"""Generation 3 Turn-Based PvP Battle Engine.

Pure Python, framework-agnostic turn resolver using authentic Gen 3 rules:
- Type-based Physical/Special split & 17-type effectiveness chart
- Gen 3 damage formula with STAB, 2.0x Critical Hits, Burn halving Physical
- Paralysis (0.25x Speed + 25% full-para), Sleep, Freeze, Burn, Poison, Toxic, Flinch, Confusion
- Priority & Speed-based turn order, stat stages (-6..+6), multi-hit, drain, recoil, forced switch
"""

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.battle.moves_data import MoveData, get_move_data
from src.battle.pokedex_data import get_species_types
from src.battle.type_chart import get_effectiveness_message, get_type_multiplier
from src.core.constants import PARTY_SLOT_SIZE, PARTY_SLOTS_COUNT
from src.core.pokemon import Pokemon

STAT_STAGE_MIN = -6
STAT_STAGE_MAX = 6

STAT_LABELS = {
    "atk": "Attack",
    "def": "Defense",
    "spd": "Speed",
    "spatk": "Sp. Atk",
    "spdef": "Sp. Def",
    "acc": "Accuracy",
    "eva": "Evasiveness",
}


def _stat_multiplier(stage: int) -> float:
    stage = max(STAT_STAGE_MIN, min(STAT_STAGE_MAX, stage))
    if stage >= 0:
        return (2.0 + stage) / 2.0
    return 2.0 / (2.0 - stage)


def _acc_eva_multiplier(acc_stage: int, eva_stage: int) -> float:
    diff = max(STAT_STAGE_MIN, min(STAT_STAGE_MAX, acc_stage - eva_stage))
    if diff >= 0:
        return (3.0 + diff) / 3.0
    return 3.0 / (3.0 - diff)


def _default_stages() -> Dict[str, int]:
    return {"atk": 0, "def": 0, "spd": 0, "spatk": 0, "spdef": 0, "acc": 0, "eva": 0}


@dataclass
class BattlePokemon:
    species: int
    species_name: str
    nickname: str
    level: int
    types: Tuple[str, ...]
    hp: int
    max_hp: int
    atk: int
    def_: int
    spd: int
    spatk: int
    spdef: int
    moves: List[MoveData]
    pp: List[int]
    status: Optional[str] = None      # None, PAR, BRN, PSN, TOX, SLP, FRZ
    sleep_turns: int = 0
    toxic_counter: int = 0
    confused_turns: int = 0
    flinched: bool = False
    stages: Dict[str, int] = field(default_factory=_default_stages)

    @property
    def is_fainted(self) -> bool:
        return self.hp <= 0

    def reset_volatiles(self) -> None:
        self.stages = _default_stages()
        self.confused_turns = 0
        self.flinched = False
        self.toxic_counter = 1 if self.status == "TOX" else 0

    @classmethod
    def from_core_pokemon(cls, mon: Pokemon) -> "BattlePokemon":
        """Builds a fresh battle-ready Pokémon from decrypted Gen 3 party data."""
        move_objs: List[MoveData] = []
        pp_vals: List[int] = []
        for idx, mid in enumerate(mon.moves):
            if mid > 0:
                mdata = get_move_data(mid)
                move_objs.append(mdata)
                raw_pp = mon.pp[idx] if idx < len(mon.pp) and mon.pp[idx] > 0 else mdata.max_pp
                pp_vals.append(min(raw_pp, mdata.max_pp))

        if not move_objs:
            tackle = get_move_data(33)
            move_objs = [tackle]
            pp_vals = [tackle.max_pp]

        max_hp = max(1, mon.max_hp)
        return cls(
            species=mon.species,
            species_name=mon.species_name,
            nickname=mon.nickname or mon.species_name,
            level=max(1, mon.level),
            types=get_species_types(mon.species),
            hp=max_hp,  # Standard Colosseum/Link Battle heals to full HP at battle start
            max_hp=max_hp,
            atk=max(1, mon.attack),
            def_=max(1, mon.defense),
            spd=max(1, mon.speed),
            spatk=max(1, mon.sp_attack),
            spdef=max(1, mon.sp_defense),
            moves=move_objs,
            pp=pp_vals,
        )

    def effective_speed(self) -> int:
        val = int(self.spd * _stat_multiplier(self.stages["spd"]))
        if self.status == "PAR":
            val = max(1, int(val * 0.25))  # Gen 3 Paralysis quarters Speed
        return max(1, val)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "species": self.species,
            "species_name": self.species_name,
            "nickname": self.nickname,
            "level": self.level,
            "types": list(self.types),
            "hp": self.hp,
            "max_hp": self.max_hp,
            "status": self.status,
            "fainted": self.is_fainted,
            "stages": {k: v for k, v in self.stages.items() if v != 0},
        }

    def to_private_dict(self) -> Dict[str, Any]:
        data = self.to_public_dict()
        data["moves"] = [
            {
                "move_id": m.move_id,
                "name": m.name,
                "type": m.move_type,
                "category": m.category,
                "power": m.power,
                "accuracy": m.accuracy,
                "pp": self.pp[idx],
                "max_pp": m.max_pp,
            }
            for idx, m in enumerate(self.moves)
        ]
        return data


