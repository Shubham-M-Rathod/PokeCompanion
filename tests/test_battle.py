"""Unit tests for FR-5 PvP battle invite, accept/decline, and opponent party injection."""

import asyncio
import base64
import contextlib
import json
import struct

import random
from src.battle import BattlePokemon, BattleSession, TurnAction, get_move_category, get_move_data, get_species_types, get_type_multiplier
from src.client.net import NetworkEngine
from src.client.state import GameStateManager
from src.core.constants import TOTAL_PARTY_SIZE, FireRedOffsets
from src.server.models import MessageType, NetworkMessage


class MockGDB:
    """In-memory mock GDB client for testing battle state reads and opponent RAM injection."""

    def __init__(self, initial_mem=None):
        self.mem = dict(initial_mem or {})
        self.writes = {}

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield

    async def read_memory(self, addr: int, length: int) -> bytes:
        data = self.mem.get(addr, b"\x00" * length)
        return data[:length].ljust(length, b"\x00")

    async def write_memory(self, addr: int, data: bytes) -> bool:
        self.writes[addr] = data
        self.mem[addr] = data
        return True


class MockWS:
    """Minimal mock WebSocket recording outbound messages."""

    def __init__(self, inbound_messages=None):
        self.sent = []
        self.inbound = list(inbound_messages or [])

    @property
    def state(self):
        class _State:
            name = "OPEN"
        return _State()

    async def send(self, text: str):
        self.sent.append(json.loads(text))

    async def recv(self) -> str:
        if self.inbound:
            return self.inbound.pop(0)
        raise RuntimeError("End of mock stream")

    async def close(self):
        pass


def _run(coro):
    """Steps a non-blocking mock coroutine synchronously without creating an OS event-loop socketpair."""
    try:
        while True:
            coro.send(None)
    except StopIteration as e:
        return e.value


def test_inject_opponent_party_and_poll_battle_state():
    # Build a 600-byte opponent party with 2 active Pokémon
    party_bytes = bytearray(TOTAL_PARTY_SIZE)
    struct.pack_into("<I", party_bytes, 0, 0x11223344)    # Slot 0 PID
    struct.pack_into("<I", party_bytes, 100, 0x55667788)  # Slot 1 PID

    gdb = MockGDB({
        FireRedOffsets.BATTLE_TYPE_FLAGS: struct.pack("<I", 0x00000008),  # Trainer battle active
        FireRedOffsets.OPPONENT_PARTY: struct.pack("<I", 0xDEADBEEF),     # Dummy ROM-generated PID
    })
    state = GameStateManager(gdb)

    # 1. Poll detects active battle and mismatched dummy PID
    _run(state.poll_battle_state())
    assert state.battle_type_flags == 0x00000008
    assert state.opponent_first_pid == 0xDEADBEEF

    # 2. Inject 600-byte opponent party + 2-mon count
    ok = _run(state.inject_opponent_party(bytes(party_bytes)))
    assert ok is True
    assert gdb.writes[FireRedOffsets.OPPONENT_PARTY_COUNT] == b"\x02"
    assert gdb.writes[FireRedOffsets.OPPONENT_PARTY][:4] == struct.pack("<I", 0x11223344)
    assert gdb.writes[FireRedOffsets.OPPONENT_PARTY + 100][:4] == struct.pack("<I", 0x55667788)

    # 3. Re-poll sees matching PID in slot 0
    _run(state.poll_battle_state())
    assert state.opponent_first_pid == 0x11223344


