"""Generation 3 (FireRed / Emerald) 17-Type Chart and Physical/Special Split.

Key Gen 3 rules:
- 17 types exist (no Fairy type).
- Steel resists Ghost (0.5x) and Dark (0.5x) in Gen 3.
- Physical vs Special category for damaging moves is strictly determined by MOVE TYPE.
"""

from typing import Dict, Iterable, Tuple

PHYSICAL_TYPES = frozenset({
    "Normal", "Fighting", "Flying", "Poison", "Ground",
    "Rock", "Bug", "Ghost", "Steel",
})

SPECIAL_TYPES = frozenset({
    "Fire", "Water", "Grass", "Electric", "Psychic",
    "Ice", "Dragon", "Dark",
})

# Hex colors for UI type badges
TYPE_COLORS: Dict[str, str] = {
    "Normal": "#A8A77A",
    "Fire": "#EE8130",
    "Water": "#6390F0",
    "Electric": "#F7D02C",
    "Grass": "#7AC74C",
    "Ice": "#96D9D6",
    "Fighting": "#C22E28",
    "Poison": "#A33EA1",
    "Ground": "#E2BF65",
    "Flying": "#A98FF3",
    "Psychic": "#F95587",
    "Bug": "#A6B91A",
    "Rock": "#B6A136",
    "Ghost": "#735797",
    "Dragon": "#6F35FC",
    "Dark": "#705746",
    "Steel": "#B7B7CE",
}

# AttackingType -> {DefendingType: multiplier} (only non-1.0 entries listed)
GEN3_TYPE_CHART: Dict[str, Dict[str, float]] = {
    "Normal": {"Rock": 0.5, "Ghost": 0.0, "Steel": 0.5},
    "Fire": {
        "Fire": 0.5, "Water": 0.5, "Grass": 2.0, "Ice": 2.0,
        "Bug": 2.0, "Rock": 0.5, "Dragon": 0.5, "Steel": 2.0,
    },
    "Water": {
        "Fire": 2.0, "Water": 0.5, "Grass": 0.5, "Ground": 2.0,
        "Rock": 2.0, "Dragon": 0.5,
    },
    "Electric": {
        "Water": 2.0, "Grass": 0.5, "Electric": 0.5, "Ground": 0.0,
        "Flying": 2.0, "Dragon": 0.5,
    },
    "Grass": {
        "Fire": 0.5, "Water": 2.0, "Grass": 0.5, "Poison": 0.5,
        "Ground": 2.0, "Flying": 0.5, "Bug": 0.5, "Rock": 2.0,
        "Dragon": 0.5, "Steel": 0.5,
    },
    "Ice": {
        "Fire": 0.5, "Water": 0.5, "Grass": 2.0, "Ice": 0.5,
        "Ground": 2.0, "Flying": 2.0, "Dragon": 2.0, "Steel": 0.5,
    },
    "Fighting": {
        "Normal": 2.0, "Ice": 2.0, "Poison": 0.5, "Flying": 0.5,
        "Psychic": 0.5, "Bug": 0.5, "Rock": 2.0, "Ghost": 0.0,
        "Dark": 2.0, "Steel": 2.0,
    },
    "Poison": {
        "Grass": 2.0, "Poison": 0.5, "Ground": 0.5, "Rock": 0.5,
        "Ghost": 0.5, "Steel": 0.0,
    },
    "Ground": {
        "Fire": 2.0, "Grass": 0.5, "Electric": 2.0, "Poison": 2.0,
        "Flying": 0.0, "Bug": 0.5, "Rock": 2.0, "Steel": 2.0,
    },
    "Flying": {
        "Grass": 2.0, "Electric": 0.5, "Fighting": 2.0, "Bug": 2.0,
        "Rock": 0.5, "Steel": 0.5,
    },
    "Psychic": {
        "Fighting": 2.0, "Poison": 2.0, "Psychic": 0.5,
        "Dark": 0.0, "Steel": 0.5,
    },
    "Bug": {
        "Fire": 0.5, "Grass": 2.0, "Fighting": 0.5, "Poison": 0.5,
        "Flying": 0.5, "Psychic": 2.0, "Ghost": 0.5, "Dark": 2.0,
        "Steel": 0.5,
    },
    "Rock": {
        "Fire": 2.0, "Ice": 2.0, "Fighting": 0.5, "Ground": 0.5,
        "Flying": 2.0, "Bug": 2.0, "Steel": 0.5,
    },
    "Ghost": {
        "Normal": 0.0, "Psychic": 2.0, "Ghost": 2.0,
        "Dark": 0.5, "Steel": 0.5,
    },
    "Dragon": {"Dragon": 2.0, "Steel": 0.5},
    "Dark": {
        "Fighting": 0.5, "Psychic": 2.0, "Ghost": 2.0,
        "Dark": 0.5, "Steel": 0.5,
    },
    "Steel": {
        "Fire": 0.5, "Water": 0.5, "Electric": 0.5, "Ice": 2.0,
        "Rock": 2.0, "Steel": 0.5,
    },
}


def get_move_category(move_type: str, power: int) -> str:
    """Returns 'Status', 'Physical', or 'Special' using Gen 3 type-based split."""
    if power <= 0:
        return "Status"
    if move_type in SPECIAL_TYPES:
        return "Special"
    return "Physical"


def get_type_multiplier(move_type: str, defender_types: Iterable[str]) -> float:
    """Computes combined effectiveness multiplier (0.0, 0.25, 0.5, 1.0, 2.0, 4.0)."""
    row = GEN3_TYPE_CHART.get(move_type, {})
    mult = 1.0
    for def_type in defender_types:
        if def_type:
            mult *= row.get(def_type, 1.0)
    return mult


def get_effectiveness_message(multiplier: float, target_name: str) -> str:
    """Returns the classic GBA battle text for a type effectiveness multiplier."""
    if multiplier == 0.0:
        return f"It doesn't affect {target_name}..."
    if multiplier > 1.0:
        return "It's super effective!"
    if multiplier < 1.0:
        return "It's not very effective..."
    return ""

