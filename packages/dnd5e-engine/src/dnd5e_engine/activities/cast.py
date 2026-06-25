"""``cast`` kind handler for the Activity resolver.

A Foundry ``CastActivity`` (``cast-data.mjs``) wraps another spell by
``spell.uuid`` — a scroll or wand "casts" a referenced spell. The handler looks
the spell up in ``ctx.spell_book``, builds a CHILD context (propagating the cast
level, the referenced spell's base level / concentration flag / own
``passive_effects``, and a recursion-guard chain), then RE-ENTERS
``resolve_activity`` for each activity on the referenced spell. ``cast`` emits
NOTHING itself — the delegated child activities emit their own events.

MIRRORS, does not import from, ``effects/spell.py`` (the Avrae-IR ``type:
"spell"`` analogue). Reproduces its semantics with the typed lib shapes:

* Spell-within-itself cycle guard FIRST (cheap, before the lookup): a ``uuid``
  already in ``ctx.parent_chain`` logs ``cast_spell_cycle`` and no-ops, never
  recursing infinitely (mirrors ``effects/spell.py``'s ``"spell" in parent_chain``
  guard).
* Spell lookup is a LOUD no-op on a miss — an unresolved ``uuid`` logs
  ``cast_spell_unresolved`` and returns rather than silently skipping.
* Cast-level resolution: ``spell.level`` override when set, else the referenced
  spell's own ``level`` (SRD §Spellcasting — Casting a Spell at a Higher Level:
  "the spell assumes the higher level for that casting").

Scroll DC / attack overrides (``spell.challenge`` with ``override=True``) ARE
honored: 42 canonical cast activities (Dragon Orb DC 18, Circlet of Blasting +5,
…) carry a FIXED save DC or attack bonus. The handler threads the fixed value
into the child context (``save_dc_override`` / ``attack_bonus_override``); the
delegated save/attack handler uses it verbatim instead of the wielder's stats.
Both fields are set unconditionally so a non-override cast clears any inherited
stale value (a grandchild never inherits a parent scroll's DC).
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import CastActivity

    from .context import ActivityResolutionContext

_LOGGER = logging.getLogger(__name__)


def resolve_cast(activity: CastActivity, ctx: ActivityResolutionContext) -> None:
    """Delegate a ``cast`` activity to its referenced spell's activities."""
    uuid = activity.spell.uuid
    # 1. Cycle guard FIRST (cheap, before lookup).
    if uuid in ctx.parent_chain:
        _LOGGER.warning("cast_spell_cycle uuid=%s chain=%s", uuid, ctx.parent_chain)
        return
    # 2. Lookup (loud no-op on miss — never silently skip).
    spell = ctx.spell_book.get(uuid)
    if spell is None:
        _LOGGER.warning("cast_spell_unresolved uuid=%s", uuid)
        return
    # 3. Cast-level resolution + bounds (SRD §Casting a Spell at a Higher Level;
    #    mirrors effects/spell.py's ``base_level <= cast_level <= 9`` invariant).
    #    A cantrip's base level is 0 (``0 <= 0 <= 9`` passes). An out-of-range
    #    cast (e.g. a scroll forged at level 10, or below the spell's base) is a
    #    LOUD no-op — never an absurd upcast (cure-wounds at level 10 → 20d8).
    cast_level = activity.spell.level if activity.spell.level is not None else spell.level
    if not (spell.level <= cast_level <= 9):
        _LOGGER.warning(
            "cast_invalid_level uuid=%s cast_level=%s base_level=%s",
            uuid,
            cast_level,
            spell.level,
        )
        return
    # 4. Build the child context and delegate. ``spell.ability`` is the ability
    #    the wrapper casts the referenced spell with (a scroll/wand may force
    #    e.g. "wis"); Foundry stores "" to mean "use the caster's default", so a
    #    non-empty value overrides and an empty value inherits the parent's.
    #
    #    A fixed item challenge (``spell.challenge.override``) threads a verbatim
    #    save DC / attack bonus into the child so the delegated save/attack handler
    #    uses the item's number, not the wielder's stats (Dragon Orb DC 18, Circlet
    #    of Blasting +5). Both are set UNCONDITIONALLY: an override is honored for
    #    THIS wrapper, and a non-override cast CLEARS any inherited stale value so a
    #    grandchild never inherits a parent scroll's DC.
    from .resolver import resolve_activity  # function-local: breaks the resolver↔cast import cycle

    challenge = activity.spell.challenge
    child_ctx = dataclasses.replace(
        ctx,
        spellcasting_ability=activity.spell.ability or ctx.spellcasting_ability,
        slot_level=cast_level,
        base_spell_level=spell.level,
        concentration=spell.concentration,
        source_passive_effects=spell.passive_effects,
        save_dc_override=(challenge.save if challenge.override else None),
        attack_bonus_override=(challenge.attack if challenge.override else None),
        parent_chain=(*ctx.parent_chain, uuid),
    )
    for child_activity in spell.activities:
        resolve_activity(child_activity, child_ctx)
