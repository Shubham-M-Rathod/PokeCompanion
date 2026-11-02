"""Diagnostic script to test reading each 100-byte party slot individually."""

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
        print(f"    [DEBUG] Read at 0x{addr:08X} len {length} returned: '{hex_str[:30]}...'")
        return b""
    return bytes.fromhex(hex_str)

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect(("127.0.0.1", 2345))
    except Exception as e:
        print(f"Could not connect: {e}")
        return

    # Handshake
    send_cmd(s, "?")

    print("================== PARTY SLOTS (READ 100 BYTES AT A TIME) ==================")
    cnt_bytes = read_bytes(s, 0x02024029, 1)
    party_count = cnt_bytes[0] if cnt_bytes else 0
    print(f"Party Count: {party_count}")

    # Read each 100-byte slot individually so we never exceed mGBA's packet buffer limit
    for i in range(party_count):
        slot_addr = 0x02024284 + (i * 100)
        slot_data = read_bytes(s, slot_addr, 100)
        if len(slot_data) < 100:
            print(f"[Slot {i+1}] Error: read returned {len(slot_data)} bytes")
            continue

        pid, otid = struct.unpack("<II", slot_data[0:8])
        raw_nick = slot_data[8:18]
        nick = decode_gen3_string(raw_nick)
        stored_csum = struct.unpack("<H", slot_data[28:30])[0]

        raw_sub = slot_data[32:80]
        g, a, e, m = decrypt_substructs(raw_sub, pid, otid)
        calc_csum = calculate_checksum(g + a + e + m)

        species_id = struct.unpack("<H", g[0:2])[0]
        level = slot_data[84]
        hp = struct.unpack("<H", slot_data[86:88])[0]
        max_hp = struct.unpack("<H", slot_data[88:90])[0]
        moves = list(struct.unpack("<HHHH", a[0:8]))

        from src.core.pokemon import SPECIES_NAMES
        species_name = SPECIES_NAMES.get(species_id, f"Species #{species_id}")

        print(f"\n[Slot {i+1}] {nick} ({species_name})")
        print(f"  Level: {level} | HP: {hp}/{max_hp}")
        print(f"  PID: 0x{pid:08X} | OTID: 0x{otid:08X}")
        print(f"  Moves: {moves}")
        print(f"  Checksum: 0x{calc_csum:04X} (Valid: {calc_csum == stored_csum})")

    # Read Bag Items (30 slots, chunk in 10 slots = 40 bytes each)
    sb2_ptr = read_bytes(s, 0x0300500C, 4)
    sb2_addr = struct.unpack("<I", sb2_ptr)[0] if sb2_ptr else 0
    sec_key_bytes = read_bytes(s, sb2_addr + 0x0F20, 4) if sb2_addr else b""
    sec_key = struct.unpack("<I", sec_key_bytes)[0] if sec_key_bytes else 0

    sb1_ptr = read_bytes(s, 0x03005008, 4)
    sb1_addr = struct.unpack("<I", sb1_ptr)[0] if sb1_ptr else 0

    print(f"\n================== IN-GAME BAG (Key: 0x{sec_key:08X}) ==================")
    if sb1_addr:
        xor_mask = sec_key & 0xFFFF
        found_any = False
        for chunk_idx in range(3): # 3 chunks of 10 items (40 bytes each)
            bag_chunk_addr = sb1_addr + 0x0310 + (chunk_idx * 40)
            raw_chunk = read_bytes(s, bag_chunk_addr, 40)
            for i in range(10):
                sub = raw_chunk[i * 4 : (i + 1) * 4]
                if len(sub) < 4:
                    break
                iid, raw_q = struct.unpack("<HH", sub)
                if iid != 0:
                    qty = raw_q ^ xor_mask
                    print(f"  • {get_item_name(iid)} (ID: 0x{iid:04X}) x{qty}")
                    found_any = True
        if not found_any:
            print("  (Bag Items Pocket is empty)")

    # Resume game
    print("\nResuming game execution ($c)...")
    s.sendall(b"$c#63")
    try:
        s.recv(1)
    except Exception:
        pass
    s.close()
    print("Done! Game is running.")

if __name__ == "__main__":
    main()
