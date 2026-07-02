"""SRD 5.2 damage-type corrections (translator override map).

Upstream Foundry raw sources ship ``types: []`` for a handful of spell damage
parts even though each spell's own SRD 5.2 description names the damage type
(the description text IS the rules ground truth). The translator applies a
documented correction map (see
``tools.translators.foundry._SPELL_DAMAGE_TYPE_CORRECTIONS``); these tests pin
both the corrected canonical output AND the description text that grounds each
correction, so upstream description drift makes the pin fail loudly.
"""

from __future__ import annotations

from dnd5e_srd_data import BundledAssetLoader
from dnd5e_srd_data.schema.common import (
    DamagePartBlock,
    SaveActivity,
    SaveDamageBlock,
)
from tools.translators.foundry import _apply_spell_damage_type_corrections


def _activity(spell, activity_id: str):
    matches = [a for a in spell.activities if a.id == activity_id]
    assert len(matches) == 1, f"expected exactly one activity {activity_id!r}"
    return matches[0]


# ---------------------------------------------------------------------------
# Canonical output: the three SRD-corrected spells.
# ---------------------------------------------------------------------------


def test_call_lightning_repeat_bolt_is_lightning_typed():
    """Call Lightning's repeat-bolt 4d10 damage activity: upstream ships
    ``types: []``, but the spell's description says "taking 3d10 Lightning
    damage on a failed save ... you can take a Magic action to call down
    lightning in that way again"."""
    loader = BundledAssetLoader()
    spell = loader.get_spell("call-lightning")
    assert spell is not None
    assert "Lightning damage" in spell.description  # grounding pin
    repeat = _activity(spell, "dnd5eactivity200")
    assert repeat.kind == "damage"
    part = repeat.damage.parts[0]
    assert part.number == 4
    assert part.denomination == 10
    assert part.types == ["lightning"]
    # The initial 3d10 bolt was already correctly typed upstream; unchanged.
    initial = _activity(spell, "dnd5eactivity000")
    assert initial.damage.parts[0].types == ["lightning"]


def test_freezing_sphere_both_10d6_parts_are_cold_typed():
    """Freezing Sphere's "Cast and Fire" and "Throw Held Globe" save
    activities: upstream ships ``types: []`` on both 10d6 parts, but the
    description says "taking 10d6 Cold damage on failed save" (and the thrown
    globe "shatters on impact, with the same effect as a normal casting")."""
    loader = BundledAssetLoader()
    spell = loader.get_spell("freezing-sphere")
    assert spell is not None
    assert "Cold damage" in spell.description  # grounding pin
    for activity_id in ("adCBWrctRmLQmb8M", "NKBsnjBBIgsaOPaY"):
        act = _activity(spell, activity_id)
        assert act.kind == "save"
        part = act.damage.parts[0]
        assert part.number == 10
        assert part.denomination == 6
        assert part.types == ["cold"], f"{activity_id} must be cold-typed"


def test_meld_into_stone_flat_50_is_force_typed():
    """Meld into Stone's flat-50 expulsion damage: upstream ships
    ``types: []`` on the custom "50" part, but the description tags BOTH
    expulsion damage instances force — "deals [[/damage 6d6 type=force]]" and
    "deals [[/damage 50 type=force]]". (SRD 5.2 changed this from 5.1's
    bludgeoning.)"""
    loader = BundledAssetLoader()
    spell = loader.get_spell("meld-into-stone")
    assert spell is not None
    assert "[[/damage 50 type=force]]" in spell.description  # grounding pin
    flat = _activity(spell, "dnd5eactivity200")
    assert flat.kind == "damage"
    part = flat.damage.parts[0]
    assert part.custom.enabled is True
    assert part.custom.formula == "50"
    assert part.types == ["force"]
    # The 6d6 partial-destruction sibling was already force-typed upstream.
    dice = _activity(spell, "dnd5eactivity000")
    assert dice.damage.parts[0].types == ["force"]


# ---------------------------------------------------------------------------
# Override-map semantics (pure unit tests of the translator helper).
# ---------------------------------------------------------------------------


def _save_activity(activity_id: str, part: DamagePartBlock) -> SaveActivity:
    return SaveActivity(_id=activity_id, damage=SaveDamageBlock(parts=[part]))


def test_correction_fills_only_the_mapped_untyped_part():
    act = _save_activity("adCBWrctRmLQmb8M", DamagePartBlock(number=10, denomination=6))
    (out,) = _apply_spell_damage_type_corrections("freezing-sphere", [act])
    assert out.damage.parts[0].types == ["cold"]


def test_correction_is_a_no_op_for_unmapped_slugs_and_activities():
    act = _save_activity("someOtherActivity", DamagePartBlock(number=2, denomination=8))
    (out,) = _apply_spell_damage_type_corrections("freezing-sphere", [act])
    assert out is act
    (out,) = _apply_spell_damage_type_corrections(
        "fireball", [_save_activity("adCBWrctRmLQmb8M", DamagePartBlock())]
    )
    assert out.damage.parts[0].types == []


def test_correction_self_retires_when_upstream_gains_a_type():
    """If a future Foundry pin ships a real type for a mapped part, the
    correction must NOT overwrite it — upstream wins and the map entry goes
    inert (to be deleted at the next pin bump)."""
    act = _save_activity(
        "adCBWrctRmLQmb8M",
        DamagePartBlock(number=10, denomination=6, types=["fire"]),
    )
    (out,) = _apply_spell_damage_type_corrections("freezing-sphere", [act])
    assert out.damage.parts[0].types == ["fire"]
