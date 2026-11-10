"""Gen 3 Turn-Based PvP Battle Engine Package.

Cleanly separated into:
- type_chart.py: Gen 3 17-type effectiveness matrix & physical/special split.
- pokedex_data.py: Species types mapping for Gen 1-3 Pokémon.
- moves_data.py: Gen 3 move database (type, power, accuracy, PP, status, stat stages).
- items_data.py: Gen 3 in-battle item effects database (potions, status cures, revives, X-items).
- engine.py: Authoritative turn-based battle resolver (damage, crits, STAB, status, switches, items).
"""

from src.battle.engine import BattlePokemon, BattleSession, TurnAction
from src.battle.items_data import BattleItemEffect, get_battle_item_effect
from src.battle.moves_data import MoveData, get_move_data
from src.battle.pokedex_data import get_species_types
from src.battle.type_chart import get_move_category, get_type_multiplier, TYPE_COLORS

__all__ = [
    "BattlePokemon",
    "BattleSession",
    "TurnAction",
    "BattleItemEffect",
    "get_battle_item_effect",
    "MoveData",
    "get_move_data",
    "get_species_types",
    "get_move_category",
    "get_type_multiplier",
    "TYPE_COLORS",
]