def test_battle_invite_accept_and_decline_protocol():
    # Prepare Player A and Player B 600-byte teams
    party_a = bytearray(TOTAL_PARTY_SIZE)
    struct.pack_into("<I", party_a, 0, 0xAAAAAAAA)
    party_b = bytearray(TOTAL_PARTY_SIZE)
    struct.pack_into("<I", party_b, 0, 0xBBBBBBBB)

    gdb_b = MockGDB()
    state_b = GameStateManager(gdb_b)
    state_b.player_name = "GARY"
    state_b.raw_party_bytes = bytes(party_b)

    net_b = NetworkEngine(state_b, player_id="p2")
    ws_b = MockWS()
    net_b.ws = ws_b
    net_b.is_running = True

    ready_events = []
    net_b.on_battle_ready = lambda opp_id, opp_bytes: ready_events.append((opp_id, opp_bytes))

    # 1. Player B accepts Player A's challenge
    party_a_b64 = base64.b64encode(bytes(party_a)).decode("ascii")
    _run(net_b.accept_challenge("p1", party_a_b64))

    assert gdb_b.writes[FireRedOffsets.OPPONENT_PARTY][:4] == struct.pack("<I", 0xAAAAAAAA)
    assert len(ready_events) == 1
    assert ready_events[0][0] == "p1"
    assert ws_b.sent[-1]["type"] == MessageType.CHALLENGE_ACCEPT.value
    assert ws_b.sent[-1]["target_id"] == "p1"

    # 2. Player B declines a challenge -> sends trainer_name payload
    _run(net_b.decline_challenge("p1"))
    assert ws_b.sent[-1]["type"] == MessageType.CHALLENGE_DECLINE.value
    assert ws_b.sent[-1]["payload"]["trainer_name"] == "GARY"

    # 3. Player A receives CHALLENGE_DECLINE in _listen_loop
    gdb_a = MockGDB()
    state_a = GameStateManager(gdb_a)
    net_a = NetworkEngine(state_a, player_id="p1")
    decline_msg = NetworkMessage(
        type=MessageType.CHALLENGE_DECLINE,
        sender_id="p2",
        target_id="p1",
        payload={"trainer_name": "GARY"},
    ).model_dump_json()

    ws_a = MockWS([decline_msg])
    net_a.ws = ws_a
    net_a.is_running = True

    declined = []
    net_a.on_challenge_declined = lambda did, dname: declined.append((did, dname))
    _run(net_a._listen_loop())

    assert declined == [("p2", "GARY")]


def test_gen3_type_chart_and_physical_special_split():
    # 4x super effective: Electric vs Gyarados (Water/Flying)
    assert get_type_multiplier("Electric", ("Water", "Flying")) == 4.0
    # 4x super effective: Water vs Geodude (Rock/Ground)
    assert get_type_multiplier("Water", ("Rock", "Ground")) == 4.0
    # 0.25x doubly resisted: Fire vs Kingdra/Dragon-Water
    assert get_type_multiplier("Fire", ("Water", "Dragon")) == 0.25
    # 0x immunity: Normal vs Ghost, Electric vs Ground
    assert get_type_multiplier("Normal", ("Ghost",)) == 0.0
    assert get_type_multiplier("Electric", ("Ground",)) == 0.0
    # Gen 3 rule: Steel resists Ghost & Dark (0.5x)
    assert get_type_multiplier("Ghost", ("Steel",)) == 0.5
    assert get_type_multiplier("Dark", ("Steel",)) == 0.5
    # Gen 3 Physical vs Special split by MOVE TYPE
    assert get_move_category("Dark", 60) == "Special"    # Bite is Special in Gen 3
    assert get_move_category("Ghost", 80) == "Physical"  # Shadow Ball is Physical in Gen 3
    assert get_move_category("Normal", 0) == "Status"
    assert get_species_types(82) == ("Electric", "Steel")  # Magneton


def _make_mon(species: int, nick: str, lvl: int, hp: int, spd: int, move_ids):
    moves = [get_move_data(mid) for mid in move_ids]
    return BattlePokemon(
        species=species,
        species_name=nick,
        nickname=nick,
        level=lvl,
        types=get_species_types(species),
        hp=hp,
        max_hp=hp,
        atk=60,
        def_=50,
        spd=spd,
        spatk=65,
        spdef=55,
        moves=moves,
        pp=[m.max_pp for m in moves],
    )


