"""Gen 3 Pokémon Data Parser, Serializer, and Text Encoding."""

import struct
from dataclasses import dataclass, field
from typing import List, Optional
from src.core.crypto import decrypt_substructs, encrypt_substructs, calculate_checksum
from src.core.constants import PARTY_SLOT_SIZE, SUBSTRUCT_ORDER

# Gen 3 Character Table Mapping
CHAR_TABLE = {
    0x00: " ",
    0x01: "À", 0x02: "Á", 0x03: "Â", 0x04: "Ç", 0x05: "È", 0x06: "É", 0x07: "Ê", 0x08: "Ë",
    0x09: "Ì", 0x0B: "Î", 0x0C: "Ï", 0x0D: "Ò", 0x0E: "Ó", 0x0F: "Ô", 0x10: "Œ", 0x11: "Ù",
    0x12: "Ú", 0x13: "Û", 0x14: "Ñ", 0x15: "ß", 0x16: "à", 0x17: "á", 0x19: "ç", 0x1A: "è",
    0x1B: "é", 0x1C: "ê", 0x1D: "ë", 0x1E: "ì", 0x20: "î", 0x21: "ï", 0x22: "ò", 0x23: "ó",
    0x24: "ô", 0x25: "œ", 0x26: "ù", 0x27: "ú", 0x28: "û", 0x29: "ñ", 0x2A: "º", 0x2B: "ª",
    0x2D: "&", 0x2E: "+",
    0x51: "¿", 0x52: "¡", 0x53: "Pk", 0x54: "Mn", 0x55: "Po", 0x56: "Ké", 0x57: "Bl", 0x58: "Oc",
    0x59: "K", 0x5A: "Í", 0x5B: "%", 0x5C: "(", 0x5D: ")",
    0x68: "â", 0x6F: "í",
    0x79: "↑", 0x7A: "↓", 0x7B: "←", 0x7C: "→",
    0x84: "e", 0x85: "<", 0x86: ">",
    0xA1: "0", 0xA2: "1", 0xA3: "2", 0xA4: "3", 0xA5: "4", 0xA6: "5", 0xA7: "6", 0xA8: "7", 0xA9: "8", 0xAA: "9",
    0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…", 0xB1: "“", 0xB2: "”", 0xB3: "‘", 0xB4: "’",
    0xB5: "♂", 0xB6: "♀", 0xB7: "$", 0xB8: ",", 0xB9: "×", 0xBA: "/",
}

# Populate A-Z (0xBB - 0xD4)
for i in range(26):
    CHAR_TABLE[0xBB + i] = chr(ord("A") + i)

# Populate a-z (0xD5 - 0xEE)
for i in range(26):
    CHAR_TABLE[0xD5 + i] = chr(ord("a") + i)

REVERSE_CHAR_TABLE = {v: k for k, v in CHAR_TABLE.items()}


def decode_gen3_string(data: bytes) -> str:
    """Decodes a Gen 3 byte sequence into a Python UTF-8 string."""
    chars = []
    for b in data:
        if b == 0xFF:  # String terminator
            break
        chars.append(CHAR_TABLE.get(b, "?"))
    return "".join(chars).strip()


def encode_gen3_string(text: str, max_len: int) -> bytes:
    """Encodes a Python string into a Gen 3 byte sequence padded with 0xFF."""
    out = bytearray()
    for ch in text[:max_len]:
        out.append(REVERSE_CHAR_TABLE.get(ch, 0x00))
    while len(out) < max_len:
        out.append(0xFF)
    return bytes(out[:max_len])


