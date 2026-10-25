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
from src.core.crypto import decrypt_substructs, calculate_checksum
from src.memory.gdb_client import GDBClient


async def run_spike_test(host: str = DEFAULT_GDB_HOST, port: int = DEFAULT_GDB_PORT):
    client = GDBClient(host=host, port=port, timeout=3.0)

    print(f"Connecting to mGBA GDB server at {host}:{port}...")
    if not await client.connect():
        print(f"[FAIL] Could not connect to {host}:{port}.")
        print("Please ensure mGBA is running and GDB Server is started (Tools -> Start GDB Server...).")
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
        
        # Parse slot header (PID at 0x00, OTID at 0x04)
        import struct
        pid, otid = struct.unpack("<II", party_data[:8])
        stored_csum = struct.unpack("<H", party_data[28:30])[0]

        print(f"      PID: 0x{pid:08X} | OTID: 0x{otid:08X} | Stored Checksum: 0x{stored_csum:04X}")

        if pid == 0 and otid == 0:
            print("      [NOTE] Slot 1 is currently empty or game is still at the title screen.")
        else:
            # Step 3: Decrypt substructs and verify checksum
            print("[3/3] Decrypting 48-byte substructs & verifying checksum...")
            raw_substructs = party_data[32:80]
            g, a, e, m = decrypt_substructs(raw_substructs, pid, otid)
            
            # Checksum is calculated over canonical 48 bytes (G+A+E+M ordered according to PID % 24)
            # Reconstruct the ordered 48 bytes decrypted buffer to test checksum:
            from src.core.constants import SUBSTRUCT_ORDER
            order = SUBSTRUCT_ORDER[pid % 24]
            canonical = [g, a, e, m]
            ordered_decrypted = bytearray(48)
            for pos, blk_idx in enumerate(order):
                ordered_decrypted[pos * 12 : (pos + 1) * 12] = canonical[blk_idx]

            calc_csum = calculate_checksum(bytes(ordered_decrypted))
            if calc_csum == stored_csum:
                print(f"      [SUCCESS] Checksum verified: 0x{calc_csum:04X} == 0x{stored_csum:04X}!")
            else:
                print(f"      [WARNING] Checksum mismatch: calculated 0x{calc_csum:04X} vs stored 0x{stored_csum:04X}")

        print("\n[SUCCESS] Spike test completed successfully! Memory connection is working.")
        return True

    finally:
        await client.disconnect()


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GDB_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_GDB_PORT
    success = asyncio.run(run_spike_test(host, port))
    sys.exit(0 if success else 1)
