"""Starts the PokeCompanion Desktop UI Companion."""

import argparse
import socket
from src.client.ui.app import main


def unfreeze_mgba(host: str = "127.0.0.1", port: int = 2345) -> None:
    """Pre-unfreezes mGBA before starting Qt application event loop."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((host, port))

        # Query halt state and ACK
        s.sendall(b"$?#3f")
        ack = s.recv(1)

        started = False
        while True:
            c = s.recv(1)
            if not c:
                break
            if c == b"$":
                started = True
                continue
            if started and c == b"#":
                s.recv(2)
                s.sendall(b"+")
                break

        # Resume game execution
        s.sendall(b"$c#63")
        try:
            s.recv(1)
        except Exception:
            pass
        s.close()
        print(f"[mGBA] Unfroze mGBA on {host}:{port} ($c)!")
    except Exception as e:
        print(f"[mGBA] Note: Could not connect to GDB on {host}:{port} ({e}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PokeCompanion NetBridge Companion Client")
    parser.add_argument("--gdb-host", default="127.0.0.1", help="mGBA GDB host (default: 127.0.0.1)")
    parser.add_argument("--gdb-port", type=int, default=2345, help="mGBA GDB port (default: 2345)")
    parser.add_argument("--server-url", default="ws://127.0.0.1:8000", help="Relay server WebSocket URL")
    parser.add_argument("--player-id", default=None, help="Optional player ID label (e.g., p1, p2)")
    args = parser.parse_args()

    unfreeze_mgba(args.gdb_host, args.gdb_port)
    main(
        gdb_host=args.gdb_host,
        gdb_port=args.gdb_port,
        server_url=args.server_url,
        player_id=args.player_id,
    )
