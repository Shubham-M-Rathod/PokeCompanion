"""Live Spike Test: Verifies connection to mGBA GDB Server and reads live game memory.

Usage:
1. Open mGBA and load FireRed (USA v1.0).
2. Go to Tools -> Start GDB Server... (port 2345).
3. Run: python test_live_connection.py
"""

import asyncio
import sys
from src.core.constants import (
    DEFAULT_GDB_HOST,
    DEFAULT_GDB_PORT,
    GAME_CODE_FIRERED,
    GAME_CODE_EMERALD,
    FireRedOffsets,
    EmeraldOffsets,
)
from src.core.pokemon import Pokemon
from src.memory.gdb_client import GDBClient


async def run_spike_test(host: str = DEFAULT_GDB_HOST, port: int = DEFAULT_GDB_PORT):
    client = GDBClient(host=host, port=port, timeout=3.0)

    print(f"Connecting to mGBA GDB server at {host}:{port}...")
    if not await client.connect():
        print(f"\n[FAIL] Could not connect to {host}:{port}.")
        print("Please ensure:")
        print("  1. mGBA is running and Pokémon FireRed is loaded.")
        print("  2. In mGBA, click 'Tools' -> 'Start GDB server...' and press OK (port 2345).")
        return False

    try:
        # Step 1: Read ROM game code at 0x080000AC
        print("[1/3] Reading ROM Game Code at 0x080000AC...")
        game_code_bytes = await client.read_memory(FireRedOffsets.ROM_GAME_CODE, 4)
        game_code_str = game_code_bytes.decode("ascii", errors="replace")
        print(f"      Detected ROM Game Code: {game_code_str}")

        if game_code_bytes == GAME_CODE_FIRERED:
            print("      Game: Pokémon FireRed (US v1.0) - MATCHED PRIMARY TARGET")
            party_addr = FireRedOffsets.PLAYER_PARTY
        elif game_code_bytes == GAME_CODE_EMERALD:
            print("      Game: Pokémon Emerald (US) - MATCHED SECONDARY TARGET")
            party_addr = EmeraldOffsets.PLAYER_PARTY
        else:
            print(f"      [WARNING] Unrecognized Game Code: {game_code_str}. Expected BPRE or BPEE.")
            party_addr = FireRedOffsets.PLAYER_PARTY

        # Step 2: Read first party slot (100 bytes)
        print(f"[2/3] Reading 100 bytes of Party Slot 1 from 0x{party_addr:08X}...")
        party_data = await client.read_memory(party_addr, 100)
        mon = Pokemon.from_bytes(party_data)

        if not mon.is_valid():
            print("      [NOTE] Slot 1 is empty or the game has not loaded a save file / starter yet.")
        else:
            # Step 3: Print parsed details
            print("[3/3] Successfully decrypted and parsed Party Slot 1:")
            print(f"      • Species:    {mon.species_name} (ID: {mon.species})")
            print(f"      • Nickname:   {mon.nickname}")
            print(f"      • Level:      {mon.level} | HP: {mon.current_hp}/{mon.max_hp}")
            print(f"      • PID/OTID:   PID=0x{mon.pid:08X} | OTID=0x{mon.otid:08X}")
            print(f"      • IVs:        HP:{mon.hp_iv} Atk:{mon.atk_iv} Def:{mon.def_iv} Spd:{mon.spd_iv} SpA:{mon.spatk_iv} SpD:{mon.spdef_iv}")
            print(f"      • EVs:        HP:{mon.hp_ev} Atk:{mon.atk_ev} Def:{mon.def_ev} Spd:{mon.spd_ev} SpA:{mon.spatk_ev} SpD:{mon.spdef_ev}")
            print(f"      • Moves:      {mon.moves} | PP: {mon.pp}")
            print(f"      • Checksum:   0x{mon.checksum:04X} (Valid)")

        print("\n[SUCCESS] Memory engine connected and operating properly!")
        return True

    finally:
        await client.disconnect()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GDB_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_GDB_PORT
    success = asyncio.run(run_spike_test(host, port))
    sys.exit(0 if success else 1)
