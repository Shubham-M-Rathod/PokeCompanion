"""Generation 3 In-Battle Item Effects Database.

Maps Gen 3 item IDs (from src.core.items) to their battle effects:
HP restoration, status cures, revives, stat stages, and PP recovery.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional


@dataclass(frozen=True)
class BattleItemEffect:
    item_id: int
    name: str
    description: str
    heal_hp: int = 0
    full_hp: bool = False
    cures_statuses: FrozenSet[str] = field(default_factory=frozenset)  # e.g. {"PAR"}, {"ALL"}
    cures_confusion: bool = False
    revive_ratio: float = 0.0                                          # 0.5 for Revive, 1.0 for Max Revive
    stat_boosts: Dict[str, int] = field(default_factory=dict)          # e.g. {"atk": 1} for X Attack
    restore_pp: int = 0                                                # 10 for Ether, 999 for Max Ether
    restore_all_moves: bool = False                                    # True for Elixir / Max Elixir


ALL_STATUSES = frozenset({"PAR", "BRN", "PSN", "TOX", "SLP", "FRZ"})


BATTLE_ITEMS_DB: Dict[int, BattleItemEffect] = {
    # HP Healing
    0x000D: BattleItemEffect(0x000D, "Potion", "Restores 20 HP.", heal_hp=20),
    0x0016: BattleItemEffect(0x0016, "Super Potion", "Restores 50 HP.", heal_hp=50),
    0x0015: BattleItemEffect(0x0015, "Hyper Potion", "Restores 200 HP.", heal_hp=200),
    0x0014: BattleItemEffect(0x0014, "Max Potion", "Fully restores HP.", full_hp=True),
    0x0013: BattleItemEffect(
        0x0013,
        "Full Restore",
        "Fully restores HP and cures all status problems.",
        full_hp=True,
        cures_statuses=ALL_STATUSES,
        cures_confusion=True,
    ),
    0x001A: BattleItemEffect(0x001A, "Fresh Water", "Restores 50 HP.", heal_hp=50),
    0x001B: BattleItemEffect(0x001B, "Soda Pop", "Restores 60 HP.", heal_hp=60),
    0x001C: BattleItemEffect(0x001C, "Lemonade", "Restores 80 HP.", heal_hp=80),
    0x001D: BattleItemEffect(0x001D, "Moomoo Milk", "Restores 100 HP.", heal_hp=100),
    0x001E: BattleItemEffect(0x001E, "EnergyPowder", "Restores 50 HP.", heal_hp=50),
    0x001F: BattleItemEffect(0x001F, "Energy Root", "Restores 200 HP.", heal_hp=200),
    0x002C: BattleItemEffect(0x002C, "Berry Juice", "Restores 20 HP.", heal_hp=20),

    # Status Cures
    0x000E: BattleItemEffect(0x000E, "Antidote", "Cures Poison.", cures_statuses=frozenset({"PSN", "TOX"})),
    0x000F: BattleItemEffect(0x000F, "Burn Heal", "Cures Burn.", cures_statuses=frozenset({"BRN"})),
    0x0010: BattleItemEffect(0x0010, "Ice Heal", "Cures Freeze.", cures_statuses=frozenset({"FRZ"})),
    0x0011: BattleItemEffect(0x0011, "Awakening", "Wakes up a sleeping Pokémon.", cures_statuses=frozenset({"SLP"})),
    0x0012: BattleItemEffect(0x0012, "Parlyz Heal", "Cures Paralysis.", cures_statuses=frozenset({"PAR"})),
    0x0017: BattleItemEffect(
        0x0017, "Full Heal", "Cures all status problems.", cures_statuses=ALL_STATUSES, cures_confusion=True
    ),
    0x0020: BattleItemEffect(
        0x0020, "Heal Powder", "Cures all status problems.", cures_statuses=ALL_STATUSES, cures_confusion=True
    ),
    0x0026: BattleItemEffect(
        0x0026, "Lava Cookie", "Cures all status problems.", cures_statuses=ALL_STATUSES, cures_confusion=True
    ),

    # Revives
    0x0018: BattleItemEffect(0x0018, "Revive", "Revives a fainted Pokémon with half HP.", revive_ratio=0.5),
    0x0019: BattleItemEffect(0x0019, "Max Revive", "Revives a fainted Pokémon with full HP.", revive_ratio=1.0),

    # PP Restoration
    0x0022: BattleItemEffect(0x0022, "Ether", "Restores 10 PP to all moves.", restore_pp=10, restore_all_moves=True),
    0x0023: BattleItemEffect(0x0023, "Max Ether", "Fully restores PP.", restore_pp=999, restore_all_moves=True),
    0x0024: BattleItemEffect(0x0024, "Elixir", "Restores 10 PP to all moves.", restore_pp=10, restore_all_moves=True),
    0x0025: BattleItemEffect(0x0025, "Max Elixir", "Fully restores PP to all moves.", restore_pp=999, restore_all_moves=True),

    # X Stat Boosters (Active Pokémon)
    0x004B: BattleItemEffect(0x004B, "X Attack", "Raises Attack by 1 stage.", stat_boosts={"atk": 1}),
    0x004C: BattleItemEffect(0x004C, "X Defend", "Raises Defense by 1 stage.", stat_boosts={"def": 1}),
    0x004D: BattleItemEffect(0x004D, "X Speed", "Raises Speed by 1 stage.", stat_boosts={"spd": 1}),
    0x004E: BattleItemEffect(0x004E, "X Accuracy", "Raises Accuracy by 1 stage.", stat_boosts={"acc": 1}),
    0x004F: BattleItemEffect(0x004F, "X Special", "Raises Sp. Atk by 1 stage.", stat_boosts={"spatk": 1}),
}


def get_battle_item_effect(item_id: int) -> Optional[BattleItemEffect]:
    """Returns BattleItemEffect if usable in battle, otherwise None."""
    return BATTLE_ITEMS_DB.get(item_id)

