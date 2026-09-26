"""Foundry roll-data substitution for Activity dice / DC formula strings.

Canonical activities carry Foundry roll-data tokens (``@mod``, ``@prof``, ...) in
their dice/DC formula fields — e.g. Cure Wounds' healing bonus is verbatim
``@mod``, and a monster save DC is ``"8 + @mod + @prof"``. ``d20.parse`` cannot
read these tokens, so each one is replaced with its caster-derived integer (as a
string) before the dice helper parses the formula.

MIRRORS, does not import from, the old the legacy path's
``intent_resolver._walk_and_patch`` / ``_parse_with_injection``: that path
injected the same caster magnitudes (ability mods, proficiency, spell DC) into
formula strings before rolling. The caster's numbers live on
``ActivityResolutionContext``; the typed Activity only declares WHICH
ability/DC-calc applies.

Scope — the roll-data tokens that appear in canonical DICE/DC FORMULA fields
(``damage.parts[].bonus``/``custom.formula``, ``healing.*``, ``attack`` bonus,
``save.dc.formula``), surveyed across the 1285-file canonical corpus:

* ``@mod`` — the governing ability modifier; the caller passes ``ability`` (the
  spell's/weapon's ability, or the caster's spellcasting ability).
* ``@prof`` — the caster proficiency bonus.
* ``@abilities.<abil>.mod`` — a specific ability modifier.
* ``@attributes.spell.mod`` — the spellcasting-ability modifier.
* ``@attributes.spell.dc`` — the caster spell save DC (``8 + prof + spell mod``).
* ``@skills.<code>.passive`` — the caster's passive score for a Foundry
  3-letter skill code (a stat-block on-hit trait DC, e.g. the Crocodile's
  Bite: "the target ... has the Grappled condition (escape DC 12)", Foundry's
  ``[[lookup @skills.ath.passive]]``): ``10 + ability mod + Proficiency Bonus
  (doubled with Expertise) when the caster is proficient``.

``@scaling`` resolves only when the context carries ``scaling_value`` — a
feature activity whose own-pool cost scales by amount (Lay on Hands' Heal).
Spell upcasting stays with ``dice.py``'s ``DamageScalingBlock`` path; a spell
formula that names ``@scaling`` still reaches the unknown-token guard below.

Any other ``@``-token reaching this resolver is out of scope for Piece 1: rather
than leave it (``d20.parse`` would fail to parse and the failure site would be
opaque), we log ``roll_data_token_unhandled`` at WARNING and raise ``ValueError``
so the gap is loud and discoverable.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Final

from dnd5e_engine.activities.actor_stats import skill_ability
from dnd5e_engine.rules.skills import SKILL_CODE_TO_SLUG

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import DamagePartBlock

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)

# A Foundry roll-data token: ``@`` followed by dot-separated identifier segments.
# Segments allow hyphens so ScaleValue keys (``@scale.barbarian.rage-damage``,
# ``@scale.rogue.sneak-attack.number``) tokenize as a single match.
_TOKEN_RE: Final = re.compile(r"@[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*")

# Literal tokens with no embedded ability segment.
_TOKEN_PROF: Final = "@prof"
_TOKEN_MOD: Final = "@mod"
_TOKEN_SPELL_MOD: Final = "@attributes.spell.mod"
_TOKEN_SPELL_DC: Final = "@attributes.spell.dc"
_TOKEN_SCALING: Final = "@scaling"

# ``@abilities.<abil>.mod`` — capture the three-letter ability key.
_ABILITY_MOD_RE: Final = re.compile(r"^@abilities\.([a-z]{3})\.mod$")

# ``@scale.<owner>.<key>[.<suffix>]`` — capture the full dotted suffix after
# ``@scale.`` (the carrier key, e.g. ``barbarian.rage-damage`` or
# ``rogue.sneak-attack.number``).
_SCALE_PREFIX: Final = "@scale."
# ``@classes.<class>.levels`` — capture the class slug (Second Wind's heal).
_CLASS_LEVELS_RE: Final = re.compile(r"^@classes\.([a-z0-9-]+)\.levels$")

# ``@skills.<code>.passive`` — capture the Foundry 3-letter skill code.
_SKILL_PASSIVE_RE: Final = re.compile(r"^@skills\.([a-z]{3})\.passive$")


def resolve_roll_data(
    expr: str,
    ctx: ActivityResolutionContext,
    *,
    ability: str | None = None,
) -> str:
    """Replace Foundry roll-data tokens in ``expr`` with caster-derived integers.

    ``ability`` is the governing ability for a bare ``@mod`` (the spell's/weapon's
    ability, or the caster's spellcasting ability) — required only when ``@mod``
    is present. The returned string is ``d20``-parseable; negative modifiers
    render as e.g. ``"2d8 + -1"``, which ``d20.parse`` accepts.
    """
    resolved = _TOKEN_RE.sub(lambda m: str(_resolve_token(m.group(0), ctx, ability)), expr)
    return _normalize_paren_dice_count(resolved)


# Foundry wraps a scale-valued dice COUNT in parens — ``(@scale.x)d8`` (Divine
# Spark's ``(@scale.channel-divinity-cleric.spark)d8``). After token
# substitution that leaves ``(1)d8``, which ``d20.parse`` rejects (a
# parenthesized group may not be a dice count). Collapse a paren-wrapped bare
# integer immediately preceding ``d<size>`` back to a plain ``NdM``.
_PAREN_DICE_COUNT_RE: Final = re.compile(r"\((\d+)\)(d\d)")


def _normalize_paren_dice_count(expr: str) -> str:
    return _PAREN_DICE_COUNT_RE.sub(r"\1\2", expr)


def resolve_damage_block(
    block: DamagePartBlock,
    ctx: ActivityResolutionContext,
    *,
    ability: str | None = None,
) -> DamagePartBlock:
    """Return a copy of ``block`` with roll-data tokens resolved in its formulas.

    Substitutes ``@``-tokens in the block's ``bonus``, (when its custom branch is
    active) ``custom.formula``, and its ``scaling.formula`` so
    ``dice.roll_damage_part`` sees ``d20``-parseable formulas. The block's dice
    ``number``/``denomination`` and the scaling step *count* stay owned by
    ``dice.py``; only the scaling *formula* string is token-resolved here.
    """
    updates: dict[str, object] = {}

    new_bonus = resolve_roll_data(block.bonus, ctx, ability=ability) if block.bonus else block.bonus
    if new_bonus != block.bonus:
        updates["bonus"] = new_bonus

    if block.custom.enabled and block.custom.formula:
        resolved_formula = resolve_roll_data(block.custom.formula, ctx, ability=ability)
        if resolved_formula != block.custom.formula:
            updates["custom"] = block.custom.model_copy(update={"formula": resolved_formula})

    if block.scaling.formula:
        resolved_scaling = resolve_roll_data(block.scaling.formula, ctx, ability=ability)
        if resolved_scaling != block.scaling.formula:
            updates["scaling"] = block.scaling.model_copy(update={"formula": resolved_scaling})

    return block.model_copy(update=updates) if updates else block


def _resolve_token(token: str, ctx: ActivityResolutionContext, ability: str | None) -> int | str:
    if token == _TOKEN_PROF:
        return ctx.caster_proficiency_bonus
    if token == _TOKEN_MOD:
        if ability is None:
            raise ValueError(
                f"@mod requires a governing ability but none was supplied for {token!r}"
            )
        return ctx.ability_mod(ability)
    if token == _TOKEN_SPELL_MOD:
        return ctx.ability_mod(_spellcasting_ability(ctx, token))
    if token == _TOKEN_SPELL_DC:
        return 8 + ctx.caster_proficiency_bonus + ctx.ability_mod(_spellcasting_ability(ctx, token))

    ability_match = _ABILITY_MOD_RE.match(token)
    if ability_match is not None:
        return ctx.ability_mod(ability_match.group(1))

    if token.startswith(_SCALE_PREFIX):
        # Pre-resolved carrier lookup (no loader I/O here — purity). The key is
        # the full dotted suffix. Int (number/distance/count) substitutes into
        # the arithmetic; a dice-expr STRING substitutes verbatim into the
        # formula string before ``d20.parse`` (it cannot be an int token).
        key = token[len(_SCALE_PREFIX) :]
        value = ctx.scale_values.get(key)
        if value is None:
            _LOGGER.warning("roll_data_scale_unresolved token=%s", token)
            raise ValueError(f"Unresolved @scale token (absent from carrier): {token!r}")
        return value

    if token == _TOKEN_SCALING and ctx.scaling_value is not None:
        return ctx.scaling_value

    class_levels_match = _CLASS_LEVELS_RE.match(token)
    if class_levels_match is not None:
        class_slug = class_levels_match.group(1)
        level = ctx.class_levels.get(class_slug)
        if level is None:
            _LOGGER.warning("roll_data_scale_unresolved token=%s", token)
            raise ValueError(f"Unresolved @classes levels token (absent from carrier): {token!r}")
        return level

    skill_match = _SKILL_PASSIVE_RE.match(token)
    if skill_match is not None:
        return _resolve_skill_passive(skill_match.group(1), ctx, token)

    _LOGGER.warning("roll_data_token_unhandled token=%s", token)
    raise ValueError(f"Unhandled roll-data token: {token!r}")


def _resolve_skill_passive(code: str, ctx: ActivityResolutionContext, token: str) -> int:
    """SRD 5.2 passive skill score for the caster: ``10 + ability modifier +
    Proficiency Bonus (doubled with Expertise) when proficient`` — a
    stat-block on-hit trait's own DC (the Crocodile's Bite: "escape DC"
    equal to its passive Athletics). ``ctx.ability_mod``/
    ``ctx.caster_proficiency_bonus`` already read the acting stat block (the
    caster's own, or its form's under a transform, C21), and
    ``ctx.caster.skill_proficiencies``/``.skill_expertise`` are kept in step
    with it the same way (``orchestrator._apply_transform``).
    """
    slug = SKILL_CODE_TO_SLUG.get(code)
    ability = skill_ability(slug) if slug is not None else None
    if slug is None or ability is None:
        _LOGGER.warning("roll_data_skill_unhandled token=%s", token)
        raise ValueError(f"Unresolved @skills passive token (unknown skill code): {token!r}")
    proficient = slug in ctx.caster.skill_proficiencies
    expertise = proficient and slug in ctx.caster.skill_expertise
    prof = ctx.caster_proficiency_bonus * (2 if expertise else 1) if proficient else 0
    return 10 + ctx.ability_mod(ability) + prof


def _spellcasting_ability(ctx: ActivityResolutionContext, token: str) -> str:
    spellcasting = ctx.spellcasting_ability
    if spellcasting is None:
        raise ValueError(f"{token!r} requires a spellcasting ability but the caster has none")
    return spellcasting
