"""Pure interpreter for always-on passive derived stats.

Maps the **allowlisted** Foundry dotted change-keys (``system.traits.dr.value``,
``system.attributes.senses.*``) and species ``trait_grants`` tokens
(``dr:<type>`` / ``di:<type>``) into a typed :class:`DerivedPassiveStats`
(resistances, immunities, senses). The ``build_party_member`` seam calls this
with the PC's always-on feature changes + species data and projects the result
onto the spec.

Also projects ``condition_immunities`` (``system.traits.ci.value``, C08-S02)
and movement (``system.attributes.movement.*``, C08-S04 — a flat
``walk_speed_bonus`` plus a typed :class:`CombatantMovementModes` carrier).

PURITY CONTRACT: zero I/O, zero logging, never raises. Allowlist misses,
deferred keys (languages, ``ac.calc``, ability/proficiency grants), and
non-literal values are collected into ``skipped_keys`` so the calling seam can
log them — the interpreter itself has no side effects.
"""

from __future__ import annotations

from collections.abc import Sequence

from dnd5e_srd_data.schema.common import PassiveEffectChange, Senses
from pydantic import BaseModel, ConfigDict

# Foundry CONST.ACTIVE_EFFECT_MODES values the senses allowlist honors.
_MODE_ADD = 2
_MODE_UPGRADE = 4  # "max" semantics

# Allowlisted senses change-key suffixes → CombatantSenses field name.
_SENSE_KEYS = {
    "system.attributes.senses.darkvision": "darkvision",
    "system.attributes.senses.blindsight": "blindsight",
    "system.attributes.senses.tremorsense": "tremorsense",
    "system.attributes.senses.truesight": "truesight",
}
_DR_KEY = "system.traits.dr.value"
_DI_KEY = "system.traits.di.value"
_CI_KEY = "system.traits.ci.value"

# SRD §Movement (C08-S04). The flat walk-speed change folds into a scalar bonus
# (composed with the species base_speed at the build seam); the non-walk modes
# land on the typed :class:`CombatantMovementModes` carrier. Foundry's symbolic
# ``@attributes.movement.walk`` token (Roving's "equal to your Speed") resolves
# to the boosted walk speed — the single formula token this seam handles (no
# general formula engine).
_MOVE_WALK_KEY = "system.attributes.movement.walk"
_MOVE_MODE_KEYS = {
    "system.attributes.movement.climb": "climb",
    "system.attributes.movement.swim": "swim",
    "system.attributes.movement.fly": "fly",
    "system.attributes.movement.burrow": "burrow",
}
_MOVE_WALK_TOKEN = "@attributes.movement.walk"

# Foundry's condition-immunity (``ci``) trait uses the damage-type-style token
# ``"poison"`` for the Poisoned condition; every other SRD condition's ``ci``
# token already equals its condition slug. Normalize the sole irregular token
# so the projected ``condition_immunities`` holds condition slugs the
# ConditionApplied emit-gate compares directly (C08-S02). A single-entry alias,
# deliberately not a general trait-vocabulary engine.
_CI_TOKEN_TO_CONDITION = {"poison": "poisoned"}


class CombatantSenses(BaseModel):
    """A creature's special senses in feet (lib ``Senses`` minus
    passive_perception). ``None`` = sense unavailable. Carried on the spec and
    the live ``Combatant``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    darkvision: int | None = None
    blindsight: int | None = None
    tremorsense: int | None = None
    truesight: int | None = None


class CombatantMovementModes(BaseModel):
    """A creature's non-walk movement speeds in feet (SRD §Movement). ``None`` =
    that mode unavailable. Mirrors :class:`CombatantSenses`'s shape; carried on
    the spec and the live ``Combatant`` alongside the scalar walk ``base_speed``.
    Kept multi-mode (not collapsed to one scalar — collapsing is lossy: a
    creature may have distinct climb / swim / fly / burrow speeds)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    climb: int | None = None
    swim: int | None = None
    fly: int | None = None
    burrow: int | None = None


