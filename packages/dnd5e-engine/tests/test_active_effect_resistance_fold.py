"""C08-S01 unit — an ACTIVE effect's ``system.traits.dr.value`` change folds
into the per-target ``resistances`` sidecar list.

``orchestrator._fold_active_effect_changes`` gained a top-of-loop branch for
``system.traits.dr.value`` (Rage's activation-gated resistance). Foundry
``mode=2`` on this key means "add the damage-type to the resistance SET" — the
value is a damage-type STRING, so the branch must bypass the numeric ``mode !=
"add"`` guard and the signed-string coercion. This pins the producer seam
directly; the full raged-damage-halving path is covered end to end by
``tests/e2e/test_c08_passive_projection.py::test_c08_s01_...``.
"""

from __future__ import annotations

from dnd5e_engine.orchestrator import _fold_active_effect_changes
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange


def _rage_effect() -> ActiveEffect:
    return ActiveEffect(
        id="effect:rage",
        name="Rage",
        origin="cast:rage:char:hero",
        target_id="char:hero",
        changes=[
            ActiveEffectChange(key="system.traits.dr.value", mode="add", value="bludgeoning"),
            ActiveEffectChange(key="system.traits.dr.value", mode="add", value="piercing"),
            ActiveEffectChange(key="system.traits.dr.value", mode="add", value="slashing"),
            # Rage's resolved melee-damage bonus rides alongside — must still fold.
            ActiveEffectChange(key="system.bonuses.mwak.damage", mode="add", value="+2"),
        ],
    )


def test_dr_value_change_folds_into_resistances_list():
    per_target_dmg: dict = {}
    per_target_entry: dict = {}
    per_target_check: dict = {}
    dirty = _fold_active_effect_changes(
        [_rage_effect()], per_target_dmg, per_target_entry, per_target_check
    )

    assert dirty is True
    assert set(per_target_dmg["resistances"]) == {"bludgeoning", "piercing", "slashing"}
    # The sibling melee-damage bonus is unaffected by the new branch.
    assert per_target_dmg["passive_melee_damage_bonus"] == "2"


def test_dr_value_merges_with_preexisting_resistances_without_duplicating():
    per_target_dmg: dict = {"resistances": ["bludgeoning"]}
    per_target_entry: dict = {}
    per_target_check: dict = {}
    _fold_active_effect_changes(
        [_rage_effect()], per_target_dmg, per_target_entry, per_target_check
    )

    # bludgeoning already present → set-semantics, no duplicate.
    assert per_target_dmg["resistances"].count("bludgeoning") == 1
    assert set(per_target_dmg["resistances"]) == {"bludgeoning", "piercing", "slashing"}
