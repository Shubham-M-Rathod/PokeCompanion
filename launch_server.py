"""Starts the Central Relay Server."""

import socket
import uvicorn


def unfreeze_mgba(host: str = "127.0.0.1", port: int = 2345) -> bool:
    """Checks if mGBA GDB server is waiting in halted state on port 2345 and unfreezes it ($c).
    
    Uses identical framing and acknowledgment handshaking as test_resume.py.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((host, port))

        # 1. Query halt state with full GDB framing
        s.sendall(b"$?#3f")
        ack = s.recv(1)  # Read '+' ACK

        # Read the stop reply packet until '#' + 2 checksum bytes
        started = False
        while True:
            c = s.recv(1)
            if not c:
                break
            if c == b"$":
                started = True
                continue
            if started and c == b"#":
                s.recv(2)  # Read 2-byte checksum
                s.sendall(b"+")  # ACK stop reply to mGBA
                break

        # 2. Send continue command to unfreeze execution
        s.sendall(b"$c#63")
        try:
            s.recv(1)  # Read '+' ACK from mGBA
        except Exception:
            pass
        s.close()
        print(f"[mGBA] Successfully connected to GDB on {host}:{port} and resumed game execution ($c)!")
        return True
    except Exception as e:
        print(f"[mGBA] Note: Could not unfreeze on {host}:{port} ({e}). (Normal if GDB server is not active).")
        return False


if __name__ == "__main__":
    print("Checking mGBA GDB status on 127.0.0.1:2345...")
    unfreeze_mgba()
    print("Starting PokeCompanion NetBridge Relay Server on http://127.0.0.1:8000...")
    uvicorn.run("src.server.server:app", host="127.0.0.1", port=8000, reload=False)
