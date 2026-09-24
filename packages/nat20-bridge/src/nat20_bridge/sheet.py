"""Character-sheet derivation for the bridge: a build-spec + loader → a
combat-ready ``PartyMemberSpec``.

A thin wrapper over the engine: ``build_party_member`` derives HP, AC, speed,
proficiencies and spell slots through ``dnd5e_engine.derive_sheet``. The bridge
only checks the requested spell list and supplies the combat identity (name,
id, start cell, initiative).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dnd5e_engine import CombatInstance, build_party_member

if TYPE_CHECKING:
    from dnd5e_engine import CharacterBuildSpec, PartyMemberSpec
    from dnd5e_srd_data.loader import AssetLoader


def derive_sheet(
    spec: CharacterBuildSpec,
    *,
    name: str,
    entity_id: str,
    loader: AssetLoader,
    hp_current: int | None = None,
    spells_known: list[str] | None = None,
    zone_id: str = "0,0",
    initiative: int = 0,
) -> PartyMemberSpec:
    known = list(spells_known or [])
    for slug in known:
        if loader.get_spell(slug) is None:
            raise ValueError(f"unknown spell: {slug!r}")
    instance = CombatInstance(
        entity_id=entity_id,
        name=name,
        hp_current=hp_current,
        initiative=initiative,
        zone_id=zone_id,
        spells_known=tuple(known),
    )
    return build_party_member(spec, instance, loader=loader)


__all__ = ["derive_sheet"]
