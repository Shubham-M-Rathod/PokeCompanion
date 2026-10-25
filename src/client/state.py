"""Game State Manager for Gen 3 Live Memory Sync.

Manages polling RAM for Party, Badges, Bag Inventory, and Trainer Info,
as well as injecting opponent parties for live trainer battles.
"""

import logging
import struct
from typing import List, Optional, Tuple

from src.core.constants import (
    GAME_CODE_FIRERED,
    GAME_CODE_EMERALD,
    TOTAL_PARTY_SIZE,
    PARTY_SLOT_SIZE,
    PARTY_SLOTS_COUNT,
    FireRedOffsets,
    EmeraldOffsets,
)
from src.core.pokemon import Pokemon, decode_gen3_string
from src.core.items import get_item_name
from src.memory.gdb_client import GDBClient

logger = logging.getLogger(__name__)

BADGE_NAMES_KANTO = [
    "Boulder", "Cascade", "Thunder", "Rainbow",
    "Soul", "Marsh", "Volcano", "Earth",
]

BADGE_NAMES_HOENN = [
    "Stone", "Knuckle", "Dynamo", "Heat",
    "Balance", "Feather", "Mind", "Rain",
]


def parse_badges(badge_byte: int) -> List[bool]:
    """Extracts 8 gym badge booleans from a single byte bitmask."""
    return [bool((badge_byte >> i) & 1) for i in range(8)]


def parse_trainer_header(header_bytes: bytes) -> Tuple[str, int, int]:
    """Parses Player Name (7 bytes), Trainer ID (u16), and Secret ID (u16) from SaveBlock2."""
    if len(header_bytes) < 14:
        raise ValueError(f"Expected at least 14 bytes for trainer header, got {len(header_bytes)}")
    name = decode_gen3_string(header_bytes[0:7])
    tid, sid = struct.unpack("<HH", header_bytes[10:14])
    return name, tid, sid


def parse_bag_pocket(raw_bag: bytes, capacity: int) -> List[Tuple[int, int, str]]:
    """Parses an array of [u16 item_id, u16 quantity] from Bag Pocket RAM."""
    items = []
    for i in range(capacity):
        chunk = raw_bag[i * 4 : (i + 1) * 4]
        if len(chunk) < 4:
            break
        item_id, qty = struct.unpack("<HH", chunk)
        if item_id != 0 and qty > 0:
            items.append((item_id, qty, get_item_name(item_id)))
    return items


def parse_party_data(raw_party: bytes) -> List[Pokemon]:
    """Parses up to 6 Pokemon slots from 600 bytes of party RAM."""
    party = []
    for slot_idx in range(PARTY_SLOTS_COUNT):
        offset = slot_idx * PARTY_SLOT_SIZE
        slot_bytes = raw_party[offset : offset + PARTY_SLOT_SIZE]
        if len(slot_bytes) == PARTY_SLOT_SIZE:
            mon = Pokemon.from_bytes(slot_bytes)
            if mon.is_valid():
                party.append(mon)
    return party


