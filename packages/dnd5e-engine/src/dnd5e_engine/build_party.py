"""Pure resolution of a CharacterBuildSpec into a complete PartyMemberSpec.

Character-derived fields (abilities, class/subclass/level, base_speed) come from the
build-spec + the library; combat-instance fields (hp/ac/initiative/zone/...) come from
CombatInstance. Feature activities (piece 4) and senses/resistances (piece 5) layer on
later via the same seam.
"""

from __future__ import annotations

import logging

from dnd5e_srd_data.loader import AssetLoader
from dnd5e_srd_data.schema.class_ import Class, Subclass
from dnd5e_srd_data.schema.refs import GrantRef
from dnd5e_srd_data.schema.species import Species

from dnd5e_engine.activities.passive_stats import interpret_passive_stats
from dnd5e_engine.build_spec import CharacterBuildSpec, CombatInstance
from dnd5e_engine.specs import PartyMemberSpec

_log = logging.getLogger(__name__)


def granted_feature_slugs(
    sources: list[Class | Subclass | Species | None], *, level: int
) -> list[str]:
    """Pure: feature slugs the given sources grant at/below ``level``.

    Shared by the build-spec passive projection and the orchestrator's
    USE_FEATURE repertoire gate (which derives the same set from a live
    Combatant's class/subclass/species). Filters ``granted_features`` to
    ``ref_type == "feature"`` and ``grant.level <= level``; preserves source
    order and dedupes. ``None`` sources (absent class/subclass/species) are
    skipped. Loader access stays with the caller — this is I/O-free.
    """
    slugs: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source is None:
            continue
        grants: list[GrantRef] = source.granted_features
        for grant in grants:
            if grant.ref_type == "feature" and grant.level <= level and grant.slug not in seen:
                seen.add(grant.slug)
                slugs.append(grant.slug)
    return slugs


def build_party_member(
    build_spec: CharacterBuildSpec, instance: CombatInstance, *, loader: AssetLoader
) -> PartyMemberSpec:
    cls = loader.get_class(build_spec.class_slug)
    if cls is None:
        raise ValueError(f"unknown class: {build_spec.class_slug!r}")
    species = loader.get_species(build_spec.species_slug)
    if species is None:
        raise ValueError(f"unknown species: {build_spec.species_slug!r}")
    sub: Subclass | None = None
    if build_spec.subclass_slug is not None:
        sub = loader.get_subclass(build_spec.subclass_slug)
        if sub is None:
            raise ValueError(f"unknown subclass: {build_spec.subclass_slug!r}")
        if sub.class_identifier != build_spec.class_slug:
            raise ValueError(
                f"subclass {build_spec.subclass_slug!r} is not a subclass of "
                f"{build_spec.class_slug!r}"
            )
    base_speed = species.movement.walk if species.movement.walk else 30
    ab = build_spec.ability_scores

    # Project always-on passive derived stats (species trait_grants/senses +
    # always-on granted-feature passive_effects) onto the spec. The interpreter
    # is pure; this seam owns the loader access and logs the dropped keys.
    feature_slugs = granted_feature_slugs([cls, sub, species], level=build_spec.level)
    feature_changes = []
    for slug in feature_slugs:
        feature = loader.get_feature(slug)
        if feature is None:
            _log.warning(
                "build_party_member: granted feature slug did not resolve to a "
                "canonical feature; skipping",
                extra={"entity_id": instance.entity_id, "granted_feature_slug": slug},
            )
            continue
        for passive in feature.passive_effects:
            # Always-on only: transfer=true innate + not activation-gated.
            if passive.transfer and not passive.disabled:
                feature_changes.extend(passive.changes)
    derived = interpret_passive_stats(
        changes=feature_changes,
        trait_grants=species.trait_grants,
        species_senses=species.senses,
    )
    if derived.skipped_keys:
        _log.debug(
            "build_party_member: skipped non-allowlisted passive keys",
            extra={"entity_id": instance.entity_id, "skipped_keys": derived.skipped_keys},
        )
    return PartyMemberSpec(
        entity_id=instance.entity_id,
        name=instance.name,
        initiative=instance.initiative,
        hp_current=instance.hp_current,
        hp_max=instance.hp_max,
        ac=instance.ac,
        attack_bonus=instance.attack_bonus,
        strength=ab.strength,
        dexterity=ab.dexterity,
        constitution=ab.constitution,
        intelligence=ab.intelligence,
        wisdom=ab.wisdom,
        charisma=ab.charisma,
        zone_id=instance.zone_id,
        spell_slots=dict(instance.spell_slots),
        spells_known=list(instance.spells_known),
        concentration_effect_id=instance.concentration_effect_id,
        character_level=build_spec.level,
        class_slug=build_spec.class_slug,
        subclass_slug=build_spec.subclass_slug,
        species_slug=build_spec.species_slug,
        base_speed=base_speed,
        equipment=build_spec.equipment,
        damage_resistances=list(derived.resistances),
        damage_immunities=list(derived.immunities),
        senses=derived.senses,
    )


__all__ = [
    "build_party_member",
]
