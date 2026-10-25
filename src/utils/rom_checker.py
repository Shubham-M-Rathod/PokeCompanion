"""Utility to check and validate Pokémon GBA ROM files."""
import os
import sys

KNOWN_ROMS = {
    "BPRE": {
        "title": "POKEMON FIRE",
        "name": "Pokémon FireRed (US)",
        "versions": {
            0x00: "v1.0 (Supported - Primary Target)",
            0x01: "v1.1 (Warning: Checksum/offsets may differ from v1.0)",
        },
    },
    "BPEE": {
        "title": "POKEMON EMER",
        "name": "Pokémon Emerald (US)",
        "versions": {
            0x00: "v1.0 (Supported)",
        },
    },
}


def inspect_rom(filepath: str) -> dict:
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    with open(filepath, "rb") as f:
        # Read header: 0x00 to 0xC0
        header = f.read(0xC0)

    if len(header) < 0xC0:
        return {"error": "File too small to be a valid GBA ROM."}

    # Header layout:
    # 0xA0 - 0xAB: Game Title (12 chars ASCII, padded with null/space)
    # 0xAC - 0xAF: Game Code (4 chars ASCII)
    # 0xB0 - 0xB1: Maker Code (2 chars ASCII)
    # 0xB2: Fixed value 0x96
    # 0xBC: Software Version (1 byte)
    game_title = header[0xA0:0xAC].decode("ascii", errors="replace").strip("\x00")
    game_code = header[0xAC:0xB0].decode("ascii", errors="replace")
    maker_code = header[0xB0:0xB2].decode("ascii", errors="replace")
    version = header[0xBC]

    known_info = KNOWN_ROMS.get(game_code)
    supported = False
    status_msg = "Unknown ROM"

    if known_info:
        ver_desc = known_info["versions"].get(version, f"v{version} (Untested)")
        status_msg = f"{known_info['name']} - {ver_desc}"
        if game_code == "BPRE" and version == 0x00:
            supported = True
        elif game_code == "BPEE" and version == 0x00:
            supported = True
    else:
        status_msg = f"Unknown game code '{game_code}'. Expected BPRE or BPEE."

    return {
        "filepath": filepath,
        "game_title": game_title,
        "game_code": game_code,
        "maker_code": maker_code,
        "version_byte": version,
        "status": status_msg,
        "supported": supported,
    }


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "roms"
    if os.path.isdir(target_dir):
        files = [
            os.path.join(target_dir, f)
            for f in os.listdir(target_dir)
            if f.lower().endswith(".gba")
        ]
        if not files:
            print(f"No .gba files found in '{target_dir}'. Drop your ROMs in '{target_dir}' and run again.")
        for f in files:
            res = inspect_rom(f)
            print(f"File: {os.path.basename(f)}")
            print(f"  Title: {res.get('game_title')}")
            print(f"  Code:  {res.get('game_code')}")
            print(f"  Ver:   0x{res.get('version_byte', 0):02X}")
            print(f"  Match: {res.get('status')}")
            print(f"  Supported: {res.get('supported')}\n")
    elif os.path.isfile(target_dir):
        res = inspect_rom(target_dir)
        print(res)
    else:
        print(f"Target '{target_dir}' does not exist.")

