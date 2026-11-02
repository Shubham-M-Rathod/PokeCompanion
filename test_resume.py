"""Diagnostic tool to inspect live RAM layout directly from mGBA."""

import socket
import struct
from src.core.pokemon import decode_gen3_string
from src.core.crypto import decrypt_substructs, calculate_checksum
from src.core.items import get_item_name

def compute_csum(cmd: str) -> str:
    return f"{sum(ord(c) for c in cmd) % 256:02x}"

def send_cmd(s: socket.socket, cmd: str) -> str:
    pkt = f"${cmd}#{compute_csum(cmd)}".encode("ascii")
    s.sendall(pkt)
    ack = s.recv(1)
    resp = bytearray()
    started = False
    while True:
        c = s.recv(1)
        if not c:
            break
        if c == b"$":
            started = True
            continue
        if started:
            if c == b"#":
                s.recv(2)
                s.sendall(b"+")
                break
            resp.extend(c)
    return resp.decode("ascii", errors="replace")

def read_bytes(s: socket.socket, addr: int, length: int) -> bytes:
    hex_str = send_cmd(s, f"m{addr:x},{length:x}")
    if hex_str.startswith("E") or len(hex_str) != length * 2:
        return b""
    return bytes.fromhex(hex_str)

def main():
    host = "127.0.0.1"
    port = 2345
    print(f"Connecting to mGBA on {host}:{port}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((host, port))
    except Exception as e:
        print(f"[ERROR] Could not connect: {e}")
        print("Please start GDB server in mGBA (Tools -> Start GDB Server).")
        return

    # Handshake
    halt_state = send_cmd(s, "?")
    print(f"Connected! (mGBA State: {halt_state})")

    # 1. ROM Code
    rom_bytes = read_bytes(s, 0x080000AC, 4)
    print(f"\n[1] ROM Code: '{rom_bytes.decode('ascii', errors='replace')}'")

    # 2. Party Count candidates
    cnt_24029 = read_bytes(s, 0x02024029, 1)
    party_count = cnt_24029[0] if cnt_24029 else 0
    print(f"[2] Party Count at 0x02024029: {party_count}")

    # 3. Party Slot 1 (100 bytes at 0x02024284)
    slot1_bytes = read_bytes(s, 0x02024284, 100)
    print(f"\n[3] Party Slot 1 (0x02024284):")
    if slot1_bytes:
        pid, otid = struct.unpack("<II", slot1_bytes[0:8])
        raw_nick = slot1_bytes[8:18]
        nick = decode_gen3_string(raw_nick)
        stored_csum = struct.unpack("<H", slot1_bytes[28:30])[0]

        print(f"    PID: 0x{pid:08X} | OTID: 0x{otid:08X}")
        print(f"    Nickname: '{nick}' (Raw hex: {raw_nick.hex()})")
        print(f"    Stored Checksum: 0x{stored_csum:04X}")

        if pid != 0 or otid != 0:
            raw_substructs = slot1_bytes[32:80]
            g, a, e, m = decrypt_substructs(raw_substructs, pid, otid)
            csum = calculate_checksum(g + a + e + m)
            species = struct.unpack("<H", g[0:2])[0]
            level = slot1_bytes[84]
            hp = struct.unpack("<H", slot1_bytes[86:88])[0]
            max_hp = struct.unpack("<H", slot1_bytes[88:90])[0]
            print(f"    Species ID: {species} | Level: {level} | HP: {hp}/{max_hp}")
            print(f"    Calculated Checksum: 0x{csum:04X} (Matches: {csum == stored_csum})")
    else:
        print("    Failed to read slot 1")

    # 4. SaveBlock2 Pointer (0x0300500C)
    sb2_ptr_bytes = read_bytes(s, 0x0300500C, 4)
    sb2_addr = struct.unpack("<I", sb2_ptr_bytes)[0] if sb2_ptr_bytes else 0
    print(f"\n[4] SaveBlock2 (Pointer at 0x0300500C): 0x{sb2_addr:08X}")
    sec_key = 0
    if 0x02000000 <= sb2_addr <= 0x0203FFFF:
        trainer_bytes = read_bytes(s, sb2_addr, 16)
        trainer_name = decode_gen3_string(trainer_bytes[0:7])
        tid, sid = struct.unpack("<HH", trainer_bytes[10:14])
        print(f"    Trainer Name: '{trainer_name}' | TID: {tid} | SID: {sid}")

        key_bytes = read_bytes(s, sb2_addr + 0x0F20, 4)
        sec_key = struct.unpack("<I", key_bytes)[0] if key_bytes else 0
        print(f"    Security Key (at SB2+0x0F20): 0x{sec_key:08X}")

    # 5. SaveBlock1 Pointer (0x03005008)
    sb1_ptr_bytes = read_bytes(s, 0x03005008, 4)
    sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0] if sb1_ptr_bytes else 0
    print(f"\n[5] SaveBlock1 (Pointer at 0x03005008): 0x{sb1_addr:08X}")
    if 0x02000000 <= sb1_addr <= 0x0203FFFF:
        badge_b = read_bytes(s, sb1_addr + 0x0FE4, 1)
        print(f"    Badges at SB1+0x0FE4: 0x{badge_b[0]:02X}" if badge_b else "    Badge read failed")

        bag_bytes_310 = read_bytes(s, sb1_addr + 0x0310, 40)
        print(f"    Raw Bag at SB1+0x0310 (40 bytes):\n      {bag_bytes_310.hex()}")

        # Print parsed items at 0x0310
        print(f"    Parsed items at 0x0310:")
        for i in range(10):
            chunk = bag_bytes_310[i * 4 : (i + 1) * 4]
            if len(chunk) < 4:
                break
            iid, raw_q = struct.unpack("<HH", chunk)
            if iid != 0:
                xor_q = raw_q ^ (sec_key & 0xFFFF)
                print(f"      Slot {i+1}: Item 0x{iid:04X} ({get_item_name(iid)}) | RawQty={raw_q} | XORQty={xor_q}")

    # 6. Resume Game Execution
    print("\nResuming game execution ($c)...")
    s.sendall(b"$c#63")
    try:
        s.recv(1)
    except Exception:
        pass
    s.close()
    print("Done! Game is now running.")

if __name__ == "__main__":
    main()
