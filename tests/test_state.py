"""Unit tests for GameStateManager parsing functions."""

import struct
from src.client.state import (
    parse_badges,
    parse_trainer_header,
    parse_bag_pocket,
    modify_bag_deposit,
    modify_bag_withdraw,
)
from src.core.pokemon import encode_gen3_string


def test_parse_badges():
    # 0b00000101 -> Badges 0 and 2 active (Boulder and Thunder)
    badges = parse_badges(0x05)
    assert len(badges) == 8
    assert badges[0] is True   # Boulder
    assert badges[1] is False  # Cascade
    assert badges[2] is True   # Thunder
    assert badges[3] is False

    # 0xFF -> All 8 badges active
    all_badges = parse_badges(0xFF)
    assert all(all_badges)


def test_parse_trainer_header():
    # Build 16-byte trainer header:
    # 7 bytes name: "ASH"
    # 3 bytes padding/gender
    # 2 bytes trainer ID: 12345
    # 2 bytes secret ID: 54321
    # 2 bytes padding
    header = bytearray(16)
    header[0:7] = encode_gen3_string("ASH", 7)
    struct.pack_into("<HH", header, 10, 12345, 54321)

    name, tid, sid = parse_trainer_header(bytes(header))
    assert name == "ASH"
    assert tid == 12345
    assert sid == 54321


def test_parse_bag_pocket():
    # 2 items: 10 Potions (0x000D), 5 Poké Balls (0x0004), then empty slot
    raw_bag = bytearray(12)
    struct.pack_into("<HH", raw_bag, 0, 0x000D, 10)  # Potion
    struct.pack_into("<HH", raw_bag, 4, 0x0004, 5)   # Poké Ball
    struct.pack_into("<HH", raw_bag, 8, 0x0000, 0)   # Empty

    items = parse_bag_pocket(bytes(raw_bag), 3)
    assert len(items) == 2
    assert items[0] == (0x000D, 10, "Potion")
    assert items[1] == (0x0004, 5, "Poké Ball")


def test_modify_bag_deposit_and_withdraw():
    sec_key = 0xBF202237
    xor_mask = sec_key & 0xFFFF  # 0x2237

    # Create initial bag with 3 slots:
    # Slot 0: Potion (0x000D) x 2
    # Slot 1: Star Piece (0x006D) x 1
    # Slot 2: Empty
    capacity = 3
    raw_bag = bytearray(capacity * 4)
    struct.pack_into("<HH", raw_bag, 0, 0x000D, 2 ^ xor_mask)
    struct.pack_into("<HH", raw_bag, 4, 0x006D, 1 ^ xor_mask)
    struct.pack_into("<HH", raw_bag, 8, 0x0000, xor_mask)

    # 1. Deposit 1 Potion (2 -> 1)
    ok, updated = modify_bag_deposit(bytes(raw_bag), capacity, sec_key, 0x000D, 1)
    assert ok is True
    parsed = parse_bag_pocket(updated, capacity, sec_key)
    assert parsed[0] == (0x000D, 1, "Potion")
    assert parsed[1] == (0x006D, 1, "Star Piece")

    # 2. Deposit remaining 1 Potion -> slot is removed and compacted
    ok, updated = modify_bag_deposit(updated, capacity, sec_key, 0x000D, 1)
    assert ok is True
    parsed = parse_bag_pocket(updated, capacity, sec_key)
    assert len(parsed) == 1
    assert parsed[0] == (0x006D, 1, "Star Piece")

    # Check raw memory compaction: Slot 0 is Star Piece, Slot 1 & 2 are empty
    iid0, q0 = struct.unpack_from("<HH", updated, 0)
    assert iid0 == 0x006D
    assert (q0 ^ xor_mask) == 1
    iid1, q1 = struct.unpack_from("<HH", updated, 4)
    assert iid1 == 0x0000
    assert q1 == xor_mask

    # 3. Withdraw 1 Rare Candy (0x0044) -> inserted into Slot 1
    ok, updated = modify_bag_withdraw(updated, capacity, sec_key, 0x0044, 1)
    assert ok is True
    parsed = parse_bag_pocket(updated, capacity, sec_key)
    assert len(parsed) == 2
    assert parsed[0] == (0x006D, 1, "Star Piece")
    assert parsed[1] == (0x0044, 1, "Rare Candy")

    # 4. Withdraw another Rare Candy (merge stack)
    ok, updated = modify_bag_withdraw(updated, capacity, sec_key, 0x0044, 1)
    assert ok is True
    parsed = parse_bag_pocket(updated, capacity, sec_key)
    assert len(parsed) == 2
    assert parsed[1] == (0x0044, 2, "Rare Candy")

    # 5. Overdraw / Not found check
    ok, _ = modify_bag_deposit(updated, capacity, sec_key, 0x0099, 1)  # Non-existent
    assert ok is False

    ok, _ = modify_bag_deposit(updated, capacity, sec_key, 0x0044, 99)  # Insufficient qty
    assert ok is False