class GameStateManager:
    """Tracks and caches live game memory for PokeCompanion."""

    def __init__(self, gdb_client: GDBClient):
        self.gdb = gdb_client
        self.game_code: Optional[str] = None
        self.offsets = FireRedOffsets

        # Cached Game State
        self.player_name: str = "Trainer"
        self.trainer_id: int = 0
        self.secret_id: int = 0
        self.badge_byte: int = 0
        self.badges: List[bool] = [False] * 8
        self.party: List[Pokemon] = []
        self.bag_items: List[Tuple[int, int, str]] = []  # (item_id, qty, name)
        self.raw_party_bytes: bytes = b"\x00" * TOTAL_PARTY_SIZE

    async def detect_game_version(self) -> str:
        """Reads ROM header at 0x080000AC to determine game version (FR-1)."""
        raw_code = await self.gdb.read_memory(FireRedOffsets.ROM_GAME_CODE, 4)
        if raw_code == GAME_CODE_FIRERED:
            self.game_code = "BPRE"
            self.offsets = FireRedOffsets
            logger.info("Auto-detected Pokémon FireRed (BPRE)")
        elif raw_code == GAME_CODE_EMERALD:
            self.game_code = "BPEE"
            self.offsets = EmeraldOffsets
            logger.info("Auto-detected Pokémon Emerald (BPEE)")
        else:
            code_str = raw_code.decode("ascii", errors="replace")
            self.game_code = code_str
            self.offsets = FireRedOffsets
            logger.warning("Unrecognized ROM code '%s', defaulting to FireRed offsets.", code_str)
        return self.game_code

    async def poll_trainer_info(self) -> None:
        """Reads SaveBlock2 for player name and trainer ID."""
        try:
            sb2_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_2_PTR, 4)
            sb2_addr = struct.unpack("<I", sb2_ptr_bytes)[0]
            if sb2_addr < 0x02000000 or sb2_addr > 0x03007FFF:
                return

            header_bytes = await self.gdb.read_memory(sb2_addr, 16)
            name, tid, sid = parse_trainer_header(header_bytes)
            if name:
                self.player_name = name
            self.trainer_id = tid
            self.secret_id = sid
        except Exception as e:
            logger.debug("Could not read trainer info: %s", e)

    async def poll_badges(self) -> None:
        """Reads 8 gym badges bitflags from SaveBlock1 + 0x1450."""
        try:
            sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
            sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
            if sb1_addr < 0x02000000 or sb1_addr > 0x03007FFF:
                return

            badge_addr = sb1_addr + self.offsets.BADGE_FLAGS_OFFSET
            badge_data = await self.gdb.read_memory(badge_addr, 1)
            self.badge_byte = badge_data[0]
            self.badges = parse_badges(self.badge_byte)
        except Exception as e:
            logger.debug("Could not read badges: %s", e)

    async def poll_party(self) -> List[Pokemon]:
        """Reads and decrypts all 6 player party slots (FR-3)."""
        raw_party = await self.gdb.read_memory(self.offsets.PLAYER_PARTY, TOTAL_PARTY_SIZE)
        self.raw_party_bytes = raw_party
        self.party = parse_party_data(raw_party)
        return self.party

    async def poll_bag(self) -> List[Tuple[int, int, str]]:
        """Reads inventory pocket from SaveBlock1."""
        try:
            sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
            sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
            if sb1_addr < 0x02000000 or sb1_addr > 0x03007FFF:
                return []

            bag_addr = sb1_addr + self.offsets.BAG_POCKET_OFFSET
            pocket_capacity = self.offsets.BAG_ITEMS_COUNT
            raw_bag = await self.gdb.read_memory(bag_addr, pocket_capacity * 4)
            self.bag_items = parse_bag_pocket(raw_bag, pocket_capacity)
            return self.bag_items
        except Exception as e:
            logger.debug("Could not read bag items: %s", e)
            return []

    async def update_all(self) -> None:
        """Executes a full polling cycle (Party, Badges, Bag, Trainer)."""
        if not self.game_code:
            await self.detect_game_version()

        await self.poll_party()
        await self.poll_trainer_info()
        await self.poll_badges()
        await self.poll_bag()

    async def inject_opponent_party(self, opponent_party_600_bytes: bytes) -> bool:
        """Injects a 600-byte party into Opponent Party RAM (FR-5)."""
        if len(opponent_party_600_bytes) != TOTAL_PARTY_SIZE:
            raise ValueError(f"Opponent party payload must be {TOTAL_PARTY_SIZE} bytes.")

        target_addr = self.offsets.OPPONENT_PARTY
        success = await self.gdb.write_memory(target_addr, opponent_party_600_bytes)
        if success:
            logger.info("Successfully injected opponent party (%d bytes) to 0x%08X", len(opponent_party_600_bytes), target_addr)
        else:
            logger.error("Failed to inject opponent party to 0x%08X", target_addr)
        return success
