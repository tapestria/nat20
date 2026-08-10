"""Task 1 (cast-delegation plan): ``ActivityResolutionContext.cast_level_override``.

A variable-charge item invocation (a wand upcast) needs to force ``resolve_cast``
to a cast level the wrapper activity's own ``spell.level`` does not carry (the
use_item charge gate computes it as ``base activity level + extra charges``).
``cast_level_override`` is the seam: when set, ``resolve_cast`` uses it verbatim
(still bounds-checked against ``spell.level <= cast_level <= 9``) instead of the
wrapper's ``activity.spell.level`` / the referenced spell's own ``level``.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import CastActivity

from dnd5e_engine.activities.cast import resolve_cast
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.dice import roll_expr
from dnd5e_engine.events import CombatEvent, DamageApplied
from dnd5e_engine.types.combat import Combatant

L = BundledAssetLoader()


def _caster() -> Combatant:
    return Combatant(
        entity_id="char:aaaaaaaaaaaa",
        entity_type="Character",
        name="PC",
        initiative=10,
        hp_current=20,
        attack_bonus=5,
        character_level=5,
        dexterity=14,
    )


def _target() -> Combatant:
    return Combatant(
        entity_id="mon:bbbbbbbbbbbb",
        entity_type="Monster",
        name="Cultist",
        initiative=8,
        hp_current=100,
        attack_bonus=3,
        character_level=1,
        dexterity=12,
    )


def _make_ctx(emitted: list[CombatEvent], **kw: object) -> ActivityResolutionContext:
    """Mirrors the ``_ctx`` helper in ``tests/test_scale_resolver.py``."""
    params: dict[str, object] = dict(
        rng=random.Random(1),
        caster=_caster(),
        targets=[_target()],
        event_emitter=emitted.append,
        caster_abilities={a: 10 for a in ("str", "dex", "con", "int", "wis", "cha")},
        caster_proficiency_bonus=3,
    )
    params.update(kw)
    return ActivityResolutionContext(**params)  # type: ignore[arg-type]


def test_cast_level_override_upcasts_delegated_spell() -> None:
    spell = L.get_spell("lightning-bolt")
    item = L.get_item("wand-of-lightning-bolts")
    assert item is not None
    cast_activity = next(a for a in item.activities if isinstance(a, CastActivity))

    emitted: list[CombatEvent] = []
    ctx = _make_ctx(
        emitted,
        spell_book={cast_activity.spell.uuid: spell},
        cast_level_override=5,
        rng=random.Random(7),
    )
    # The item's cast wrapper fixes the save DC at 15 (challenge.override=True);
    # forcing the FIRST target's natural d20 to 1 (dex mod +0 on the default
    # ability spread) guarantees a FAILED save, so damage lands at full — this
    # isolates the assertion to the upcast dice count, never the on_save halving.
    ctx.variables["force_save_d20"] = 1

    resolve_cast(cast_activity, ctx)

    damage_events = [e for e in emitted if isinstance(e, DamageApplied)]
    assert damage_events, "delegated cast resolved no damage"

    # Lightning Bolt: 8d6 base at its own level 3, `scaling.mode="whole"` /
    # `scaling.number=1` adds +1d6 per cast level above base -> 10d6 at cast
    # level 5. `damage.py` draws the parts off `ctx.rng` through the SAME
    # `dice.roll_expr` primitive; replaying "10d6" against an identically-seeded
    # RNG reproduces the exact total the resolver rolled. A level-3 cast (no
    # override) would instead consume "8d6" off the same seed stream and land on
    # a different total, so an equality match here pins the upcast to 10d6
    # specifically, not merely "some damage happened".
    expected_10d6 = roll_expr("10d6", random.Random(7))
    assert damage_events[0].amount == expected_10d6


def test_cast_level_override_below_base_is_rejected() -> None:
    spell = L.get_spell("lightning-bolt")
    item = L.get_item("wand-of-lightning-bolts")
    assert item is not None
    cast_activity = next(a for a in item.activities if isinstance(a, CastActivity))

    emitted: list[CombatEvent] = []
    ctx = _make_ctx(
        emitted,
        spell_book={cast_activity.spell.uuid: spell},
        cast_level_override=1,  # below the spell's base level (3)
        rng=random.Random(7),
    )
    ctx.variables["force_save_d20"] = 1

    resolve_cast(cast_activity, ctx)

    # cast_invalid_level rejection path: no resolution events of any kind.
    assert emitted == []
