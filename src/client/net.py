"""WebSocket Network Client for PokeCompanion.

Interacts with the Central Relay Server for peer discovery,
battle challenge relay, and cloud bank operations.
"""

import asyncio
import base64
import json
import logging
from typing import Callable, Dict, List, Optional
import websockets

from src.server.models import MessageType, NetworkMessage, PlayerState, PokemonSummary
from src.client.state import GameStateManager

logger = logging.getLogger(__name__)


class NetworkEngine:
    def __init__(self, state_mgr: GameStateManager, server_url: str = "ws://127.0.0.1:8000"):
        self.state = state_mgr
        self.server_url = server_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_running = False
        self.player_id: str = f"trainer_{id(self) % 10000}"

        # Callbacks for GUI or Event Loop
        self.on_player_list_changed: Optional[Callable[[List[dict]], None]] = None
        self.on_challenge_received: Optional[Callable[[str, str, dict], None]] = None
        self.on_battle_ready: Optional[Callable[[str, bytes], None]] = None
        self.on_ledger_updated: Optional[Callable[[Dict[int, int]], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    async def connect(self, player_id: Optional[str] = None):
        if player_id:
            self.player_id = player_id
        endpoint = f"{self.server_url}/ws/{self.player_id}"
        self.ws = await websockets.connect(endpoint)
        self.is_running = True
        logger.info("Connected to relay server at %s", endpoint)
        asyncio.create_task(self._listen_loop())
        # Initial state sync
        await self.sync_state()

    async def disconnect(self):
        self.is_running = False
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def _send(self, msg: NetworkMessage):
        if self.ws and not self.ws.closed:
            await self.ws.send(msg.model_dump_json())

    async def sync_state(self):
        """Builds player summary from state and transmits SYNC_STATE to server."""
        party_summaries = []
        for mon in self.state.party:
            party_summaries.append(
                PokemonSummary(
                    species_id=mon.species,
                    species_name=mon.species_name,
                    nickname=mon.nickname,
                    level=mon.level,
                    hp=mon.current_hp,
                    max_hp=mon.max_hp,
                    moves=mon.moves,
                )
            )

        player_state = PlayerState(
            player_id=self.player_id,
            trainer_name=self.state.player_name,
            game_code=self.state.game_code or "BPRE",
            badges_count=sum(self.state.badges),
            badge_bits=self.state.badge_byte,
            party=party_summaries,
        )

        msg = NetworkMessage(
            type=MessageType.SYNC_STATE,
            sender_id=self.player_id,
            payload={"state": player_state.model_dump()},
        )
        await self._send(msg)

    async def send_challenge(self, target_player_id: str):
        """Sends a battle challenge with local 600-byte party (base64 encoded)."""
        party_b64 = base64.b64encode(self.state.raw_party_bytes).decode("ascii")
        msg = NetworkMessage(
            type=MessageType.CHALLENGE_REQ,
            sender_id=self.player_id,
            target_id=target_player_id,
            payload={
                "trainer_name": self.state.player_name,
                "party_b64": party_b64,
            },
        )
        await self._send(msg)
        logger.info("Sent battle challenge to %s", target_player_id)

    async def accept_challenge(self, challenger_id: str, incoming_party_b64: str):
        """Accepts challenge, sends back local 600 bytes, and injects opponent party."""
        # 1. Decode opponent party and inject into RAM
        opponent_party_bytes = base64.b64decode(incoming_party_b64)
        await self.state.inject_opponent_party(opponent_party_bytes)

        # 2. Reply to challenger with our 600-byte party so challenger can also inject
        my_party_b64 = base64.b64encode(self.state.raw_party_bytes).decode("ascii")
        reply = NetworkMessage(
            type=MessageType.CHALLENGE_ACCEPT,
            sender_id=self.player_id,
            target_id=challenger_id,
            payload={
                "trainer_name": self.state.player_name,
                "party_b64": my_party_b64,
            },
        )
        await self._send(reply)

        if self.on_battle_ready:
            self.on_battle_ready(challenger_id, opponent_party_bytes)

    async def decline_challenge(self, challenger_id: str):
        msg = NetworkMessage(
            type=MessageType.CHALLENGE_DECLINE,
            sender_id=self.player_id,
            target_id=challenger_id,
        )
        await self._send(msg)

    async def deposit_item(self, item_id: int, quantity: int = 1):
        msg = NetworkMessage(
            type=MessageType.CLOUD_ITEM_DEPOSIT,
            sender_id=self.player_id,
            payload={"item_id": item_id, "quantity": quantity},
        )
        await self._send(msg)

    async def withdraw_item(self, item_id: int, quantity: int = 1):
        msg = NetworkMessage(
            type=MessageType.CLOUD_ITEM_WITHDRAW,
            sender_id=self.player_id,
            payload={"item_id": item_id, "quantity": quantity},
        )
        await self._send(msg)

    async def _listen_loop(self):
        try:
            while self.is_running and self.ws:
                raw_text = await self.ws.recv()
                data = json.loads(raw_text)
                msg = NetworkMessage(**data)

                if msg.type == MessageType.PLAYER_LIST:
                    players = msg.payload.get("players", [])
                    if self.on_player_list_changed:
                        self.on_player_list_changed(players)

                elif msg.type == MessageType.CHALLENGE_REQ:
                    challenger = msg.sender_id
                    name = msg.payload.get("trainer_name", "Unknown")
                    if self.on_challenge_received:
                        self.on_challenge_received(challenger, name, msg.payload)

                elif msg.type == MessageType.CHALLENGE_ACCEPT:
                    opp_b64 = msg.payload.get("party_b64", "")
                    if opp_b64:
                        opp_bytes = base64.b64decode(opp_b64)
                        # Inject into opponent party memory
                        await self.state.inject_opponent_party(opp_bytes)
                        if self.on_battle_ready:
                            self.on_battle_ready(msg.sender_id, opp_bytes)

                elif msg.type == MessageType.LEDGER_UPDATE:
                    ledger = msg.payload.get("ledger", {})
                    # keys might come back as string from JSON, parse to int
                    parsed_ledger = {int(k): v for k, v in ledger.items()}
                    if self.on_ledger_updated:
                        self.on_ledger_updated(parsed_ledger)

                elif msg.type == MessageType.ESCROW_ERROR:
                    err = msg.payload.get("error", "Escrow transaction failed.")
                    if self.on_error:
                        self.on_error(err)

        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed.")
        except Exception as e:
            logger.error("Error in network listen loop: %s", e)