@dataclass
class TurnAction:
    action_type: str  # "FIGHT", "SWITCH", "FORFEIT"
    move_index: int = 0
    switch_index: int = 0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TurnAction":
        return cls(
            action_type=str(payload.get("action_type", "FIGHT")).upper(),
            move_index=int(payload.get("move_index", 0)),
            switch_index=int(payload.get("switch_index", 0)),
        )


def parse_party_for_battle(party_600_bytes: bytes) -> List[BattlePokemon]:
    """Extracts valid party Pokémon from raw 600-byte GBA memory."""
    team: List[BattlePokemon] = []
    for i in range(PARTY_SLOTS_COUNT):
        chunk = party_600_bytes[i * PARTY_SLOT_SIZE : (i + 1) * PARTY_SLOT_SIZE]
        if len(chunk) == PARTY_SLOT_SIZE:
            mon = Pokemon.from_bytes(chunk)
            if mon.is_valid():
                team.append(BattlePokemon.from_core_pokemon(mon))
    return team


class BattleSession:
    """Authoritative server-side turn-by-turn Gen 3 PvP battle state machine."""

    def __init__(
        self,
        battle_id: str,
        p1_id: str,
        p1_name: str,
        p1_team: List[BattlePokemon],
        p2_id: str,
        p2_name: str,
        p2_team: List[BattlePokemon],
        rng: Optional[random.Random] = None,
    ):
        self.battle_id = battle_id
        self.p1_id = p1_id
        self.p2_id = p2_id
        self.names = {p1_id: p1_name or p1_id, p2_id: p2_name or p2_id}
        self.teams: Dict[str, List[BattlePokemon]] = {p1_id: p1_team, p2_id: p2_team}
        self.active_idx: Dict[str, int] = {p1_id: 0, p2_id: 0}
        self.rng = rng or random.Random()

        self.turn_number: int = 1
        self.phase: str = "CHOOSE_ACTION"  # "CHOOSE_ACTION", "FORCE_SWITCH", "FINISHED"
        self.force_switch_players: List[str] = []
        self.winner_id: Optional[str] = None
        self.pending_actions: Dict[str, TurnAction] = {}

    def opponent_of(self, player_id: str) -> str:
        return self.p2_id if player_id == self.p1_id else self.p1_id

    def active_mon(self, player_id: str) -> BattlePokemon:
        return self.teams[player_id][self.active_idx[player_id]]

    def alive_indices(self, player_id: str) -> List[int]:
        return [i for i, m in enumerate(self.teams[player_id]) if not m.is_fainted]

    def submit_action(self, player_id: str, action: TurnAction) -> Optional[Dict[str, Any]]:
        """Records a player's choice. Resolves the step once all required players have chosen."""
        if self.phase == "FINISHED" or player_id not in self.teams:
            return None

        # Instant forfeit ends battle immediately
        if action.action_type == "FORFEIT":
            opp = self.opponent_of(player_id)
            self.phase = "FINISHED"
            self.winner_id = opp
            events = [
                self._event(f"{self.names[player_id]} forfeited the battle!"),
                self._event(f"🏆 {self.names[opp]} won the battle!"),
            ]
            return self._build_result_payload(events)

        if self.phase == "FORCE_SWITCH":
            if player_id not in self.force_switch_players:
                return None
            if not self._is_valid_switch(player_id, action.switch_index):
                return None
            self.pending_actions[player_id] = action
            if all(pid in self.pending_actions for pid in self.force_switch_players):
                return self._resolve_force_switches()
            return None

        # Normal CHOOSE_ACTION phase
        if action.action_type == "SWITCH" and not self._is_valid_switch(player_id, action.switch_index):
            return None

        self.pending_actions[player_id] = action
        if len(self.pending_actions) == 2:
            return self._resolve_normal_turn()
        return None

    def _is_valid_switch(self, player_id: str, idx: int) -> bool:
        team = self.teams[player_id]
        return 0 <= idx < len(team) and idx != self.active_idx[player_id] and not team[idx].is_fainted

    def _event(self, text: str, kind: str = "msg", side: Optional[str] = None, **extra) -> Dict[str, Any]:
        ev: Dict[str, Any] = {"text": text, "kind": kind}
        if side is not None:
            ev["player_id"] = side
        ev.update(extra)
        return ev

    def _resolve_force_switches(self) -> Dict[str, Any]:
        events: List[Dict[str, Any]] = []
        for pid in list(self.force_switch_players):
            act = self.pending_actions.pop(pid)
            self._perform_switch(pid, act.switch_index, events)

        self.force_switch_players.clear()
        self.pending_actions.clear()
        self.phase = "CHOOSE_ACTION"
        self.turn_number += 1
        return self._build_result_payload(events)

    def _resolve_normal_turn(self) -> Dict[str, Any]:
        p1_act = self.pending_actions.pop(self.p1_id)
        p2_act = self.pending_actions.pop(self.p2_id)
        self.pending_actions.clear()
        events: List[Dict[str, Any]] = []

        # Clear turn-scoped flinch flags
        self.active_mon(self.p1_id).flinched = False
        self.active_mon(self.p2_id).flinched = False

        # 1. Process SWITCH actions before FIGHT actions
        actions = [(self.p1_id, p1_act), (self.p2_id, p2_act)]
        fight_queue: List[Tuple[str, TurnAction, MoveData]] = []

        for pid, act in actions:
            if act.action_type == "SWITCH":
                self._perform_switch(pid, act.switch_index, events)
            else:
                move = self._pick_move(pid, act.move_index)
                fight_queue.append((pid, act, move))

        # 2. Sort FIGHT actions by Move Priority, then Effective Speed, then random tie-break
        fight_queue.sort(
            key=lambda item: (
                item[2].priority,
                self.active_mon(item[0]).effective_speed(),
                self.rng.random(),
            ),
            reverse=True,
        )

        # 3. Execute attacks in speed order
        for pid, act, move in fight_queue:
            attacker = self.active_mon(pid)
            opp_id = self.opponent_of(pid)
            defender = self.active_mon(opp_id)
            if attacker.is_fainted or defender.is_fainted:
                continue
            self._execute_move(pid, opp_id, act.move_index, move, events)

            if defender.is_fainted:
                events.append(self._event(f"{defender.nickname} fainted!", kind="faint", side=opp_id))
            if attacker.is_fainted:
                events.append(self._event(f"{attacker.nickname} fainted!", kind="faint", side=pid))

        # 4. End-of-turn residual status damage (Burn / Poison / Toxic)
        for pid in (self.p1_id, self.p2_id):
            mon = self.active_mon(pid)
            if not mon.is_fainted:
                self._apply_residual_damage(pid, mon, events)

        # 5. Check victory or forced switches
        self._update_post_turn_phase(events)
        if self.phase == "CHOOSE_ACTION":
            self.turn_number += 1

        return self._build_result_payload(events)

    def _perform_switch(self, pid: str, new_idx: int, events: List[Dict[str, Any]]) -> None:
        old_mon = self.active_mon(pid)
        if not old_mon.is_fainted:
            old_mon.reset_volatiles()
            events.append(self._event(f"{self.names[pid]} withdrew {old_mon.nickname}!", kind="switch", side=pid))

        self.active_idx[pid] = new_idx
        new_mon = self.active_mon(pid)
        new_mon.reset_volatiles()
        events.append(self._event(f"{self.names[pid]} sent out {new_mon.nickname}!", kind="switch", side=pid))

    def _pick_move(self, pid: str, move_index: int) -> MoveData:
        mon = self.active_mon(pid)
        if 0 <= move_index < len(mon.moves) and mon.pp[move_index] > 0:
            return mon.moves[move_index]
        # Fallback to first move with PP, or Struggle
        for idx, pp in enumerate(mon.pp):
            if pp > 0:
                return mon.moves[idx]
        return get_move_data(165)  # Struggle

    def _consume_pp(self, mon: BattlePokemon, move_index: int, move: MoveData) -> None:
        if move.move_id == 165:
            return
        if 0 <= move_index < len(mon.moves) and mon.moves[move_index].move_id == move.move_id:
            mon.pp[move_index] = max(0, mon.pp[move_index] - 1)

    def _can_act_check_status(
        self, pid: str, mon: BattlePokemon, move: MoveData, events: List[Dict[str, Any]]
    ) -> bool:
        if mon.flinched:
            events.append(self._event(f"{mon.nickname} flinched and couldn't move!", kind="status", side=pid))
            return False

        if mon.status == "SLP":
            if mon.sleep_turns > 0:
                mon.sleep_turns -= 1
            if mon.sleep_turns > 0:
                events.append(self._event(f"{mon.nickname} is fast asleep.", kind="status", side=pid))
                return False
            mon.status = None
            events.append(self._event(f"{mon.nickname} woke up!", kind="status", side=pid))

        elif mon.status == "FRZ":
            # Fire-type user move or 20% chance thaws in Gen 3
            if move.move_type == "Fire" or self.rng.random() < 0.20:
                mon.status = None
                events.append(self._event(f"{mon.nickname} thawed out!", kind="status", side=pid))
            else:
                events.append(self._event(f"{mon.nickname} is frozen solid!", kind="status", side=pid))
                return False

        elif mon.status == "PAR":
            if self.rng.random() < 0.25:
                events.append(self._event(f"{mon.nickname} is paralyzed! It can't move!", kind="status", side=pid))
                return False

        if mon.confused_turns > 0:
            mon.confused_turns -= 1
            if mon.confused_turns == 0:
                events.append(self._event(f"{mon.nickname} snapped out of confusion!", kind="status", side=pid))
            else:
                events.append(self._event(f"{mon.nickname} is confused!", kind="status", side=pid))
                if self.rng.random() < 0.50:
                    # 40-power typeless physical self-hit
                    self_dmg = self._calc_confusion_damage(mon)
                    mon.hp = max(0, mon.hp - self_dmg)
                    events.append(
                        self._event(
                            f"It hurt itself in its confusion! (-{self_dmg} HP)",
                            kind="damage",
                            side=pid,
                            damage=self_dmg,
                        )
                    )
                    return False

        return True

    def _execute_move(
        self,
        att_id: str,
        def_id: str,
        move_index: int,
        move: MoveData,
        events: List[Dict[str, Any]],
    ) -> None:
        attacker = self.active_mon(att_id)
        defender = self.active_mon(def_id)

        if not self._can_act_check_status(att_id, attacker, move, events):
            return

        self._consume_pp(attacker, move_index, move)
        events.append(self._event(f"{attacker.nickname} used {move.name}!", kind="attack", side=att_id, move_type=move.move_type))

        # Accuracy check (0 means never-miss)
        if move.accuracy > 0:
            hit_chance = move.accuracy * _acc_eva_multiplier(attacker.stages["acc"], defender.stages["eva"])
            if self.rng.uniform(0, 100) > hit_chance:
                events.append(self._event(f"{attacker.nickname}'s attack missed!", kind="miss", side=att_id))
                return

        # Damaging vs Pure Status move
        if move.power > 0:
            type_mult = get_type_multiplier(move.move_type, defender.types) if move.move_id != 165 else 1.0
            if type_mult == 0.0 and not move.fixed_damage and not move.level_damage:
                events.append(self._event(get_effectiveness_message(0.0, defender.nickname), kind="immune", side=def_id))
                return

            # Note: fixed-damage moves still respect Ghost/Normal immunities in Gen 3 (unless typeless)
            if (move.fixed_damage or move.level_damage) and type_mult == 0.0:
                events.append(self._event(get_effectiveness_message(0.0, defender.nickname), kind="immune", side=def_id))
                return

            hits = 1
            if move.max_hits > 1:
                hits = self.rng.randint(move.min_hits, move.max_hits)

            total_damage = 0
            any_crit = False
            for _ in range(hits):
                if defender.is_fainted:
                    break
                dmg, is_crit = self._calculate_damage(attacker, defender, move, type_mult)
                defender.hp = max(0, defender.hp - dmg)
                total_damage += dmg
                if is_crit:
                    any_crit = True

            # Fire attack thaws a frozen defender
            if defender.status == "FRZ" and move.move_type == "Fire" and not defender.is_fainted:
                defender.status = None
                events.append(self._event(f"{defender.nickname} thawed out!", kind="status", side=def_id))

            events.append(
                self._event(
                    f"{defender.nickname} took {total_damage} damage!",
                    kind="damage",
                    side=def_id,
                    damage=total_damage,
                    effectiveness=type_mult,
                )
            )
            if hits > 1:
                events.append(self._event(f"Hit {hits} time(s)!"))
            if any_crit:
                events.append(self._event("A critical hit!", kind="crit"))
            eff_msg = get_effectiveness_message(type_mult, defender.nickname)
            if eff_msg and not move.fixed_damage and not move.level_damage:
                events.append(self._event(eff_msg, kind="effectiveness", multiplier=type_mult))

            # Drain HP
            if move.drain_ratio > 0 and total_damage > 0 and not attacker.is_fainted:
                heal = max(1, int(total_damage * move.drain_ratio))
                attacker.hp = min(attacker.max_hp, attacker.hp + heal)
                events.append(self._event(f"{attacker.nickname} absorbed energy! (+{heal} HP)", kind="heal", side=att_id))

            # Recoil
            if move.recoil_ratio > 0 and total_damage > 0 and not attacker.is_fainted:
                recoil = attacker.hp if move.recoil_ratio >= 1.0 else max(1, int(total_damage * move.recoil_ratio))
                attacker.hp = max(0, attacker.hp - recoil)
                events.append(self._event(f"{attacker.nickname} is hit with recoil! (-{recoil} HP)", kind="damage", side=att_id))

        # Apply Secondary / Status Effects
        if move.status_effect and not defender.is_fainted:
            if self.rng.uniform(0, 100) <= move.status_chance:
                self._apply_status_effect(def_id, defender, move, events)

        # Apply Stat Stage Changes
        if move.self_stat_changes and not attacker.is_fainted:
            self._apply_stat_changes(att_id, attacker, move.self_stat_changes, events)
        if move.target_stat_changes and not defender.is_fainted:
            self._apply_stat_changes(def_id, defender, move.target_stat_changes, events)

    def _calculate_damage(
        self, attacker: BattlePokemon, defender: BattlePokemon, move: MoveData, type_mult: float
    ) -> Tuple[int, bool]:
        if move.level_damage:
            return attacker.level, False
        if move.fixed_damage is not None:
            return move.fixed_damage, False

        # Critical Hit Check (Gen 3: 1/16 base, 1/8 for high-crit moves, 2.0x multiplier)
        crit_rate = 1 / 8 if move.high_crit else 1 / 16
        is_crit = self.rng.random() < crit_rate

        is_special = move.category == "Special"
        atk_stage = attacker.stages["spatk"] if is_special else attacker.stages["atk"]
        def_stage = defender.stages["spdef"] if is_special else defender.stages["def"]

        # Gen 3 Crit ignores negative attack stages and positive defense stages
        if is_crit:
            atk_stage = max(0, atk_stage)
            def_stage = min(0, def_stage)

        base_atk = attacker.spatk if is_special else attacker.atk
        base_def = defender.spdef if is_special else defender.def_
        eff_atk = max(1.0, base_atk * _stat_multiplier(atk_stage))
        eff_def = max(1.0, base_def * _stat_multiplier(def_stage))

        power = move.power
        # Facade doubles power if user is PAR/BRN/PSN/TOX
        if move.move_id == 263 and attacker.status in ("PAR", "BRN", "PSN", "TOX"):
            power *= 2

        base_damage = (((2.0 * attacker.level) / 5.0 + 2.0) * power * (eff_atk / eff_def)) / 50.0 + 2.0

        # Burn halves physical damage (Facade ignores burn penalty in Gen 3? Actually in Gen 3 Burn still halves Facade unless Gen 6+, wait: standard Gen 3 Burn halves Physical)
        if not is_special and attacker.status == "BRN":
            base_damage = max(1.0, base_damage * 0.5)

        if is_crit:
            base_damage *= 2.0

        # Random roll (0.85 to 1.00)
        base_damage *= self.rng.uniform(0.85, 1.00)

        # STAB (1.5x if attacker shares type with move)
        if move.move_type in attacker.types and move.move_id != 165:
            base_damage *= 1.5

        # Type Effectiveness
        base_damage *= type_mult

        return max(1, int(base_damage)), is_crit

    def _calc_confusion_damage(self, mon: BattlePokemon) -> int:
        eff_atk = max(1.0, mon.atk * _stat_multiplier(mon.stages["atk"]))
        eff_def = max(1.0, mon.def_ * _stat_multiplier(mon.stages["def"]))
        dmg = (((2.0 * mon.level) / 5.0 + 2.0) * 40.0 * (eff_atk / eff_def)) / 50.0 + 2.0
        return max(1, int(dmg * self.rng.uniform(0.85, 1.0)))

    def _apply_status_effect(
        self, target_id: str, target: BattlePokemon, move: MoveData, events: List[Dict[str, Any]]
    ) -> None:
        eff = move.status_effect
        if eff == "FLINCH":
            target.flinched = True
            return
        if eff == "CONFUSE":
            if target.confused_turns == 0:
                target.confused_turns = self.rng.randint(2, 5)
                events.append(self._event(f"{target.nickname} became confused!", kind="status", side=target_id))
            elif move.power == 0:
                events.append(self._event(f"{target.nickname} is already confused!"))
            return

        # Major status condition: only one allowed at a time
        if target.status is not None:
            if move.power == 0:
                events.append(self._event(f"But it failed! ({target.nickname} already has {target.status})"))
            return

        # Type immunities (Gen 3)
        if eff == "BRN" and "Fire" in target.types:
            if move.power == 0:
                events.append(self._event(f"It doesn't affect {target.nickname}..."))
            return
        if eff in ("PSN", "TOX") and ("Poison" in target.types or "Steel" in target.types):
            if move.power == 0:
                events.append(self._event(f"It doesn't affect {target.nickname}..."))
            return
        if eff == "FRZ" and "Ice" in target.types:
            return
        if eff == "PAR" and move.move_type == "Electric" and "Ground" in target.types and move.power == 0:
            events.append(self._event(f"It doesn't affect {target.nickname}..."))
            return

        target.status = eff
        if eff == "SLP":
            target.sleep_turns = self.rng.randint(2, 4)
            events.append(self._event(f"{target.nickname} fell asleep!", kind="status", side=target_id))
        elif eff == "PAR":
            events.append(self._event(f"{target.nickname} is paralyzed! It may be unable to move!", kind="status", side=target_id))
        elif eff == "BRN":
            events.append(self._event(f"{target.nickname} was burned!", kind="status", side=target_id))
        elif eff == "PSN":
            events.append(self._event(f"{target.nickname} was poisoned!", kind="status", side=target_id))
        elif eff == "TOX":
            target.toxic_counter = 1
            events.append(self._event(f"{target.nickname} was badly poisoned!", kind="status", side=target_id))
        elif eff == "FRZ":
            events.append(self._event(f"{target.nickname} was frozen solid!", kind="status", side=target_id))

    def _apply_stat_changes(
        self, pid: str, target: BattlePokemon, changes: Dict[str, int], events: List[Dict[str, Any]]
    ) -> None:
        for stat, delta in changes.items():
            old_val = target.stages.get(stat, 0)
            new_val = max(STAT_STAGE_MIN, min(STAT_STAGE_MAX, old_val + delta))
            label = STAT_LABELS.get(stat, stat)
            if new_val == old_val:
                limit_word = "higher" if delta > 0 else "lower"
                events.append(self._event(f"{target.nickname}'s {label} won't go any {limit_word}!"))
                continue
            target.stages[stat] = new_val
            if delta >= 2:
                phrase = "sharply rose"
            elif delta == 1:
                phrase = "rose"
            elif delta <= -2:
                phrase = "harshly fell"
            else:
                phrase = "fell"
            events.append(self._event(f"{target.nickname}'s {label} {phrase}!", kind="stat", side=pid))

    def _apply_residual_damage(self, pid: str, mon: BattlePokemon, events: List[Dict[str, Any]]) -> None:
        if mon.status == "BRN":
            dmg = max(1, mon.max_hp // 8)
            mon.hp = max(0, mon.hp - dmg)
            events.append(self._event(f"{mon.nickname} was hurt by its burn! (-{dmg} HP)", kind="damage", side=pid))
        elif mon.status == "PSN":
            dmg = max(1, mon.max_hp // 8)
            mon.hp = max(0, mon.hp - dmg)
            events.append(self._event(f"{mon.nickname} was hurt by poison! (-{dmg} HP)", kind="damage", side=pid))
        elif mon.status == "TOX":
            mon.toxic_counter = min(15, max(1, mon.toxic_counter))
            dmg = max(1, (mon.max_hp * mon.toxic_counter) // 16)
            mon.hp = max(0, mon.hp - dmg)
            mon.toxic_counter += 1
            events.append(self._event(f"{mon.nickname} was hurt by poison! (-{dmg} HP)", kind="damage", side=pid))

        if mon.is_fainted:
            events.append(self._event(f"{mon.nickname} fainted!", kind="faint", side=pid))

    def _update_post_turn_phase(self, events: List[Dict[str, Any]]) -> None:
        p1_alive = self.alive_indices(self.p1_id)
        p2_alive = self.alive_indices(self.p2_id)

        if not p1_alive and not p2_alive:
            self.phase = "FINISHED"
            self.winner_id = "DRAW"
            events.append(self._event("Both teams fainted! It's a draw!"))
            return
        if not p1_alive:
            self.phase = "FINISHED"
            self.winner_id = self.p2_id
            events.append(self._event(f"🏆 {self.names[self.p2_id]} defeated {self.names[self.p1_id]}!"))
            return
        if not p2_alive:
            self.phase = "FINISHED"
            self.winner_id = self.p1_id
            events.append(self._event(f"🏆 {self.names[self.p1_id]} defeated {self.names[self.p2_id]}!"))
            return

        need_switch: List[str] = []
        for pid in (self.p1_id, self.p2_id):
            if self.active_mon(pid).is_fainted:
                need_switch.append(pid)

        if need_switch:
            self.phase = "FORCE_SWITCH"
            self.force_switch_players = need_switch
        else:
            self.phase = "CHOOSE_ACTION"
            self.force_switch_players = []

    def get_view_for(self, player_id: str) -> Dict[str, Any]:
        """Builds a player-scoped view (full private stats for self, public view for opponent)."""
        opp_id = self.opponent_of(player_id)
        return {
            "battle_id": self.battle_id,
            "turn": self.turn_number,
            "phase": self.phase,
            "winner_id": self.winner_id,
            "must_switch": player_id in self.force_switch_players,
            "waiting_for_players": [
                pid for pid in ([self.p1_id, self.p2_id] if self.phase == "CHOOSE_ACTION" else self.force_switch_players)
                if pid not in self.pending_actions
            ],
            "you": {
                "player_id": player_id,
                "trainer_name": self.names[player_id],
                "active_index": self.active_idx[player_id],
                "active": self.active_mon(player_id).to_private_dict(),
                "team": [m.to_private_dict() for m in self.teams[player_id]],
            },
            "opponent": {
                "player_id": opp_id,
                "trainer_name": self.names[opp_id],
                "active_index": self.active_idx[opp_id],
                "active": self.active_mon(opp_id).to_public_dict(),
                "party_status": [
                    {"fainted": m.is_fainted, "status": m.status} for m in self.teams[opp_id]
                ],
            },
        }

    def _build_result_payload(self, events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {
            pid: {
                **self.get_view_for(pid),
                "events": events,
            }
            for pid in (self.p1_id, self.p2_id)
        }

