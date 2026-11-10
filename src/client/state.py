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


def modify_bag_deposit(
    raw_bag: bytes, capacity: int, security_key: int, item_id: int, quantity: int = 1
) -> Tuple[bool, bytes]:
    """Decrements or removes an item from raw bag RAM, compacting subsequent slots.
    
    Returns:
        (success, updated_raw_bag_bytes)
    """
    xor_mask = security_key & 0xFFFF
    slots = []
    found_idx = -1

    for i in range(capacity):
        chunk = raw_bag[i * 4 : (i + 1) * 4]
        if len(chunk) < 4:
            break
        iid, raw_q = struct.unpack("<HH", chunk)
        cur_qty = raw_q ^ xor_mask
        if iid != 0 and found_idx == -1 and iid == item_id:
            found_idx = i
        slots.append([iid, cur_qty if iid != 0 else 0])

    while len(slots) < capacity:
        slots.append([0, 0])

    if found_idx == -1:
        return False, raw_bag  # Item not in bag

    cur_iid, cur_qty = slots[found_idx]
    if cur_qty < quantity:
        return False, raw_bag  # Insufficient quantity

    new_qty = cur_qty - quantity
    if new_qty > 0:
        slots[found_idx][1] = new_qty
    else:
        # Remove item and shift subsequent items down (compacting)
        slots.pop(found_idx)
        # Append empty slot at the end
        slots.append([0, 0])

    # Re-encode slots into raw bytes with XOR security mask
    out = bytearray(capacity * 4)
    for i, (iid, q) in enumerate(slots[:capacity]):
        stored_q = (q ^ xor_mask) if iid != 0 else xor_mask
        struct.pack_into("<HH", out, i * 4, iid, stored_q)

    return True, bytes(out)