# Gen 1 Species Names (1 to 151)
SPECIES_NAMES = {
    0: "None",
    1: "Bulbasaur", 2: "Ivysaur", 3: "Venusaur", 4: "Charmander", 5: "Charmeleon", 6: "Charizard",
    7: "Squirtle", 8: "Wartortle", 9: "Blastoise", 10: "Caterpie", 11: "Metapod", 12: "Butterfree",
    13: "Weedle", 14: "Kakuna", 15: "Beedrill", 16: "Pidgey", 17: "Pidgeotto", 18: "Pidgeot",
    19: "Rattata", 20: "Raticate", 21: "Spearow", 22: "Fearow", 23: "Ekans", 24: "Arbok",
    25: "Pikachu", 26: "Raichu", 27: "Sandshrew", 28: "Sandslash", 29: "Nidoran♀", 30: "Nidorina",
    31: "Nidoqueen", 32: "Nidoran♂", 33: "Nidorino", 34: "Nidoking", 35: "Clefairy", 36: "Clefable",
    37: "Vulpix", 38: "Ninetales", 39: "Jigglypuff", 40: "Wigglytuff", 41: "Zubat", 42: "Golbat",
    43: "Oddish", 44: "Gloom", 45: "Vileplume", 46: "Paras", 47: "Parasect", 48: "Venonat",
    49: "Venomoth", 50: "Diglett", 51: "Dugtrio", 52: "Meowth", 53: "Persian", 54: "Psyduck",
    55: "Golduck", 56: "Mankey", 57: "Primeape", 58: "Growlithe", 59: "Arcanine", 60: "Poliwag",
    61: "Poliwhirl", 62: "Poliwrath", 63: "Abra", 64: "Kadabra", 65: "Alakazam", 66: "Machop",
    67: "Machoke", 68: "Machamp", 69: "Bellsprout", 70: "Weepinbell", 71: "Victreebel", 72: "Tentacool",
    73: "Tentacruel", 74: "Geodude", 75: "Graveler", 76: "Golem", 77: "Ponyta", 78: "Rapidash",
    79: "Slowpoke", 80: "Slowbro", 81: "Magnemite", 82: "Magneton", 83: "Farfetch'd", 84: "Doduo",
    85: "Dodrio", 86: "Seel", 87: "Dewgong", 88: "Grimer", 89: "Muk", 90: "Shellder",
    91: "Cloyster", 92: "Gastly", 93: "Haunter", 94: "Gengar", 95: "Onix", 96: "Drowzee",
    97: "Hypno", 98: "Krabby", 99: "Kingler", 100: "Voltorb", 101: "Electrode", 102: "Exeggcute",
    103: "Exeggutor", 104: "Cubone", 105: "Marowak", 106: "Hitmonlee", 107: "Hitmonchan", 108: "Lickitung",
    109: "Koffing", 110: "Weezing", 111: "Rhyhorn", 112: "Rhydon", 113: "Chansey", 114: "Tangela",
    115: "Kangaskhan", 116: "Horsea", 117: "Seadra", 118: "Goldeen", 119: "Seaking", 120: "Staryu",
    121: "Starmie", 122: "Mr. Mime", 123: "Scyther", 124: "Jynx", 125: "Electabuzz", 126: "Magmar",
    127: "Pinsir", 128: "Tauros", 129: "Magikarp", 130: "Gyarados", 131: "Lapras", 132: "Ditto",
    133: "Eevee", 134: "Vaporeon", 135: "Jolteon", 136: "Flareon", 137: "Porygon", 138: "Omanyte",
    139: "Omastar", 140: "Kabuto", 141: "Kabutops", 142: "Aerodactyl", 143: "Snorlax", 144: "Articuno",
    145: "Zapdos", 146: "Moltres", 147: "Dratini", 148: "Dragonair", 149: "Dragonite", 150: "Mewtwo",
    151: "Mew",
}


