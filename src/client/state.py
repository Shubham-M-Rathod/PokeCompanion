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
    SUBSTRUCT_ORDER,
)
from src.core.pokemon import Pokemon, decode_gen3_string
from src.core.crypto import calculate_checksum, decrypt_substructs
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


def parse_bag_pocket(raw_bag: bytes, capacity: int, security_key: int = 0) -> List[Tuple[int, int, str]]:
    """Parses an array of [u16 item_id, u16 quantity] from Bag Pocket RAM, handling XOR obfuscation."""
    items = []
    xor_mask = security_key & 0xFFFF

    for i in range(capacity):
        chunk = raw_bag[i * 4 : (i + 1) * 4]
        if len(chunk) < 4:
            break
        item_id, raw_qty = struct.unpack("<HH", chunk)
        if item_id == 0:
            continue

        # Valid item IDs in Gen 3 are 1..375
        if not (1 <= item_id <= 375):
            continue

        # Decrypt quantity using security key if applicable
        qty = raw_qty ^ xor_mask
        if not (1 <= qty <= 999):
            # Fallback to raw quantity if XOR produces invalid value
            if 1 <= raw_qty <= 999:
                qty = raw_qty
            else:
                continue

        items.append((item_id, qty, get_item_name(item_id)))
    return items


def verify_pokemon_checksum(mon: Pokemon) -> bool:
    """Recalculates and verifies the 16-bit additive checksum of the 48-byte substructs."""
    if not mon.is_valid() or len(mon.raw_data) < PARTY_SLOT_SIZE:
        return False
    
    raw_substructs = mon.raw_data[32:80]
    g, a, e, m = decrypt_substructs(raw_substructs, mon.pid, mon.otid)
    
    order = SUBSTRUCT_ORDER[mon.pid % 24]
    canonical = [g, a, e, m]
    ordered_decrypted = bytearray(48)
    for pos, blk_idx in enumerate(order):
        ordered_decrypted[pos * 12 : (pos + 1) * 12] = canonical[blk_idx]

    calc_csum = calculate_checksum(bytes(ordered_decrypted))
    return calc_csum == mon.checksum


def parse_party_data(raw_party: bytes, party_count: int) -> List[Pokemon]:
    """Parses only the active Pokemon slots (up to party_count) and validates checksums."""
    party = []
    if not (1 <= party_count <= 6):
        return []

    for slot_idx in range(party_count):
        offset = slot_idx * PARTY_SLOT_SIZE
        slot_bytes = raw_party[offset : offset + PARTY_SLOT_SIZE]
        if len(slot_bytes) == PARTY_SLOT_SIZE:
            mon = Pokemon.from_bytes(slot_bytes)
            if mon.is_valid() and verify_pokemon_checksum(mon):
                party.append(mon)
    return party


class GameStateManager:
    """Tracks and caches live game memory for PokeCompanion."""

    def __init__(self, gdb_client: GDBClient):
        self.gdb = gdb_client
        self.game_code: Optional[str] = None
        self.offsets = FireRedOffsets

        # Cached Game State
        self.party_count: int = 0
        self.player_name: str = "Trainer"
        self.trainer_id: int = 0
        self.secret_id: int = 0
        self.security_key: int = 0
        self.badge_byte: int = 0
        self.badges: List[bool] = [False] * 8
        self.party: List[Pokemon] = []
        self.bag_items: List[Tuple[int, int, str]] = []
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
        """Reads SaveBlock2 for player name, trainer ID, and security key."""
        try:
            sb2_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_2_PTR, 4)
            sb2_addr = struct.unpack("<I", sb2_ptr_bytes)[0]
            # Valid EWRAM pointer range on GBA
            if sb2_addr < 0x02000000 or sb2_addr > 0x0203E000:
                return

            header_bytes = await self.gdb.read_memory(sb2_addr, 16)
            name, tid, sid = parse_trainer_header(header_bytes)
            if name:
                self.player_name = name
            self.trainer_id = tid
            self.secret_id = sid

            # Read security key at SaveBlock2 + SECURITY_KEY_OFFSET
            key_addr = sb2_addr + self.offsets.SECURITY_KEY_OFFSET
            key_bytes = await self.gdb.read_memory(key_addr, 4)
            self.security_key = struct.unpack("<I", key_bytes)[0]
        except Exception as e:
            logger.debug("Could not read trainer info: %s", e)

    async def poll_badges(self) -> None:
        """Reads 8 gym badges bitflags from SaveBlock1 + 0x1450."""
        try:
            sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
            sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
            if sb1_addr < 0x02000000 or sb1_addr > 0x0203E000:
                return

            badge_addr = sb1_addr + self.offsets.BADGE_FLAGS_OFFSET
            badge_data = await self.gdb.read_memory(badge_addr, 1)
            self.badge_byte = badge_data[0]
            self.badges = parse_badges(self.badge_byte)
        except Exception as e:
            logger.debug("Could not read badges: %s", e)

    async def poll_party(self) -> List[Pokemon]:
        """Reads gPlayerPartyCount and decrypts only active party slots with checksum checks."""
        try:
            # 1. Read single byte gPlayerPartyCount at 0x02024029
            count_data = await self.gdb.read_memory(self.offsets.PLAYER_PARTY_COUNT, 1)
            party_count = count_data[0]
            if party_count > 6:
                # Game is at title screen or in transition
                self.party_count = 0
                self.party = []
                return []
            self.party_count = party_count

            if party_count == 0:
                self.party = []
                return []

            # 2. Read full 600 bytes
            raw_party = await self.gdb.read_memory(self.offsets.PLAYER_PARTY, TOTAL_PARTY_SIZE)
            self.raw_party_bytes = raw_party
            self.party = parse_party_data(raw_party, party_count)
            return self.party
        except Exception as e:
            logger.debug("Error reading party: %s", e)
            return []

    async def poll_bag(self) -> List[Tuple[int, int, str]]:
        """Reads inventory pocket from SaveBlock1 using security key."""
        try:
            sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
            sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
            if sb1_addr < 0x02000000 or sb1_addr > 0x0203E000:
                return []

            bag_addr = sb1_addr + self.offsets.BAG_POCKET_OFFSET
            pocket_capacity = self.offsets.BAG_ITEMS_COUNT
            raw_bag = await self.gdb.read_memory(bag_addr, pocket_capacity * 4)
            self.bag_items = parse_bag_pocket(raw_bag, pocket_capacity, self.security_key)
            return self.bag_items
        except Exception as e:
            logger.debug("Could not read bag items: %s", e)
            return []

    async def update_all(self) -> None:
        """Executes a full polling cycle inside a single non-blocking GDB transaction."""
        async with self.gdb.transaction():
            if not self.game_code:
                await self.detect_game_version()

            await self.poll_trainer_info()
            await self.poll_party()
            await self.poll_badges()
            await self.poll_bag()

    async def inject_opponent_party(self, opponent_party_600_bytes: bytes) -> bool:
        """Injects a 600-byte party into Opponent Party RAM (FR-5)."""
        if len(opponent_party_600_bytes) != TOTAL_PARTY_SIZE:
            raise ValueError(f"Opponent party payload must be {TOTAL_PARTY_SIZE} bytes.")

        async with self.gdb.transaction():
            target_addr = self.offsets.OPPONENT_PARTY
            success = await self.gdb.write_memory(target_addr, opponent_party_600_bytes)
            if success:
                logger.info("Successfully injected opponent party (%d bytes) to 0x%08X", len(opponent_party_600_bytes), target_addr)
            else:
                logger.error("Failed to inject opponent party to 0x%08X", target_addr)
            return success