def modify_bag_withdraw(
    raw_bag: bytes, capacity: int, security_key: int, item_id: int, quantity: int = 1
) -> Tuple[bool, bytes]:
    """Injects or increments an item in raw bag RAM.
    
    Returns:
        (success, updated_raw_bag_bytes)
    """
    xor_mask = security_key & 0xFFFF
    slots = []
    existing_idx = -1
    first_empty_idx = -1

    for i in range(capacity):
        chunk = raw_bag[i * 4 : (i + 1) * 4]
        if len(chunk) < 4:
            break
        iid, raw_q = struct.unpack("<HH", chunk)
        cur_qty = raw_q ^ xor_mask if iid != 0 else 0
        if iid != 0 and iid == item_id and existing_idx == -1:
            existing_idx = i
        if iid == 0 and first_empty_idx == -1:
            first_empty_idx = i
        slots.append([iid, cur_qty])

    while len(slots) < capacity:
        if first_empty_idx == -1:
            first_empty_idx = len(slots)
        slots.append([0, 0])

    if existing_idx != -1:
        # Merge into existing stack
        new_qty = slots[existing_idx][1] + quantity
        if new_qty > 999:
            return False, raw_bag  # Stack overflow
        slots[existing_idx][1] = new_qty
    else:
        # Insert into first empty slot
        if first_empty_idx == -1:
            return False, raw_bag  # Bag is completely full
        slots[first_empty_idx] = [item_id, quantity]

    # Re-encode slots with XOR security mask
    out = bytearray(capacity * 4)
    for i, (iid, q) in enumerate(slots[:capacity]):
        stored_q = (q ^ xor_mask) if iid != 0 else xor_mask
        struct.pack_into("<HH", out, i * 4, iid, stored_q)

    return True, bytes(out)


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
        self.battle_type_flags: int = 0
        self.opponent_first_pid: int = 0

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

            # 2. Read each 100-byte slot individually (avoids mGBA GDB packet buffer limit)
            new_party = []
            party_bytes = bytearray(TOTAL_PARTY_SIZE)
            for slot_idx in range(party_count):
                slot_addr = self.offsets.PLAYER_PARTY + (slot_idx * PARTY_SLOT_SIZE)
                slot_bytes = await self.gdb.read_memory(slot_addr, PARTY_SLOT_SIZE)
                if len(slot_bytes) == PARTY_SLOT_SIZE:
                    party_bytes[slot_idx * PARTY_SLOT_SIZE : (slot_idx + 1) * PARTY_SLOT_SIZE] = slot_bytes
                    mon = Pokemon.from_bytes(slot_bytes)
                    if mon.is_valid() and verify_pokemon_checksum(mon):
                        new_party.append(mon)
            self.raw_party_bytes = bytes(party_bytes)
            self.party = new_party
            return self.party
        except Exception as e:
            logger.error("Error reading party: %s", e)
            return []

    def _get_pocket_params(self, item_id: int) -> Tuple[int, int]:
        """Returns (pocket_offset, capacity) based on whether item is a Poké Ball or general item."""
        if 0x0001 <= item_id <= 0x000C:
            return getattr(self.offsets, "BAG_POKEBALLS_OFFSET", 0x0400), getattr(self.offsets, "BAG_POKEBALLS_COUNT", 13)
        return getattr(self.offsets, "BAG_POCKET_OFFSET", 0x0310), getattr(self.offsets, "BAG_ITEMS_COUNT", 30)

    async def poll_bag(self) -> List[Tuple[int, int, str]]:
        """Reads both Items Pocket and Poké Balls Pocket from SaveBlock1."""
        try:
            sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
            sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
            if sb1_addr < 0x02000000 or sb1_addr > 0x0203E000:
                return []

            # 1. Read Items Pocket (30 slots * 4 bytes = 120 bytes in 3 chunks of 40 bytes)
            items_addr = sb1_addr + self.offsets.BAG_POCKET_OFFSET
            items_capacity = self.offsets.BAG_ITEMS_COUNT
            raw_items = bytearray()
            for chunk_idx in range(3):
                chunk = await self.gdb.read_memory(items_addr + (chunk_idx * 40), 40)
                raw_items.extend(chunk)
            pocket_items = parse_bag_pocket(bytes(raw_items), items_capacity, self.security_key)

            # 2. Read Poké Balls Pocket (13 slots * 4 bytes = 52 bytes in 2 chunks: 40 + 12)
            balls_offset = getattr(self.offsets, "BAG_POKEBALLS_OFFSET", 0x0400)
            balls_capacity = getattr(self.offsets, "BAG_POKEBALLS_COUNT", 13)
            balls_addr = sb1_addr + balls_offset
            raw_balls = bytearray()
            raw_balls.extend(await self.gdb.read_memory(balls_addr, 40))
            raw_balls.extend(await self.gdb.read_memory(balls_addr + 40, 12))
            pocket_balls = parse_bag_pocket(bytes(raw_balls), balls_capacity, self.security_key)

            self.bag_items = pocket_items + pocket_balls
            return self.bag_items
        except Exception as e:
            logger.error("Could not read bag items: %s", e)
            return []

    async def ram_deposit_item(self, item_id: int, quantity: int = 1) -> bool:
        """Removes quantity of item_id from the appropriate SaveBlock1 bag pocket."""
        pocket_offset, capacity = self._get_pocket_params(item_id)
        total_bytes = capacity * 4

        async with self.gdb.transaction():
            try:
                sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
                sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
                if sb1_addr < 0x02000000 or sb1_addr > 0x0203E000:
                    logger.error("Invalid SaveBlock1 pointer: 0x%08X", sb1_addr)
                    return False

                bag_addr = sb1_addr + pocket_offset

                # Read current pocket bytes in 40-byte chunks
                raw_pocket = bytearray()
                for chunk_offset in range(0, total_bytes, 40):
                    chunk_len = min(40, total_bytes - chunk_offset)
                    chunk = await self.gdb.read_memory(bag_addr + chunk_offset, chunk_len)
                    raw_pocket.extend(chunk)

                if not self.security_key:
                    await self.poll_trainer_info()

                ok, updated_pocket = modify_bag_deposit(
                    bytes(raw_pocket), capacity, self.security_key, item_id, quantity
                )
                if not ok:
                    logger.warning("Could not deposit item 0x%04X: not found or insufficient quantity.", item_id)
                    return False

                # Write updated pocket bytes back in 40-byte chunks
                for chunk_offset in range(0, total_bytes, 40):
                    chunk_len = min(40, total_bytes - chunk_offset)
                    chunk = updated_pocket[chunk_offset : chunk_offset + chunk_len]
                    await self.gdb.write_memory(bag_addr + chunk_offset, chunk)

                # Refresh cached bag
                await self.poll_bag()
                logger.info("Successfully deposited item 0x%04X x%d from in-game RAM.", item_id, quantity)
                return True
            except Exception as e:
                logger.error("Error modifying RAM bag for deposit: %s", e)
                return False

    async def ram_withdraw_item(self, item_id: int, quantity: int = 1) -> bool:
        """Injects quantity of item_id into the appropriate SaveBlock1 bag pocket."""
        pocket_offset, capacity = self._get_pocket_params(item_id)
        total_bytes = capacity * 4

        async with self.gdb.transaction():
            try:
                sb1_ptr_bytes = await self.gdb.read_memory(self.offsets.SAVE_BLOCK_1_PTR, 4)
                sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
                if sb1_addr < 0x02000000 or sb1_addr > 0x0203E000:
                    logger.error("Invalid SaveBlock1 pointer: 0x%08X", sb1_addr)
                    return False

                bag_addr = sb1_addr + pocket_offset

                # Read current pocket bytes in 40-byte chunks
                raw_pocket = bytearray()
                for chunk_offset in range(0, total_bytes, 40):
                    chunk_len = min(40, total_bytes - chunk_offset)
                    chunk = await self.gdb.read_memory(bag_addr + chunk_offset, chunk_len)
                    raw_pocket.extend(chunk)

                if not self.security_key:
                    await self.poll_trainer_info()

                ok, updated_pocket = modify_bag_withdraw(
                    bytes(raw_pocket), capacity, self.security_key, item_id, quantity
                )
                if not ok:
                    logger.warning("Could not withdraw item 0x%04X: in-game pocket is full.", item_id)
                    return False

                # Write updated pocket bytes back in 40-byte chunks
                for chunk_offset in range(0, total_bytes, 40):
                    chunk_len = min(40, total_bytes - chunk_offset)
                    chunk = updated_pocket[chunk_offset : chunk_offset + chunk_len]
                    await self.gdb.write_memory(bag_addr + chunk_offset, chunk)

                # Refresh cached bag
                await self.poll_bag()
                logger.info("Successfully withdrew item 0x%04X x%d into in-game RAM.", item_id, quantity)
                return True
            except Exception as e:
                logger.error("Error modifying RAM bag for withdrawal: %s", e)
                return False

    async def poll_battle_state(self) -> None:
        """Reads gBattleTypeFlags and current enemy slot-0 PID for battle start detection."""
        battle_flags_addr = getattr(self.offsets, "BATTLE_TYPE_FLAGS", 0)
        if not battle_flags_addr:
            self.battle_type_flags = 0
            self.opponent_first_pid = 0
            return
        try:
            flags_bytes = await self.gdb.read_memory(battle_flags_addr, 4)
            self.battle_type_flags = struct.unpack("<I", flags_bytes)[0]
            if self.battle_type_flags != 0:
                opp_pid_bytes = await self.gdb.read_memory(self.offsets.OPPONENT_PARTY, 4)
                self.opponent_first_pid = struct.unpack("<I", opp_pid_bytes)[0]
            else:
                self.opponent_first_pid = 0
        except Exception as e:
            logger.debug("Could not read battle state: %s", e)

    async def update_all(self) -> None:
        """Executes a full polling cycle inside a single non-blocking GDB transaction."""
        async with self.gdb.transaction():
            if not self.game_code:
                await self.detect_game_version()

            await self.poll_trainer_info()
            await self.poll_party()
            await self.poll_badges()
            await self.poll_bag()
            await self.poll_battle_state()

    async def inject_opponent_party(self, opponent_party_600_bytes: bytes) -> bool:
        """Injects a 600-byte party into Opponent Party RAM in 100-byte chunks (FR-5)."""
        if len(opponent_party_600_bytes) != TOTAL_PARTY_SIZE:
            raise ValueError(f"Opponent party payload must be {TOTAL_PARTY_SIZE} bytes.")

        # Count active opponent Pokémon
        opp_count = 0
        for i in range(PARTY_SLOTS_COUNT):
            slot_bytes = opponent_party_600_bytes[i * PARTY_SLOT_SIZE : (i + 1) * PARTY_SLOT_SIZE]
            pid = struct.unpack("<I", slot_bytes[0:4])[0]
            if pid != 0:
                opp_count += 1
        opp_count = max(1, min(6, opp_count))

        async with self.gdb.transaction():
            target_addr = self.offsets.OPPONENT_PARTY
            all_ok = True
            for i in range(PARTY_SLOTS_COUNT):
                chunk = opponent_party_600_bytes[i * PARTY_SLOT_SIZE : (i + 1) * PARTY_SLOT_SIZE]
                ok = await self.gdb.write_memory(target_addr + (i * PARTY_SLOT_SIZE), chunk)
                if not ok:
                    all_ok = False

            # Set opponent party count
            if hasattr(self.offsets, "OPPONENT_PARTY_COUNT"):
                await self.gdb.write_memory(self.offsets.OPPONENT_PARTY_COUNT, bytes([opp_count]))

            if all_ok:
                logger.info("Successfully injected opponent party (%d Pokémon, %d bytes) to 0x%08X", opp_count, len(opponent_party_600_bytes), target_addr)
            else:
                logger.error("Failed to inject opponent party to 0x%08X", target_addr)
            return all_ok
