"""Starts the PokeCompanion Desktop UI Companion."""

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
    except Exception:
        pass


if __name__ == "__main__":
    unfreeze_mgba()
    main()
