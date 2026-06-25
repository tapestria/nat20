"""Pure interpreter for always-on passive derived stats.

Maps the **allowlisted** Foundry dotted change-keys (``system.traits.dr.value``,
``system.attributes.senses.*``) and species ``trait_grants`` tokens
(``dr:<type>`` / ``di:<type>``) into a typed :class:`DerivedPassiveStats`
(resistances, immunities, senses). The ``build_party_member`` seam calls this
with the PC's always-on feature changes + species data and projects the result
onto the spec.

PURITY CONTRACT: zero I/O, zero logging, never raises. Allowlist misses,
deferred keys (movement, ci, languages), and non-literal values are collected
into ``skipped_keys`` so the calling seam can log them — the interpreter itself
has no side effects. Movement (``system.attributes.movement.*``) and
``condition_immunities`` (``ci``) are DEFERRED: recognized as deferred and
routed to ``skipped_keys``, never projected.
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


class CombatantSenses(BaseModel):
    """A creature's special senses in feet (lib ``Senses`` minus
    passive_perception). ``None`` = sense unavailable. Carried on the spec and
    the live ``Combatant``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    darkvision: int | None = None
    blindsight: int | None = None
    tremorsense: int | None = None
    truesight: int | None = None


class DerivedPassiveStats(BaseModel):
    """Typed output of :func:`interpret_passive_stats` — the always-on passive
    deltas to project onto a PC's spec at combat-build time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resistances: tuple[str, ...] = ()
    immunities: tuple[str, ...] = ()
    senses: CombatantSenses = CombatantSenses()
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


def interpret_passive_stats(
    *,
    changes: Sequence[PassiveEffectChange],
    trait_grants: Sequence[str],
    species_senses: Senses | None,
) -> DerivedPassiveStats:
    """Interpret always-on passive changes + species data into typed deltas.

    PURE: no I/O, no logging, never raises. Unknown / deferred keys and
    non-literal numeric values are returned in ``skipped_keys``.
    """
    resistances: list[str] = []
    immunities: list[str] = []
    skipped: list[str] = []
    sense_values: dict[str, int] = {}

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
        else:
            # Any non-allowlisted key (movement, ci, bonuses, hp, ...) -> deferred.
            skipped.append(key)

    # Merge species senses by max (mode-4 / upgrade semantics).
    if species_senses is not None:
        for field in ("darkvision", "blindsight", "tremorsense", "truesight"):
            species_value = getattr(species_senses, field)
            if species_value is None:
                continue
            current = sense_values.get(field)
            sense_values[field] = species_value if current is None else max(current, species_value)

    return DerivedPassiveStats(
        resistances=tuple(resistances),
        immunities=tuple(immunities),
        senses=CombatantSenses(**sense_values),
        skipped_keys=tuple(skipped),
    )
