"""Constants and Memory Offsets for Generation 3 Pokémon Games."""

# Game Codes at ROM offset 0x080000AC
GAME_CODE_FIRERED = b"BPRE"  # Pokémon FireRed US v1.0
GAME_CODE_EMERALD = b"BPEE"  # Pokémon Emerald US v1.0

# Memory Addresses
class FireRedOffsets:
    ROM_GAME_CODE = 0x080000AC
    PLAYER_PARTY_COUNT = 0x02024029 # 1 byte u8
    OPPONENT_PARTY_COUNT = 0x0202402A # 1 byte u8
    PLAYER_PARTY = 0x02024284   # 6 slots * 100 bytes = 600 bytes
    OPPONENT_PARTY = 0x0202402C # 6 slots * 100 bytes = 600 bytes
    BATTLE_TYPE_FLAGS = 0x02022B4C # u32 gBattleTypeFlags (0 = overworld, non-zero = in battle/transition)
    SAVE_BLOCK_1_PTR = 0x03005008
    SAVE_BLOCK_2_PTR = 0x0300500C # Contains Player Name, Gender, Trainer ID, SecurityKey
    BADGE_FLAGS_OFFSET = 0x0FE4 # SaveBlock1 + 0x0FE4 (1 byte, 8 badge bits: FLAG_BADGE01_GET - FLAG_BADGE08_GET)
    BAG_POCKET_OFFSET = 0x0310  # SaveBlock1 + 0x0310 (Items pocket: 30 slots * 4 = 120 bytes)
    BAG_ITEMS_COUNT = 30        # FireRed items pocket capacity
    BAG_POKEBALLS_OFFSET = 0x0400 # SaveBlock1 + 0x0400 (Poké Balls pocket: 13 slots * 4 = 52 bytes)
    BAG_POKEBALLS_COUNT = 13
    SECURITY_KEY_OFFSET = 0x0F20 # SaveBlock2 + 0x0F20 (u32 security/encryption key)


class EmeraldOffsets:
    ROM_GAME_CODE = 0x080000AC
    PLAYER_PARTY_COUNT = 0x020244E9 # 1 byte u8
    PLAYER_PARTY = 0x020244EC
    OPPONENT_PARTY = 0x02024744
    SAVE_BLOCK_1_PTR = 0x03005D8C
    SAVE_BLOCK_2_PTR = 0x03005D90
    BADGE_FLAGS_OFFSET = 0x1450
    BAG_POCKET_OFFSET = 0x0560
    BAG_ITEMS_COUNT = 30
    BAG_POKEBALLS_OFFSET = 0x0600
    BAG_POKEBALLS_COUNT = 16
    SECURITY_KEY_OFFSET = 0x00AC # SaveBlock2 + 0x00AC (u32 security/encryption key)


# Gen 3 Pokémon Data Sizes
PARTY_SLOT_SIZE = 100
PARTY_SLOTS_COUNT = 6
TOTAL_PARTY_SIZE = PARTY_SLOT_SIZE * PARTY_SLOTS_COUNT  # 600 bytes

SUBSTRUCT_SIZE = 12
SUBSTRUCTS_TOTAL_SIZE = 48  # 4 substructs of 12 bytes each

# Substruct Order Table (indexed by PID % 24)
# G = Growth (0), A = Attacks (1), E = EVs & Condition (2), M = Miscellaneous (3)
SUBSTRUCT_ORDER = [
    (0, 1, 2, 3),  # 0: GAEM
    (0, 1, 3, 2),  # 1: GAME
    (0, 2, 1, 3),  # 2: GEAM
    (0, 2, 3, 1),  # 3: GEMA
    (0, 3, 1, 2),  # 4: GMAE
    (0, 3, 2, 1),  # 5: GMEA
    (1, 0, 2, 3),  # 6: AGEM
    (1, 0, 3, 2),  # 7: AGME
    (1, 2, 0, 3),  # 8: AEGM
    (1, 2, 3, 0),  # 9: AEMG
    (1, 3, 0, 2),  # 10: AMGE
    (1, 3, 2, 0),  # 11: AMEG
    (2, 0, 1, 3),  # 12: EGAM
    (2, 0, 3, 1),  # 13: EGMA
    (2, 1, 0, 3),  # 14: EAGM
    (2, 1, 3, 0),  # 15: EAMG
    (2, 3, 0, 1),  # 16: EMGA
    (2, 3, 1, 0),  # 17: EMAG
    (3, 0, 1, 2),  # 18: MGAE
    (3, 0, 2, 1),  # 19: MGEA
    (3, 1, 0, 2),  # 20: MAGE
    (3, 1, 2, 0),  # 21: MAEG
    (3, 2, 0, 1),  # 22: MEGA
    (3, 2, 1, 0),  # 23: MEAG
]

# GDB Configuration Defaults
DEFAULT_GDB_HOST = "127.0.0.1"
DEFAULT_GDB_PORT = 2345

