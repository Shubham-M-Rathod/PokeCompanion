"""Unit tests for Pokemon model parsing and Gen 3 string codecs."""

import struct
from src.core.pokemon import Pokemon, decode_gen3_string, encode_gen3_string
from src.core.crypto import encrypt_substructs, calculate_checksum
from src.core.constants import SUBSTRUCT_ORDER


def test_gen3_string_codec():
    original = "PIKACHU"
    encoded = encode_gen3_string(original, 10)
    assert len(encoded) == 10
    decoded = decode_gen3_string(encoded)
    assert decoded == original


def test_pokemon_from_bytes():
    pid = 0x12345678
    otid = 0x87654321

    # Prepare Substructs
    growth = struct.pack("<HHI2B2x", 25, 0, 1000, 0, 70)  # Species 25 = Pikachu (12 bytes)
    attacks = struct.pack("<HHHHBBBB", 84, 85, 0, 0, 30, 20, 0, 0)
    evs = struct.pack("<BBBBBB6x", 10, 20, 30, 40, 50, 60)
    iv_field = 31 | (31 << 5) | (31 << 10) | (31 << 15) | (31 << 20) | (31 << 25)
    misc = struct.pack("<BB2xII", 0, 0, iv_field, 0)

    # Checksum calculation over ordered decrypted substructs
    order = SUBSTRUCT_ORDER[pid % 24]
    canonical = [growth, attacks, evs, misc]
    ordered_decrypted = bytearray(48)
    for pos, blk_idx in enumerate(order):
        ordered_decrypted[pos * 12 : (pos + 1) * 12] = canonical[blk_idx]
    csum = calculate_checksum(bytes(ordered_decrypted))

    encrypted = encrypt_substructs(growth, attacks, evs, misc, pid, otid)

    # Build 100-byte structure
    header = bytearray(32)
    header[0:4] = struct.pack("<I", pid)
    header[4:8] = struct.pack("<I", otid)
    header[8:18] = encode_gen3_string("SPARK", 10)
    header[28:30] = struct.pack("<H", csum)

    battle_stats = struct.pack("<IBB7H", 0, 25, 0, 60, 60, 45, 30, 70, 40, 40)

    raw_mon = bytes(header) + encrypted + battle_stats
    assert len(raw_mon) == 100

    mon = Pokemon.from_bytes(raw_mon)
    assert mon.is_valid() is True
    assert mon.nickname == "SPARK"
    assert mon.species == 25
    assert mon.species_name == "Pikachu"
    assert mon.level == 25
    assert mon.hp_iv == 31
    assert mon.atk_iv == 31
    assert mon.current_hp == 60
