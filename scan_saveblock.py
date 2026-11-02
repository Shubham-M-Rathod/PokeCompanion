"""Memory scanner to locate the exact Badge flags in SaveBlock1 for FireRed."""

import socket
import struct

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
        if not c: break
        if c == b"$": started = True; continue
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
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    send_cmd(s, "?")

    # Read SaveBlock1 Pointer (0x03005008 in FireRed)
    sb1_ptr_bytes = read_bytes(s, 0x03005008, 4)
    sb1_addr = struct.unpack("<I", sb1_ptr_bytes)[0]
    print(f"SaveBlock1 Address: 0x{sb1_addr:08X}")

    # Read the flags region in SaveBlock1 (0x0C00 to 0x1600)
    start_off = 0x0C00
    end_off = 0x1600
    chunk_size = 64

    found = []
    for off in range(start_off, end_off, chunk_size):
        chunk = read_bytes(s, sb1_addr + off, chunk_size)
        if not chunk:
            break
        for i, val in enumerate(chunk):
            if val != 0:
                rel_off = off + i
                found.append((rel_off, val))

    print(f"\nNon-zero bytes in flags region (0x0C00 - 0x1600):")
    for rel_off, val in found:
        bits = bin(val)[2:].zfill(8)
        print(f"  SB1 + 0x{rel_off:04X} (0x{sb1_addr + rel_off:08X}): 0x{val:02X} (Bits: {bits})")

    # Resume game
    s.sendall(b"$c#63")
    try: s.recv(1)
    except: pass
    s.close()
    print("\nResumed game.")

if __name__ == "__main__":
    main()
