"""Pydantic data models and message schemas for PokeCompanion NetBridge."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    # Discovery & State
    SYNC_STATE = "SYNC_STATE"
    PLAYER_LIST = "PLAYER_LIST"
    PLAYER_LEFT = "PLAYER_LEFT"

    # Battle Broker
    CHALLENGE_REQ = "CHALLENGE_REQ"
    CHALLENGE_ACCEPT = "CHALLENGE_ACCEPT"
    CHALLENGE_DECLINE = "CHALLENGE_DECLINE"
    BATTLE_READY = "BATTLE_READY"

    # Cloud Bag Escrow & Item Sharing
    CLOUD_ITEM_DEPOSIT = "CLOUD_ITEM_DEPOSIT"
    CLOUD_ITEM_WITHDRAW = "CLOUD_ITEM_WITHDRAW"
    CLOUD_ITEM_WITHDRAW_OK = "CLOUD_ITEM_WITHDRAW_OK"
    ITEM_GIFT = "ITEM_GIFT"
    LEDGER_UPDATE = "LEDGER_UPDATE"
    ESCROW_ERROR = "ESCROW_ERROR"


class PokemonSummary(BaseModel):
    species_id: int
    species_name: str
    nickname: str
    level: int
    hp: int
    max_hp: int
    moves: List[int] = Field(default_factory=list)


class PlayerState(BaseModel):
    player_id: str
    trainer_name: str
    game_code: str  # BPRE or BPEE
    badges_count: int
    badge_bits: int
    party: List[PokemonSummary] = Field(default_factory=list)


class NetworkMessage(BaseModel):
    type: MessageType
    sender_id: str
    target_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