@dataclass
class Pokemon:
    # Unencrypted Header
    pid: int = 0
    otid: int = 0
    nickname: str = ""
    language: int = 0
    ot_name: str = ""
    markings: int = 0
    checksum: int = 0

    # Growth Substruct
    species: int = 0
    species_name: str = "Unknown"
    held_item: int = 0
    experience: int = 0
    pp_bonuses: int = 0
    friendship: int = 0

    # Attacks Substruct
    moves: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    pp: List[int] = field(default_factory=lambda: [0, 0, 0, 0])

    # EVs Substruct
    hp_ev: int = 0
    atk_ev: int = 0
    def_ev: int = 0
    spd_ev: int = 0
    spatk_ev: int = 0
    spdef_ev: int = 0

    # Misc Substruct (IVs)
    hp_iv: int = 0
    atk_iv: int = 0
    def_iv: int = 0
    spd_iv: int = 0
    spatk_iv: int = 0
    spdef_iv: int = 0
    is_egg: bool = False
    ability_bit: int = 0

    # Battle Status (only present in 100-byte party data)
    status: int = 0
    level: int = 0
    current_hp: int = 0
    max_hp: int = 0
    attack: int = 0
    defense: int = 0
    speed: int = 0
    sp_attack: int = 0
    sp_defense: int = 0

    # Raw 100-byte payload cache
    raw_data: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "Pokemon":
        if len(data) < PARTY_SLOT_SIZE:
            raise ValueError(f"Expected at least {PARTY_SLOT_SIZE} bytes, got {len(data)}")

        p = cls()
        p.raw_data = data[:PARTY_SLOT_SIZE]

        # 1. Unpack Header (0x00 - 0x1F)
        p.pid, p.otid = struct.unpack("<II", data[0:8])
        if p.pid == 0 and p.otid == 0:
            return p  # Empty slot

        p.nickname = decode_gen3_string(data[8:18])
        p.language = struct.unpack("<H", data[18:20])[0]
        p.ot_name = decode_gen3_string(data[20:27])
        p.markings = data[27]
        p.checksum = struct.unpack("<H", data[28:30])[0]

        # 2. Decrypt Substructs (0x20 - 0x4F, 48 bytes)
        raw_substructs = data[32:80]
        growth, attacks, evs, misc = decrypt_substructs(raw_substructs, p.pid, p.otid)

        # Growth (12 bytes: u16 species, u16 item, u32 exp, u8 pp_bonus, u8 friendship, 2x pad)
        p.species, p.held_item, p.experience, p.pp_bonuses, p.friendship = struct.unpack(
            "<HHI2B2x", growth
        )
        p.species_name = SPECIES_NAMES.get(p.species, f"Species #{p.species}")

        # Attacks
        p.moves = list(struct.unpack("<HHHH", attacks[0:8]))
        p.pp = list(struct.unpack("<BBBB", attacks[8:12]))

        # EVs
        p.hp_ev, p.atk_ev, p.def_ev, p.spd_ev, p.spatk_ev, p.spdef_ev = struct.unpack(
            "<BBBBBB", evs[0:6]
        )

        # Misc (IVs)
        iv_data = struct.unpack("<I", misc[4:8])[0]
        p.hp_iv = iv_data & 0x1F
        p.atk_iv = (iv_data >> 5) & 0x1F
        p.def_iv = (iv_data >> 10) & 0x1F
        p.spd_iv = (iv_data >> 15) & 0x1F
        p.spatk_iv = (iv_data >> 20) & 0x1F
        p.spdef_iv = (iv_data >> 25) & 0x1F
        p.is_egg = bool((iv_data >> 30) & 1)
        p.ability_bit = (iv_data >> 31) & 1

        # 3. Battle Status (0x50 - 0x63, 20 bytes: u32 status, u8 level, u8 mail, 7*u16 stats)
        (
            p.status,
            p.level,
            _,  # mail id
            p.current_hp,
            p.max_hp,
            p.attack,
            p.defense,
            p.speed,
            p.sp_attack,
            p.sp_defense,
        ) = struct.unpack("<IBB7H", data[80:100])

        return p

    def is_valid(self) -> bool:
        return self.pid != 0 or self.otid != 0
