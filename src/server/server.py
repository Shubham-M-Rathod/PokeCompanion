"""Central Relay Server for PokeCompanion NetBridge.

Handles:
1. Lobby / Peer Discovery (Tracks online trainers, badges, and team summaries)
2. Battle Broker (Dispatches battle challenges and relays 600-byte party data)
3. Cloud Bank Service (Atomic escrow ledger for shared items)
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.server.models import MessageType, NetworkMessage, PlayerState

logger = logging.getLogger("NetBridgeRelay")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PokeCompanion NetBridge Relay Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RelayManager:
    def __init__(self):
        # Active connections: player_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Cached player states: player_id -> PlayerState
        self.player_states: Dict[str, PlayerState] = {}
        # Atomic Shared Cloud Bag Ledger: item_id -> quantity
        self.cloud_ledger: Dict[int, int] = {
            0x000D: 5,  # 5 Potions initial public pool
            0x0004: 10, # 10 Poké Balls initial public pool
        }

    async def connect(self, player_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[player_id] = websocket
        logger.info("Player %s connected. Total online: %d", player_id, len(self.active_connections))
        # Send current ledger and player list to the newly connected player
        await self.send_personal_message(
            NetworkMessage(
                type=MessageType.LEDGER_UPDATE,
                sender_id="SERVER",
                payload={"ledger": self.cloud_ledger},
            ),
            player_id,
        )
        await self.broadcast_player_list()

    async def disconnect(self, player_id: str):
        if player_id in self.active_connections:
            del self.active_connections[player_id]
        if player_id in self.player_states:
            del self.player_states[player_id]
        logger.info("Player %s disconnected. Total online: %d", player_id, len(self.active_connections))
        await self.broadcast(
            NetworkMessage(
                type=MessageType.PLAYER_LEFT,
                sender_id="SERVER",
                payload={"player_id": player_id},
            )
        )
        await self.broadcast_player_list()

    async def send_personal_message(self, message: NetworkMessage, player_id: str):
        ws = self.active_connections.get(player_id)
        if ws:
            try:
                await ws.send_text(message.model_dump_json())
            except Exception as e:
                logger.error("Failed to send message to %s: %s", player_id, e)

    async def broadcast(self, message: NetworkMessage, exclude: Optional[str] = None):
        payload_str = message.model_dump_json()
        for pid, ws in list(self.active_connections.items()):
            if pid != exclude:
                try:
                    await ws.send_text(payload_str)
                except Exception as e:
                    logger.error("Error broadcasting to %s: %s", pid, e)

    async def broadcast_player_list(self):
        players_data = [state.model_dump() for state in self.player_states.values()]
        msg = NetworkMessage(
            type=MessageType.PLAYER_LIST,
            sender_id="SERVER",
            payload={"players": players_data},
        )
        await self.broadcast(msg)

    async def handle_deposit(self, player_id: str, item_id: int, quantity: int) -> bool:
        """Adds items into cloud escrow ledger."""
        self.cloud_ledger[item_id] = self.cloud_ledger.get(item_id, 0) + quantity
        logger.info("Player %s deposited item 0x%04X x%d. New balance: %d", player_id, item_id, quantity, self.cloud_ledger[item_id])
        await self.broadcast(
            NetworkMessage(
                type=MessageType.LEDGER_UPDATE,
                sender_id="SERVER",
                payload={"ledger": self.cloud_ledger},
            )
        )
        return True

    async def handle_withdraw(self, player_id: str, item_id: int, quantity: int) -> bool:
        """Validates and withdraws items from cloud escrow ledger."""
        current_qty = self.cloud_ledger.get(item_id, 0)
        if current_qty < quantity:
            logger.warning("Withdrawal rejected: insufficient item 0x%04X (requested %d, available %d)", item_id, quantity, current_qty)
            await self.send_personal_message(
                NetworkMessage(
                    type=MessageType.ESCROW_ERROR,
                    sender_id="SERVER",
                    target_id=player_id,
                    payload={"error": "Insufficient item quantity in cloud ledger."},
                ),
                player_id,
            )
            return False

        self.cloud_ledger[item_id] = current_qty - quantity
        if self.cloud_ledger[item_id] == 0:
            del self.cloud_ledger[item_id]

        logger.info("Player %s withdrew item 0x%04X x%d.", player_id, item_id, quantity)

        # Notify the withdrawing player of approval so they can inject into RAM
        await self.send_personal_message(
            NetworkMessage(
                type=MessageType.CLOUD_ITEM_WITHDRAW_OK,
                sender_id="SERVER",
                target_id=player_id,
                payload={"item_id": item_id, "quantity": quantity},
            ),
            player_id,
        )

        await self.broadcast(
            NetworkMessage(
                type=MessageType.LEDGER_UPDATE,
                sender_id="SERVER",
                payload={"ledger": self.cloud_ledger},
            )
        )
        return True


manager = RelayManager()


@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "online_players": len(manager.active_connections),
        "ledger_items_count": len(manager.cloud_ledger),
    }


@app.get("/lobby")
async def get_lobby():
    return {
        "players": [p.model_dump() for p in manager.player_states.values()],
        "ledger": manager.cloud_ledger,
    }


@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: str):
    await manager.connect(player_id, websocket)
    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                msg = NetworkMessage(**data)
            except Exception as parse_err:
                logger.warning("Malformed message from %s: %s", player_id, parse_err)
                continue

            msg.sender_id = player_id

            if msg.type == MessageType.SYNC_STATE:
                state_data = msg.payload.get("state")
                if state_data:
                    manager.player_states[player_id] = PlayerState(**state_data)
                    await manager.broadcast_player_list()

            elif msg.type in (MessageType.CHALLENGE_REQ, MessageType.CHALLENGE_ACCEPT, MessageType.CHALLENGE_DECLINE, MessageType.BATTLE_READY, MessageType.ITEM_GIFT):
                # Route direct message to target player
                if msg.target_id:
                    await manager.send_personal_message(msg, msg.target_id)

            elif msg.type == MessageType.CLOUD_ITEM_DEPOSIT:
                item_id = msg.payload.get("item_id")
                qty = msg.payload.get("quantity", 1)
                if item_id and qty > 0:
                    await manager.handle_deposit(player_id, item_id, qty)

            elif msg.type == MessageType.CLOUD_ITEM_WITHDRAW:
                item_id = msg.payload.get("item_id")
                qty = msg.payload.get("quantity", 1)
                if item_id and qty > 0:
                    await manager.handle_withdraw(player_id, item_id, qty)

    except WebSocketDisconnect:
        await manager.disconnect(player_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", player_id, e)
        await manager.disconnect(player_id)

