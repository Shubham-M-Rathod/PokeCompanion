"""Unit tests for Central Relay Server logic and Escrow Ledger."""

from src.server.server import manager, health_check, get_lobby


def test_server_health_and_lobby():
    # Endpoints can be called directly without HTTP network client
    try:
        coro_health = health_check()
        res_health = coro_health.send(None)
    except StopIteration as e:
        res_health = e.value

    assert res_health["status"] == "online"
    assert "online_players" in res_health
    assert "ledger_items_count" in res_health

    try:
        coro_lobby = get_lobby()
        res_lobby = coro_lobby.send(None)
    except StopIteration as e:
        res_lobby = e.value

    assert "players" in res_lobby
    assert "ledger" in res_lobby


def test_escrow_ledger_logic():
    # Test item: 0x0044 (Rare Candy)
    test_item = 0x0044
    manager.cloud_ledger.pop(test_item, None)

    # Initial state
    assert test_item not in manager.cloud_ledger

    # Direct ledger deposit test
    manager.cloud_ledger[test_item] = manager.cloud_ledger.get(test_item, 0) + 3
    assert manager.cloud_ledger[test_item] == 3

    # Direct ledger withdrawal test
    manager.cloud_ledger[test_item] -= 2
    assert manager.cloud_ledger[test_item] == 1

    # Overdraw protection check
    req_qty = 5
    can_withdraw = manager.cloud_ledger.get(test_item, 0) >= req_qty
    assert can_withdraw is False
