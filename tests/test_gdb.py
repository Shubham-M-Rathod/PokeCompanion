"""Unit tests for GDB client protocol framing and packet parsing."""

import pytest
from src.memory.gdb_client import (
    compute_checksum,
    format_packet,
    parse_memory_response,
    parse_write_response,
)


def test_packet_checksum():
    # Test mGBA read command checksum: 'm2024284,64'
    csum = compute_checksum("m2024284,64")
    assert len(csum) == 2
    expected = f"{sum(ord(c) for c in 'm2024284,64') % 256:02x}"
    assert csum == expected


def test_format_packet():
    pkt = format_packet("OK")
    assert pkt == b"$OK#9a"

    pkt_read = format_packet("m080000ac,4")
    assert pkt_read.startswith(b"$m080000ac,4#")


def test_parse_memory_response():
    # Successful memory parse: "42505245" -> ASCII "BPRE"
    hex_str = "42505245"
    data = parse_memory_response(hex_str, 4)
    assert data == b"BPRE"

    # Hex length mismatch raises ValueError
    with pytest.raises(ValueError, match="Expected 8 hex characters"):
        parse_memory_response("4250", 4)

    # GDB error raises RuntimeError
    with pytest.raises(RuntimeError, match="GDB memory read returned error"):
        parse_memory_response("E01", 4)


def test_parse_write_response():
    assert parse_write_response("OK") is True
    assert parse_write_response("E01") is False
    assert parse_write_response("") is False