class DerivedPassiveStats(BaseModel):
    """Typed output of :func:`interpret_passive_stats` — the always-on passive
    deltas to project onto a PC's spec at combat-build time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resistances: tuple[str, ...] = ()
    immunities: tuple[str, ...] = ()
    # SRD §Condition Immunity — condition slugs the creature can't suffer
    # (Nature's Ward → ``"poisoned"``). ci trait tokens are normalized to
    # condition slugs before landing here (see ``_CI_TOKEN_TO_CONDITION``).
    condition_immunities: tuple[str, ...] = ()
    senses: CombatantSenses = CombatantSenses()
    # SRD §Movement — flat walk-speed bonus (Roving's +10) the build seam adds
    # to the species base_speed; and the typed non-walk modes carrier.
    walk_speed_bonus: int = 0
    movement_modes: CombatantMovementModes = CombatantMovementModes()
    skipped_keys: tuple[str, ...] = ()


def _parse_literal_int(value: str) -> int | None:
    """Return the int if ``value`` is a plain numeric literal, else ``None``.

    Defends against symbolic Foundry values (``@scale.*`` formulas) reaching a
    numeric field. Quote-escaping (``"\"60\""``) is stripped before parsing.
    """
    cleaned = value.strip().strip('"').strip()
    try:
        return int(cleaned)
    except ValueError:
        return None


def _resolve_movement_modes(
    mode_changes: Sequence[tuple[str, str, int]],
    *,
    resolved_walk: int,
    skipped: list[str],
) -> dict[str, int]:
    """Fold buffered non-walk movement changes into a ``{field: speed}`` dict.

    The symbolic ``@attributes.movement.walk`` token resolves to ``resolved_walk``
    (the boosted walk speed); any other symbolic value, or an unmodeled mode, is
    appended to ``skipped``. Mode 4 = max (upgrade), mode 2 = additive.
    """
    move_values: dict[str, int] = {}
    for field, raw_value, mode in mode_changes:
        if raw_value.strip() == _MOVE_WALK_TOKEN:
            literal: int | None = resolved_walk
        else:
            literal = _parse_literal_int(raw_value)
        if literal is None:
            skipped.append(f"system.attributes.movement.{field}")
            continue
        current = move_values.get(field)
        if mode == _MODE_UPGRADE:
            move_values[field] = literal if current is None else max(current, literal)
        elif mode == _MODE_ADD:
            move_values[field] = literal if current is None else current + literal
        else:
            skipped.append(f"system.attributes.movement.{field}")
    return move_values


def interpret_passive_stats(
    *,
    changes: Sequence[PassiveEffectChange],
    trait_grants: Sequence[str],
    species_senses: Senses | None,
    species_base_speed: int = 30,
) -> DerivedPassiveStats:
    """Interpret always-on passive changes + species data into typed deltas.

    ``species_base_speed`` is the creature's unmodified walking speed (feet); the
    symbolic ``@attributes.movement.walk`` token on a non-walk mode resolves
    against the *boosted* walk speed (``species_base_speed + walk_speed_bonus``,
    C08-S04).

    PURE: no I/O, no logging, never raises. Unknown / deferred keys and
    non-literal numeric values are returned in ``skipped_keys``.
    """
    resistances: list[str] = []
    immunities: list[str] = []
    condition_immunities: list[str] = []
    skipped: list[str] = []
    sense_values: dict[str, int] = {}
    # Flat additive walk-speed bonus (Roving's +10). Non-walk mode changes are
    # buffered and resolved *after* the loop, once walk_speed_bonus is known, so
    # a ``@attributes.movement.walk`` token sees the boosted speed.
    walk_speed_bonus = 0
    mode_changes: list[tuple[str, str, int]] = []

    # Species trait_grants: dr:<t> -> resistance, di:<t> -> immunity,
    # anything else (ci:, languages:, ...) -> skipped (deferred / out of scope).
    for token in trait_grants:
        prefix, _, rest = token.partition(":")
        if prefix == "dr" and rest:
            resistances.append(rest)
        elif prefix == "di" and rest:
            immunities.append(rest)
        else:
            skipped.append(token)

    for change in changes:
        key = change.key
        if key == _DR_KEY:
            resistances.append(change.value.strip().strip('"').strip())
        elif key == _DI_KEY:
            immunities.append(change.value.strip().strip('"').strip())
        elif key == _CI_KEY:
            token = change.value.strip().strip('"').strip()
            if token:
                condition_immunities.append(_CI_TOKEN_TO_CONDITION.get(token, token))
        elif key in _SENSE_KEYS:
            literal = _parse_literal_int(change.value)
            if literal is None:
                skipped.append(key)
                continue
            field = _SENSE_KEYS[key]
            current = sense_values.get(field)
            if change.mode == _MODE_UPGRADE:
                sense_values[field] = literal if current is None else max(current, literal)
            elif change.mode == _MODE_ADD:
                sense_values[field] = literal if current is None else current + literal
            else:
                # other modes (override/multiply/downgrade/custom) not modeled
                skipped.append(key)
        elif key == _MOVE_WALK_KEY:
            # Flat walk-speed change (Roving's +10). Only the additive mode is
            # modeled; a literal int folds into walk_speed_bonus, anything else
            # (symbolic / non-add mode) is deferred.
            literal = _parse_literal_int(change.value)
            if literal is not None and change.mode == _MODE_ADD:
                walk_speed_bonus += literal
            else:
                skipped.append(key)
        elif key in _MOVE_MODE_KEYS:
            # Non-walk mode (climb/swim/fly/burrow); resolved after the loop.
            mode_changes.append((_MOVE_MODE_KEYS[key], change.value, change.mode))
        else:
            # Any non-allowlisted key (ci, bonuses, hp, ...) -> deferred.
            skipped.append(key)

    # Merge species senses by max (mode-4 / upgrade semantics).
    if species_senses is not None:
        for field in ("darkvision", "blindsight", "tremorsense", "truesight"):
            species_value = getattr(species_senses, field)
            if species_value is None:
                continue
            current = sense_values.get(field)
            sense_values[field] = species_value if current is None else max(current, species_value)

    # Resolve non-walk movement modes now that walk_speed_bonus is settled. The
    # symbolic ``@attributes.movement.walk`` token ("equal to your Speed")
    # resolves to the boosted walk speed; any other symbolic value is deferred.
    move_values = _resolve_movement_modes(
        mode_changes, resolved_walk=species_base_speed + walk_speed_bonus, skipped=skipped
    )

    return DerivedPassiveStats(
        resistances=tuple(resistances),
        immunities=tuple(immunities),
        condition_immunities=tuple(condition_immunities),
        senses=CombatantSenses(**sense_values),
        walk_speed_bonus=walk_speed_bonus,
        movement_modes=CombatantMovementModes(**move_values),
        skipped_keys=tuple(skipped),
    )
