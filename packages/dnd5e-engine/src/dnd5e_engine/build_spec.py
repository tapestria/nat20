"""The build-spec contract: the typed input that resolves into a complete PC.

A 7c test/seed factory produces these now; the char-creation build-core (CharacterDraft,
spec-only today) becomes a second producer of the identical contract later. Resolution
(build_party_member) is pure; selection (who fills the build-spec) is the producer's job.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from dnd5e_srd_data.loader import AssetLoader
from pydantic import BaseModel, ConfigDict, Field, model_validator

from dnd5e_engine.spellcasting import (
    SpellcastingProgression,
    derive_pact_slots,
    derive_spell_slots,
    multiclass_caster_level,
    slots_for_caster_level,
)

# Long-form -> the canonical field; short-form aliases the backend cache / lib may pass.
_ABILITY_ALIASES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
_LONG = set(_ABILITY_ALIASES.values())


class AbilityScores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10


class CharacterBuildSpec(BaseModel):
    """The typed input that resolves into a complete PC.

    C17: ``classes`` is the multiclass carrier (spec §3) — a ``{class_slug: level}``
    map. ``class_slug`` (= the FIRST key, the primary class) and ``level`` (= the SUM
    of class levels) are kept as single-class aliases and always populated, so
    existing single-class callers (``CharacterBuildSpec(class_slug=..., level=...)``)
    keep working exactly as before.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    species_slug: str
    class_slug: str = ""
    classes: dict[str, int] = Field(default_factory=dict)
    subclass_slug: str | None = None
    level: int = Field(ge=1, le=20, default=1)
    ability_scores: AbilityScores = Field(default_factory=AbilityScores)
    equipment: tuple[str, ...] = ()
    selected_choices: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _reconcile_classes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        classes = dict(data.get("classes") or {})
        class_slug = data.get("class_slug")
        level = data.get("level")
        if classes:
            for slug, lvl in classes.items():
                if not isinstance(lvl, int) or lvl < 1:
                    raise ValueError(
                        f"class level for {slug!r} must be a positive int, got {lvl!r}"
                    )
            total = sum(classes.values())
            primary = next(iter(classes))
            if class_slug and class_slug not in classes:
                raise ValueError(
                    f"class_slug {class_slug!r} is not one of classes {sorted(classes)}"
                )
            if level is not None and level != total:
                raise ValueError(f"level {level} does not equal the sum of classes ({total})")
            data["class_slug"] = class_slug or primary
            data["level"] = total
            data["classes"] = classes
        elif class_slug:
            data["classes"] = {class_slug: level if level is not None else 1}
        else:
            raise ValueError("CharacterBuildSpec needs class_slug or classes")
        return data


class CombatInstance(BaseModel):
    """Combat-instance values that are NOT character-derived.

    Entity identity (entity_id/name) + rolled/looked-up combat stats.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    name: str
    hp_current: int
    hp_max: int
    ac: int = 10
    attack_bonus: int = 0
    initiative: int = 0
    zone_id: str = ""
    concentration_effect_id: str | None = None
    spell_slots: dict[int, int] = Field(default_factory=dict)
    # SRD Pact Magic — the Warlock's separately-recovering slot pool
    # ``{slot_level: count_remaining}``; consumed by the orchestrator in C17 Task 3.
    pact_slots: dict[int, int] = Field(default_factory=dict)
    spells_known: tuple[str, ...] = ()


def _normalize_abilities(raw: dict[str, int]) -> AbilityScores:
    out: dict[str, int] = {}
    for k, v in raw.items():
        key = _ABILITY_ALIASES.get(k, k)
        if key not in _LONG:
            raise ValueError(f"unknown ability key: {k!r}")
        out[key] = int(v)
    return AbilityScores(**out)


def make_build_spec(
    *,
    species_slug: str,
    class_slug: str | None = None,
    level: int | None = None,
    classes: Mapping[str, int] | None = None,
    subclass_slug: str | None = None,
    ability_scores: dict[str, int] | None = None,
    equipment: tuple[str, ...] = (),
    selected_choices: tuple[str, ...] = (),
) -> CharacterBuildSpec:
    payload: dict[str, Any] = {
        "species_slug": species_slug,
        "subclass_slug": subclass_slug,
        "ability_scores": _normalize_abilities(ability_scores or {}),
        "equipment": equipment,
        "selected_choices": selected_choices,
    }
    if classes:
        payload["classes"] = dict(classes)
    if class_slug is not None:
        payload["class_slug"] = class_slug
    if level is not None:
        payload["level"] = level
    return CharacterBuildSpec(**payload)


def _progressions(
    classes: Mapping[str, int], loader: AssetLoader
) -> dict[str, tuple[SpellcastingProgression, int]]:
    out: dict[str, tuple[SpellcastingProgression, int]] = {}
    for slug, lvl in classes.items():
        cls = loader.get_class(slug)
        if cls is None:
            raise ValueError(f"unknown class: {slug!r}")
        out[slug] = (cast(SpellcastingProgression, str(cls.spellcasting.progression)), lvl)
    return out


def derive_multiclass_slots(
    classes: Mapping[str, int], *, loader: AssetLoader | None = None
) -> dict[int, int]:
    """Multiclass Spellcasting-feature slots for a ``{class_slug: level}`` map.

    Reads each class's ``spellcasting.progression`` through ``loader`` (default:
    the configured lib loader), applies the SRD per-class rounding (R2) and looks
    the total up in the Multiclass Spellcaster table. A single-class map returns
    exactly ``derive_spell_slots(...)`` for that class.
    """
    if loader is None:
        from dnd5e_engine.lib_loader import get_lib_loader

        loader = get_lib_loader()
    return slots_for_caster_level(multiclass_caster_level(_progressions(classes, loader)))


def derive_multiclass_pact_slots(
    classes: Mapping[str, int], *, loader: AssetLoader | None = None
) -> dict[int, int]:
    """Pact Magic pool for the ``pact``-progression class levels in ``classes`` (``{}`` if none)."""
    if loader is None:
        from dnd5e_engine.lib_loader import get_lib_loader

        loader = get_lib_loader()
    pact_levels = [lvl for prog, lvl in _progressions(classes, loader).values() if prog == "pact"]
    return derive_pact_slots(sum(pact_levels)) if pact_levels else {}


__all__ = [
    "AbilityScores",
    "CharacterBuildSpec",
    "CombatInstance",
    "derive_multiclass_pact_slots",
    "derive_multiclass_slots",
    "derive_spell_slots",
    "make_build_spec",
]
