"""Generation 3 Move Database (FireRed / Emerald) for the PvP Battle Engine.

Provides exact Gen 3 move types, base power, accuracy, PP, priority,
critical-hit bonuses, status effects, and stat-stage modifiers.
Unknown move IDs safely degrade to a neutral 50-power Normal move so battles never crash.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from src.battle.type_chart import get_move_category


@dataclass(frozen=True)
class MoveData:
    move_id: int
    name: str
    move_type: str
    power: int = 0
    accuracy: int = 100          # 0 means never-miss (e.g. Swift, Aerial Ace)
    max_pp: int = 20
    priority: int = 0
    high_crit: bool = False
    status_effect: Optional[str] = None     # PAR, BRN, PSN, TOX, SLP, FRZ, CONFUSE, FLINCH
    status_chance: int = 0                  # Percentage (0-100)
    self_stat_changes: Dict[str, int] = field(default_factory=dict)
    target_stat_changes: Dict[str, int] = field(default_factory=dict)
    drain_ratio: float = 0.0                # e.g. 0.5 for Giga Drain / Absorb
    recoil_ratio: float = 0.0               # e.g. 0.25 for Take Down / 0.33 for Double-Edge
    fixed_damage: Optional[int] = None      # e.g. 40 for Dragon Rage, 20 for SonicBoom
    level_damage: bool = False              # True for Seismic Toss / Night Shade
    min_hits: int = 1
    max_hits: int = 1

    @property
    def category(self) -> str:
        return get_move_category(self.move_type, self.power)


def _m(
    mid: int,
    name: str,
    mtype: str,
    power: int = 0,
    acc: int = 100,
    pp: int = 20,
    **kwargs,
) -> Tuple[int, MoveData]:
    return mid, MoveData(move_id=mid, name=name, move_type=mtype, power=power, accuracy=acc, max_pp=pp, **kwargs)


# Gen 3 Move Definitions (accurate Gen 3 stats: e.g., Bite is Dark/Special in Gen 3, Water Gun 40, Surf 95)
MOVES_DB: Dict[int, MoveData] = dict([
    _m(1, "Pound", "Normal", 40, 100, 35),
    _m(2, "Karate Chop", "Fighting", 50, 100, 25, high_crit=True),
    _m(3, "DoubleSlap", "Normal", 15, 85, 10, min_hits=2, max_hits=5),
    _m(5, "Mega Punch", "Normal", 80, 85, 20),
    _m(7, "Fire Punch", "Fire", 75, 100, 15, status_effect="BRN", status_chance=10),
    _m(8, "Ice Punch", "Ice", 75, 100, 15, status_effect="FRZ", status_chance=10),
    _m(9, "ThunderPunch", "Electric", 75, 100, 15, status_effect="PAR", status_chance=10),
    _m(10, "Scratch", "Normal", 40, 100, 35),
    _m(13, "Razor Wind", "Normal", 80, 100, 10, high_crit=True),
    _m(14, "Swords Dance", "Normal", 0, 0, 30, self_stat_changes={"atk": 2}),
    _m(15, "Cut", "Normal", 50, 95, 30),
    _m(16, "Gust", "Flying", 40, 100, 35),
    _m(17, "Wing Attack", "Flying", 60, 100, 35),
    _m(19, "Fly", "Flying", 70, 95, 15),
    _m(22, "Vine Whip", "Grass", 35, 100, 10),
    _m(23, "Stomp", "Normal", 65, 100, 20, status_effect="FLINCH", status_chance=30),
    _m(24, "Double Kick", "Fighting", 30, 100, 30, min_hits=2, max_hits=2),
    _m(25, "Mega Kick", "Normal", 120, 75, 5),
    _m(28, "Sand-Attack", "Ground", 0, 100, 15, target_stat_changes={"acc": -1}),
    _m(29, "Headbutt", "Normal", 70, 100, 15, status_effect="FLINCH", status_chance=30),
    _m(30, "Horn Attack", "Normal", 65, 100, 25),
    _m(31, "Fury Attack", "Normal", 15, 85, 20, min_hits=2, max_hits=5),
    _m(33, "Tackle", "Normal", 35, 95, 35),
    _m(34, "Body Slam", "Normal", 85, 100, 15, status_effect="PAR", status_chance=30),
    _m(36, "Take Down", "Normal", 90, 85, 20, recoil_ratio=0.25),
    _m(37, "Thrash", "Normal", 90, 100, 20),
    _m(38, "Double-Edge", "Normal", 120, 100, 15, recoil_ratio=0.33),
    _m(39, "Tail Whip", "Normal", 0, 100, 30, target_stat_changes={"def": -1}),
    _m(40, "Poison Sting", "Poison", 15, 100, 35, status_effect="PSN", status_chance=30),
    _m(41, "Twineedle", "Bug", 25, 100, 20, min_hits=2, max_hits=2, status_effect="PSN", status_chance=20),
    _m(42, "Pin Missile", "Bug", 14, 85, 20, min_hits=2, max_hits=5),
    _m(43, "Leer", "Normal", 0, 100, 30, target_stat_changes={"def": -1}),
    _m(44, "Bite", "Dark", 60, 100, 25, status_effect="FLINCH", status_chance=30),
    _m(45, "Growl", "Normal", 0, 100, 40, target_stat_changes={"atk": -1}),
    _m(47, "Sing", "Normal", 0, 55, 15, status_effect="SLP", status_chance=100),
    _m(48, "Supersonic", "Normal", 0, 55, 20, status_effect="CONFUSE", status_chance=100),
    _m(49, "SonicBoom", "Normal", 1, 90, 20, fixed_damage=20),
    _m(51, "Acid", "Poison", 40, 100, 30, target_stat_changes={"def": -1}),
    _m(52, "Ember", "Fire", 40, 100, 25, status_effect="BRN", status_chance=10),
    _m(53, "Flamethrower", "Fire", 95, 100, 15, status_effect="BRN", status_chance=10),
    _m(55, "Water Gun", "Water", 40, 100, 25),
    _m(56, "Hydro Pump", "Water", 120, 80, 5),
    _m(57, "Surf", "Water", 95, 100, 15),
    _m(58, "Ice Beam", "Ice", 95, 100, 10, status_effect="FRZ", status_chance=10),
    _m(59, "Blizzard", "Ice", 120, 70, 5, status_effect="FRZ", status_chance=10),
    _m(60, "Psybeam", "Psychic", 65, 100, 20, status_effect="CONFUSE", status_chance=10),
    _m(61, "BubbleBeam", "Water", 65, 100, 20),
    _m(62, "Aurora Beam", "Ice", 65, 100, 20),
    _m(63, "Hyper Beam", "Normal", 150, 90, 5),
    _m(64, "Peck", "Flying", 35, 100, 35),
    _m(65, "Drill Peck", "Flying", 80, 100, 20),
    _m(66, "Submission", "Fighting", 80, 80, 25, recoil_ratio=0.25),
    _m(67, "Low Kick", "Fighting", 60, 100, 20),
    _m(69, "Seismic Toss", "Fighting", 1, 100, 20, level_damage=True),
    _m(70, "Strength", "Normal", 80, 100, 15),
    _m(71, "Absorb", "Grass", 20, 100, 20, drain_ratio=0.5),
    _m(72, "Mega Drain", "Grass", 40, 100, 10, drain_ratio=0.5),
    _m(73, "Leech Seed", "Grass", 0, 90, 10, status_effect="PSN", status_chance=100),
    _m(74, "Growth", "Normal", 0, 0, 40, self_stat_changes={"spatk": 1}),
    _m(75, "Razor Leaf", "Grass", 55, 95, 25, high_crit=True),
    _m(76, "SolarBeam", "Grass", 120, 100, 10),
    _m(77, "PoisonPowder", "Poison", 0, 75, 35, status_effect="PSN", status_chance=100),
    _m(78, "Stun Spore", "Grass", 0, 75, 30, status_effect="PAR", status_chance=100),
    _m(79, "Sleep Powder", "Grass", 0, 75, 15, status_effect="SLP", status_chance=100),
    _m(81, "String Shot", "Bug", 0, 95, 40, target_stat_changes={"spd": -1}),
    _m(82, "Dragon Rage", "Dragon", 1, 100, 10, fixed_damage=40),
    _m(83, "Fire Spin", "Fire", 15, 70, 15),
    _m(84, "ThunderShock", "Electric", 40, 100, 30, status_effect="PAR", status_chance=10),
    _m(85, "Thunderbolt", "Electric", 95, 100, 15, status_effect="PAR", status_chance=10),
    _m(86, "Thunder Wave", "Electric", 0, 100, 20, status_effect="PAR", status_chance=100),
    _m(87, "Thunder", "Electric", 120, 70, 10, status_effect="PAR", status_chance=30),
    _m(88, "Rock Throw", "Rock", 50, 90, 15),
    _m(89, "Earthquake", "Ground", 100, 100, 10),
    _m(91, "Dig", "Ground", 60, 100, 10),
    _m(92, "Toxic", "Poison", 0, 85, 10, status_effect="TOX", status_chance=100),
    _m(93, "Confusion", "Psychic", 50, 100, 25, status_effect="CONFUSE", status_chance=10),
    _m(94, "Psychic", "Psychic", 90, 100, 10),
    _m(95, "Hypnosis", "Psychic", 0, 60, 20, status_effect="SLP", status_chance=100),
    _m(96, "Meditate", "Psychic", 0, 0, 40, self_stat_changes={"atk": 1}),
    _m(97, "Agility", "Psychic", 0, 0, 30, self_stat_changes={"spd": 2}),
    _m(98, "Quick Attack", "Normal", 40, 100, 30, priority=1),
    _m(99, "Rage", "Normal", 20, 100, 20, self_stat_changes={"atk": 1}),
    _m(101, "Night Shade", "Ghost", 1, 100, 15, level_damage=True),
    _m(103, "Screech", "Normal", 0, 85, 40, target_stat_changes={"def": -2}),
    _m(104, "Double Team", "Normal", 0, 0, 15, self_stat_changes={"eva": 1}),
    _m(106, "Harden", "Normal", 0, 0, 30, self_stat_changes={"def": 1}),
    _m(107, "Minimize", "Normal", 0, 0, 20, self_stat_changes={"eva": 1}),
    _m(108, "SmokeScreen", "Normal", 0, 100, 20, target_stat_changes={"acc": -1}),
    _m(109, "Confuse Ray", "Ghost", 0, 100, 10, status_effect="CONFUSE", status_chance=100),
    _m(110, "Withdraw", "Water", 0, 0, 40, self_stat_changes={"def": 1}),
    _m(111, "Defense Curl", "Normal", 0, 0, 40, self_stat_changes={"def": 1}),
    _m(112, "Barrier", "Psychic", 0, 0, 30, self_stat_changes={"def": 2}),
    _m(120, "Selfdestruct", "Normal", 200, 100, 5, recoil_ratio=1.0),
    _m(121, "Egg Bomb", "Normal", 100, 75, 10),
    _m(122, "Lick", "Ghost", 20, 100, 30, status_effect="PAR", status_chance=30),
    _m(123, "Smog", "Poison", 20, 70, 20, status_effect="PSN", status_chance=40),
    _m(124, "Sludge", "Poison", 65, 100, 20, status_effect="PSN", status_chance=30),
    _m(125, "Bone Club", "Ground", 65, 85, 20, status_effect="FLINCH", status_chance=10),
    _m(126, "Fire Blast", "Fire", 120, 85, 5, status_effect="BRN", status_chance=10),
    _m(127, "Waterfall", "Water", 80, 100, 15),
    _m(129, "Swift", "Normal", 60, 0, 20),
    _m(130, "Skull Bash", "Normal", 100, 100, 15),
    _m(133, "Amnesia", "Psychic", 0, 0, 20, self_stat_changes={"spdef": 2}),
    _m(136, "Hi Jump Kick", "Fighting", 85, 90, 20),
    _m(137, "Glare", "Normal", 0, 75, 30, status_effect="PAR", status_chance=100),
    _m(139, "Poison Gas", "Poison", 0, 55, 40, status_effect="PSN", status_chance=100),
    _m(141, "Leech Life", "Bug", 20, 100, 15, drain_ratio=0.5),
    _m(142, "Lovely Kiss", "Normal", 0, 75, 10, status_effect="SLP", status_chance=100),
    _m(145, "Bubble", "Water", 20, 100, 30),
    _m(146, "Dizzy Punch", "Normal", 70, 100, 10, status_effect="CONFUSE", status_chance=20),
    _m(147, "Spore", "Grass", 0, 100, 15, status_effect="SLP", status_chance=100),
    _m(148, "Flash", "Normal", 0, 70, 20, target_stat_changes={"acc": -1}),
    _m(150, "Splash", "Normal", 0, 0, 40),
    _m(151, "Acid Armor", "Poison", 0, 0, 40, self_stat_changes={"def": 2}),
    _m(152, "Crabhammer", "Water", 90, 85, 10, high_crit=True),
    _m(153, "Explosion", "Normal", 250, 100, 5, recoil_ratio=1.0),
    _m(154, "Fury Swipes", "Normal", 18, 80, 15, min_hits=2, max_hits=5),
    _m(155, "Bonemerang", "Ground", 50, 90, 10, min_hits=2, max_hits=2),
    _m(157, "Rock Slide", "Rock", 75, 90, 10, status_effect="FLINCH", status_chance=30),
    _m(158, "Hyper Fang", "Normal", 80, 90, 15, status_effect="FLINCH", status_chance=10),
    _m(159, "Sharpen", "Normal", 0, 0, 30, self_stat_changes={"atk": 1}),
    _m(161, "Tri Attack", "Normal", 80, 100, 10, status_effect="PAR", status_chance=20),
    _m(163, "Slash", "Normal", 70, 100, 20, high_crit=True),
    _m(165, "Struggle", "Normal", 50, 0, 1, recoil_ratio=0.25),
    _m(172, "Flame Wheel", "Fire", 60, 100, 25, status_effect="BRN", status_chance=10),
    _m(177, "Aeroblast", "Flying", 100, 95, 5, high_crit=True),
    _m(181, "Powder Snow", "Ice", 40, 100, 25, status_effect="FRZ", status_chance=10),
    _m(183, "Mach Punch", "Fighting", 40, 100, 30, priority=1),
    _m(184, "Scary Face", "Normal", 0, 90, 10, target_stat_changes={"spd": -2}),
    _m(185, "Faint Attack", "Dark", 60, 0, 20),
    _m(186, "Sweet Kiss", "Normal", 0, 75, 10, status_effect="CONFUSE", status_chance=100),
    _m(188, "Sludge Bomb", "Poison", 90, 100, 10, status_effect="PSN", status_chance=30),
    _m(189, "Mud-Slap", "Ground", 20, 100, 10, target_stat_changes={"acc": -1}),
    _m(192, "Zap Cannon", "Electric", 100, 50, 5, status_effect="PAR", status_chance=100),
    _m(196, "Icy Wind", "Ice", 55, 95, 15, target_stat_changes={"spd": -1}),
    _m(198, "Bone Rush", "Ground", 25, 80, 10, min_hits=2, max_hits=5),
    _m(200, "Outrage", "Dragon", 90, 100, 15),
    _m(202, "Giga Drain", "Grass", 60, 100, 5, drain_ratio=0.5),
    _m(204, "Charm", "Normal", 0, 100, 20, target_stat_changes={"atk": -2}),
    _m(209, "Spark", "Electric", 65, 100, 20, status_effect="PAR", status_chance=30),
    _m(210, "Fury Cutter", "Bug", 10, 95, 20),
    _m(211, "Steel Wing", "Steel", 70, 90, 25),
    _m(216, "Return", "Normal", 102, 100, 20),
    _m(221, "Sacred Fire", "Fire", 100, 95, 5, status_effect="BRN", status_chance=50),
    _m(224, "Megahorn", "Bug", 120, 85, 10),
    _m(225, "DragonBreath", "Dragon", 60, 100, 20, status_effect="PAR", status_chance=30),
    _m(231, "Iron Tail", "Steel", 100, 75, 15),
    _m(232, "Metal Claw", "Steel", 50, 95, 35),
    _m(233, "Vital Throw", "Fighting", 70, 0, 10, priority=-1),
    _m(237, "Hidden Power", "Normal", 60, 100, 15),
    _m(238, "Cross Chop", "Fighting", 100, 80, 5, high_crit=True),
    _m(239, "Twister", "Dragon", 40, 100, 20, status_effect="FLINCH", status_chance=20),
    _m(242, "Crunch", "Dark", 80, 100, 15),
    _m(245, "ExtremeSpeed", "Normal", 80, 100, 5, priority=1),
    _m(246, "AncientPower", "Rock", 60, 100, 5),
    _m(247, "Shadow Ball", "Ghost", 80, 100, 15),
    _m(249, "Rock Smash", "Fighting", 20, 100, 15),
    _m(252, "Fake Out", "Normal", 40, 100, 10, priority=1, status_effect="FLINCH", status_chance=100),
    _m(257, "Heat Wave", "Fire", 100, 90, 10, status_effect="BRN", status_chance=10),
    _m(261, "Will-O-Wisp", "Fire", 0, 75, 15, status_effect="BRN", status_chance=100),
    _m(263, "Facade", "Normal", 70, 100, 20),
    _m(279, "Revenge", "Fighting", 60, 100, 10, priority=-4),
    _m(280, "Brick Break", "Fighting", 75, 100, 15),
    _m(282, "Knock Off", "Dark", 20, 100, 20),
    _m(290, "Secret Power", "Normal", 70, 100, 20),
    _m(299, "Blaze Kick", "Fire", 85, 90, 10, high_crit=True, status_effect="BRN", status_chance=10),
    _m(305, "Poison Fang", "Poison", 50, 100, 15, status_effect="TOX", status_chance=30),
    _m(307, "Blast Burn", "Fire", 150, 90, 5),
    _m(308, "Hydro Cannon", "Water", 150, 90, 5),
    _m(314, "Air Cutter", "Flying", 55, 95, 25, high_crit=True),
    _m(315, "Overheat", "Fire", 140, 90, 5, self_stat_changes={"spatk": -2}),
    _m(317, "Rock Tomb", "Rock", 50, 80, 10, target_stat_changes={"spd": -1}),
    _m(318, "Silver Wind", "Bug", 60, 100, 5),
    _m(324, "Signal Beam", "Bug", 75, 100, 15, status_effect="CONFUSE", status_chance=10),
    _m(325, "Shadow Punch", "Ghost", 60, 0, 20),
    _m(328, "Sand Tomb", "Ground", 15, 70, 15),
    _m(331, "Bullet Seed", "Grass", 10, 100, 30, min_hits=2, max_hits=5),
    _m(332, "Aerial Ace", "Flying", 60, 0, 20),
    _m(334, "Iron Defense", "Steel", 0, 0, 15, self_stat_changes={"def": 2}),
    _m(337, "Dragon Claw", "Dragon", 80, 100, 15),
    _m(338, "Frenzy Plant", "Grass", 150, 90, 5),
    _m(339, "Bulk Up", "Fighting", 0, 0, 20, self_stat_changes={"atk": 1, "def": 1}),
    _m(340, "Bounce", "Flying", 85, 85, 5, status_effect="PAR", status_chance=30),
    _m(341, "Mud Shot", "Ground", 55, 95, 15, target_stat_changes={"spd": -1}),
    _m(343, "Covet", "Normal", 40, 100, 40),
    _m(344, "Volt Tackle", "Electric", 120, 100, 15, recoil_ratio=0.33, status_effect="PAR", status_chance=10),
    _m(345, "Magical Leaf", "Grass", 60, 0, 20),
    _m(347, "Calm Mind", "Psychic", 0, 0, 20, self_stat_changes={"spatk": 1, "spdef": 1}),
    _m(348, "Leaf Blade", "Grass", 70, 100, 15, high_crit=True),
    _m(349, "Dragon Dance", "Dragon", 0, 0, 20, self_stat_changes={"atk": 1, "spd": 1}),
    _m(350, "Rock Blast", "Rock", 25, 80, 10, min_hits=2, max_hits=5),
    _m(351, "Shock Wave", "Electric", 60, 0, 20),
    _m(352, "Water Pulse", "Water", 60, 100, 20, status_effect="CONFUSE", status_chance=20),
])


def get_move_data(move_id: int) -> MoveData:
    """Returns Gen 3 MoveData for move_id, or a safe fallback for unmapped moves."""
    if move_id in MOVES_DB:
        return MOVES_DB[move_id]
    return MoveData(move_id=move_id, name=f"Move #{move_id}", move_type="Normal", power=50, accuracy=100, max_pp=20)

