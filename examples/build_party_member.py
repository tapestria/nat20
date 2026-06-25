"""Resolve a CharacterBuildSpec into a combat-ready PartyMemberSpec.

``make_build_spec`` constructs the character contract (species/class/level/
abilities); ``build_party_member`` resolves it against the bundled SRD 5.2
corpus (loaded via ``BundledAssetLoader``) plus a ``CombatInstance`` carrying
the rolled combat stats (hp/ac/initiative/position).
"""

from __future__ import annotations

from dnd5e_srd_data import BundledAssetLoader

from dnd5e_engine import (
    CombatInstance,
    build_party_member,
    cell_id,
    make_build_spec,
)

# The character contract: a level-1 human Fighter with a classic stat array.
build_spec = make_build_spec(
    species_slug="human",
    class_slug="fighter",
    level=1,
    ability_scores={"str": 16, "dex": 12, "con": 14,
                    "int": 10, "wis": 12, "cha": 8},
)

# Combat-instance values that are not character-derived (rolled HP, AC, start cell).
instance = CombatInstance(
    entity_id="char:valeros",
    name="Valeros",
    hp_current=12,
    hp_max=12,
    ac=16,
    initiative=2,
    zone_id=cell_id(0, 0),
)

member = build_party_member(build_spec, instance, loader=BundledAssetLoader())
print(f"{member.name}: level {member.character_level} "
      f"{member.species_slug} {member.class_slug}")
print(f"  HP {member.hp_current}/{member.hp_max}  AC {member.ac}  "
      f"speed {member.base_speed}ft")
print(f"  STR {member.strength} DEX {member.dexterity} CON {member.constitution} "
      f"INT {member.intelligence} WIS {member.wisdom} CHA {member.charisma}")
