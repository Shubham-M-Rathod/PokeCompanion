"""Unit tests for Gen 3 Pokémon Substruct Cryptography and Checksum."""

import pytest
import struct
from src.core.crypto import calculate_checksum, xor_crypt, decrypt_substructs, encrypt_substructs


def test_xor_crypt_symmetry():
    data = b"0123456789ab" * 4  # 48 bytes
    key = 0xDEADBEEF
    
    encrypted = xor_crypt(data, key)
    assert len(encrypted) == 48
    assert encrypted != data
    
    decrypted = xor_crypt(encrypted, key)
    assert decrypted == data


def test_calculate_checksum():
    # 48 zero bytes -> checksum 0
    zeros = b"\x00" * 48
    assert calculate_checksum(zeros) == 0
    
    # 24 16-bit words of value 1 -> checksum 24
    ones = struct.pack("<24H", *([1] * 24))
    assert calculate_checksum(ones) == 24
    
    # Checksum overflow wrapping test (0xFFFF + 1 = 0)
    words = [0x8000] * 2 + [0] * 22
    buf = struct.pack("<24H", *words)
    assert calculate_checksum(buf) == 0x0000


def test_encrypt_decrypt_roundtrip_all_orders():
    # Test all 24 possible PID % 24 permutations
    sample_g = b"GROWTH_BLK_1"
    sample_a = b"ATTACK_BLK_2"
    sample_e = b"EV_CONDITION"
    sample_m = b"MISCELLANEOU"
    
    otid = 0x12345678
    
    for order_idx in range(24):
        pid = 1000 * 24 + order_idx
        assert pid % 24 == order_idx
        
        encrypted = encrypt_substructs(sample_g, sample_a, sample_e, sample_m, pid, otid)
        assert len(encrypted) == 48
        
        g, a, e, m = decrypt_substructs(encrypted, pid, otid)
        assert g == sample_g
        assert a == sample_a
        assert e == sample_e
        assert m == sample_m
