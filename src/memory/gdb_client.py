"""GDB Remote Protocol Client for mGBA.

Interacts directly with mGBA's built-in GDB stub over TCP (default port 2345)
to read and write memory without modifying ROMs or using emulator plugins.
Provides non-blocking execution management to keep the emulator running at 60 FPS.
"""

import asyncio
import contextlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_checksum(data: str) -> str:
    """Computes the GDB 2-hex-digit checksum: sum(data) % 256."""
    csum = sum(ord(c) for c in data) % 256
    return f"{csum:02x}"


def format_packet(data: str) -> bytes:
    """Encapsulates string data into standard GDB packet format: $data#checksum."""
    csum = compute_checksum(data)
    return f"${data}#{csum}".encode("ascii")


def parse_memory_response(resp: str, expected_len: int) -> bytes:
    """Parses a hex-encoded memory read response from GDB into raw bytes."""
    if resp.startswith("E"):
        raise RuntimeError(f"GDB memory read returned error: {resp}")
    if len(resp) != expected_len * 2:
        raise ValueError(f"Expected {expected_len * 2} hex characters, got {len(resp)}: {resp}")
    return bytes.fromhex(resp)


def parse_write_response(resp: str) -> bool:
    """Validates that a write command returned OK."""
    return resp == "OK"


class GDBClient:
    """Asynchronous client for mGBA's GDB Remote Serial Protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 2345, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock: Optional[asyncio.Lock] = None
        self.target_is_running: bool = False

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def is_connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self) -> bool:
        """Establishes connection with mGBA GDB server and resumes execution."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            logger.info("Connected to mGBA GDB server at %s:%d", self.host, self.port)
            # mGBA halts execution upon initial GDB connection.
            # We immediately resume execution so the game doesn't freeze!
            await self._raw_continue()
            return True
        except Exception as e:
            logger.warning("Could not connect to mGBA GDB server at %s:%d: %s", self.host, self.port, e)
            self.reader = None
            self.writer = None
            self.target_is_running = False
            return False

    async def disconnect(self) -> None:
        """Closes the GDB connection cleanly."""
        if self.writer:
            try:
                # Resume target before disconnecting so game keeps playing
                if not self.target_is_running:
                    await self._raw_continue()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            finally:
                self.reader = None
                self.writer = None
                self.target_is_running = False
                logger.info("Disconnected from GDB server.")

    async def _raw_interrupt(self) -> None:
        """Sends Ctrl+C (\x03) to briefly halt mGBA so memory can be safely inspected."""
        if not self.writer or not self.reader:
            return
        self.writer.write(b"\x03")
        await self.writer.drain()
        # Read until stop packet is received (e.g. $T05...#xx or $S05#xx)
        try:
            started = False
            while True:
                char = await asyncio.wait_for(self.reader.read(1), timeout=0.4)
                if not char:
                    break
                if char == b"$":
                    started = True
                    continue
                if started and char == b"#":
                    # Read 2-byte checksum
                    await asyncio.wait_for(self.reader.read(2), timeout=0.4)
                    self.writer.write(b"+")
                    await self.writer.drain()
                    break
        except Exception:
            pass
        self.target_is_running = False

    async def _raw_continue(self) -> None:
        """Sends continue command ($c#63) so mGBA runs at full 60 FPS."""
        if not self.writer or not self.reader:
            return
        self.writer.write(b"$c#63")
        await self.writer.drain()
        try:
            ack = await asyncio.wait_for(self.reader.read(1), timeout=0.2)
        except Exception:
            pass
        self.target_is_running = True

    @contextlib.asynccontextmanager
    async def transaction(self):
        """Context manager: halts mGBA for a few milliseconds, performs reads/writes, and resumes."""
        async with self._get_lock():
            if self.target_is_running:
                await self._raw_interrupt()
            try:
                yield
            finally:
                if self.is_connected:
                    await self._raw_continue()

    async def _send_raw_packet(self, payload: str) -> str:
        """Sends a packet and waits for ACK (+) and response packet.
        
        Must be called with lock held.
        """
        if not self.writer or not self.reader:
            raise ConnectionError("GDB client is not connected.")

        packet = format_packet(payload)
        self.writer.write(packet)
        await self.writer.drain()

        # Wait for ACK '+'
        ack = await asyncio.wait_for(self.reader.read(1), timeout=self.timeout)
        if ack != b"+":
            logger.debug("Received unexpected ACK character: %r", ack)

        # Read packet payload: starts with '$', ends with '#<csum>'
        raw_resp = bytearray()
        started = False
        while True:
            char = await asyncio.wait_for(self.reader.read(1), timeout=self.timeout)
            if not char:
                raise ConnectionResetError("Connection closed while waiting for GDB packet.")
            if char == b"$":
                started = True
                continue
            if started:
                if char == b"#":
                    # Read 2-byte checksum
                    await asyncio.wait_for(self.reader.read(2), timeout=self.timeout)
                    # Send ACK back to server
                    self.writer.write(b"+")
                    await self.writer.drain()
                    break
                raw_resp.extend(char)

        return raw_resp.decode("ascii", errors="replace")

    async def read_memory(self, address: int, length: int) -> bytes:
        """Reads `length` bytes from target memory at `address`."""
        cmd = f"m{address:x},{length:x}"
        resp = await self._send_raw_packet(cmd)
        return parse_memory_response(resp, length)

    async def write_memory(self, address: int, data: bytes) -> bool:
        """Writes `data` bytes to target memory at `address`."""
        hex_data = data.hex()
        cmd = f"M{address:x},{len(data):x}:{hex_data}"
        resp = await self._send_raw_packet(cmd)
        return parse_write_response(resp)
