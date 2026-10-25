"""Unit tests for GameStateManager parsing functions."""

import struct
from src.client.state import parse_badges, parse_trainer_header, parse_bag_pocket
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

