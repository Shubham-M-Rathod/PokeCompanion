"""Generation 3 Pokémon Substruct Cryptography and Checksum Engine.

References:
- 100-byte Pokémon data structure in Gen 3 (FireRed, LeafGreen, Ruby, Sapphire, Emerald).
- Bytes 0x00 - 0x1F: Unencrypted data (PID, OTID, Nickname, Language, Flags, Checksum at 0x1C-0x1D).
- Bytes 0x20 - 0x4F: 48 bytes encrypted substructs (4 blocks of 12 bytes: Growth, Attacks, EVs, Misc).
- Bytes 0x50 - 0x63: Battle stats (Level, HP, Max HP, Attack, Defense, Speed, SpAtk, SpDef).
"""

import struct
from typing import Tuple
from src.core.constants import SUBSTRUCT_ORDER, SUBSTRUCT_SIZE, SUBSTRUCTS_TOTAL_SIZE


def calculate_checksum(decrypted_substructs: bytes) -> int:
    """Calculates the 16-bit checksum of the 48-byte decrypted substructs.
    
    The checksum is the sum of all 24 16-bit unsigned integers (little-endian),
    masked to 16 bits.
    """
    if len(decrypted_substructs) != SUBSTRUCTS_TOTAL_SIZE:
        raise ValueError(f"Decrypted substructs must be {SUBSTRUCTS_TOTAL_SIZE} bytes, got {len(decrypted_substructs)}")
    
    words = struct.unpack("<24H", decrypted_substructs)
    return sum(words) & 0xFFFF


def xor_crypt(substruct_bytes: bytes, key: int) -> bytes:
    """XORs 48 bytes with a 32-bit key.
    
    The 48 bytes are treated as 12 little-endian 32-bit unsigned integers,
    each XORed with key. Because XOR is symmetric, this function both encrypts
    and decrypts.
    """
    if len(substruct_bytes) != SUBSTRUCTS_TOTAL_SIZE:
        raise ValueError(f"Buffer must be {SUBSTRUCTS_TOTAL_SIZE} bytes, got {len(substruct_bytes)}")
    
    words = struct.unpack("<12I", substruct_bytes)
    xored = [w ^ key for w in words]
    return struct.pack("<12I", *xored)


def decrypt_substructs(raw_substructs: bytes, pid: int, otid: int) -> Tuple[bytes, bytes, bytes, bytes]:
    """Decrypts and reorders the 48-byte substruct buffer into canonical order.
    
    Returns:
        (growth_block, attacks_block, evs_block, misc_block)
        Each block is 12 bytes in length.
    """
    key = (pid ^ otid) & 0xFFFFFFFF
    decrypted_raw = xor_crypt(raw_substructs, key)
    
    # Split into 4 chunks of 12 bytes based on the order in the encrypted buffer
    chunks = [
        decrypted_raw[i * SUBSTRUCT_SIZE : (i + 1) * SUBSTRUCT_SIZE]
        for i in range(4)
    ]
    
    # Order mapping determined by PID % 24
    order_index = pid % 24
    order = SUBSTRUCT_ORDER[order_index]
    
    # order tuple maps chunk_position -> block_type (0=G, 1=A, 2=E, 3=M)
    canonical = [None] * 4
    for pos, block_type in enumerate(order):
        canonical[block_type] = chunks[pos]
    
    return tuple(canonical)  # type: ignore


def encrypt_substructs(
    growth: bytes, attacks: bytes, evs: bytes, misc: bytes, pid: int, otid: int
) -> bytes:
    """Orders canonical blocks according to (PID % 24) and encrypts them with (PID ^ OTID).
    
    Returns:
        48-byte encrypted buffer ready to be written to memory at offset 0x20.
    """
    if any(len(b) != SUBSTRUCT_SIZE for b in (growth, attacks, evs, misc)):
        raise ValueError("Each substruct block must be exactly 12 bytes.")
    
    canonical = [growth, attacks, evs, misc]
    order_index = pid % 24
    order = SUBSTRUCT_ORDER[order_index]
    
    # Arrange canonical blocks into the physical order required for this PID
    ordered_bytes = bytearray(SUBSTRUCTS_TOTAL_SIZE)
    for pos, block_type in enumerate(order):
        ordered_bytes[pos * SUBSTRUCT_SIZE : (pos + 1) * SUBSTRUCT_SIZE] = canonical[block_type]
    
    key = (pid ^ otid) & 0xFFFFFFFF
    return xor_crypt(bytes(ordered_bytes), key)