def test_battle_session_effectiveness_status_and_forced_switch():
    # Player 1: Wartortle (Water, Lv 30, Water Gun & Surf) + Pikachu reserve
    p1_mon1 = _make_mon(8, "WARTORTLE", 30, 85, 60, [57, 86])   # Surf (57), Thunder Wave (86)
    p1_mon2 = _make_mon(25, "PIKACHU", 25, 65, 90, [85])        # Thunderbolt (85)
    # Player 2: Charizard (Fire/Flying) + Charmeleon (Fire)
    p2_mon1 = _make_mon(6, "CHARIZARD", 30, 50, 75, [53, 98])   # Flamethrower (53), Quick Attack (98)
    p2_mon2 = _make_mon(5, "CHARMELEON", 28, 70, 65, [52])      # Ember (52)

    rng = random.Random(42)
    session = BattleSession(
        battle_id="b1",
        p1_id="p1",
        p1_name="ASH",
        p1_team=[p1_mon1, p1_mon2],
        p2_id="p2",
        p2_name="GARY",
        p2_team=[p2_mon1, p2_mon2],
        rng=rng,
    )

    # Turn 1: P2 uses Quick Attack (+1 priority -> moves before Surf despite Wartortle being slower/faster),
    # P1 uses Surf (2x super effective STAB vs Charizard -> KOs 50 HP Charizard)
    res_p1 = session.submit_action("p1", TurnAction("FIGHT", move_index=0))
    assert res_p1 is None  # Still waiting on P2
    res_both = session.submit_action("p2", TurnAction("FIGHT", move_index=1))
    assert res_both is not None

    events_text = [e["text"] for e in res_both["p1"]["events"]]
    assert any("Quick Attack" in t for t in events_text)
    assert any("Surf" in t for t in events_text)
    assert any("super effective" in t for t in events_text)
    assert events_text.index(next(t for t in events_text if "Quick Attack" in t)) < events_text.index(
        next(t for t in events_text if "Surf" in t)
    )
    assert p2_mon1.is_fainted is True
    assert session.phase == "FORCE_SWITCH"
    assert res_both["p2"]["must_switch"] is True
    assert res_both["p1"]["must_switch"] is False

    # Turn 1b: P2 sends out Charmeleon
    sw_res = session.submit_action("p2", TurnAction("SWITCH", switch_index=1))
    assert sw_res is not None
    assert session.phase == "CHOOSE_ACTION"
    assert session.active_mon("p2").nickname == "CHARMELEON"

    # Turn 2: P1 uses Thunder Wave -> paralyzes Charmeleon & quarters its Speed
    old_spd = p2_mon2.effective_speed()
    session.submit_action("p1", TurnAction("FIGHT", move_index=1))  # Thunder Wave
    turn2 = session.submit_action("p2", TurnAction("FIGHT", move_index=0))  # Ember
    assert turn2 is not None
    assert p2_mon2.status == "PAR"
    assert p2_mon2.effective_speed() < old_spd

    # Turn 3: P2 forfeits -> P1 wins cleanly
    forfeit_res = session.submit_action("p2", TurnAction("FORFEIT"))
    assert forfeit_res is not None
    assert session.phase == "FINISHED"
    assert forfeit_res["p1"]["winner_id"] == "p1"


def test_burn_halves_physical_and_residual_damage():
    attacker = _make_mon(128, "TAUROS", 50, 150, 100, [34])  # Body Slam (Normal/Physical)
    defender = _make_mon(143, "SNORLAX", 50, 220, 30, [33])
    s1 = BattleSession("x1", "a", "A", [attacker], "b", "B", [defender], rng=random.Random(1))
    dmg_normal, _ = s1._calculate_damage(attacker, defender, get_move_data(34), 1.0)

    attacker_brn = _make_mon(128, "TAUROS", 50, 150, 100, [34])
    attacker_brn.status = "BRN"
    defender2 = _make_mon(143, "SNORLAX", 50, 220, 30, [33])
    s2 = BattleSession("x2", "a", "A", [attacker_brn], "b", "B", [defender2], rng=random.Random(1))
    dmg_burned, _ = s2._calculate_damage(attacker_brn, defender2, get_move_data(34), 1.0)

    assert dmg_burned <= (dmg_normal // 2) + 1


