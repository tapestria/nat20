"""Which of an item's activities an intent fires, and what that costs.

SRD 5.2 §Making an Attack: an attack with a weapon is a swing — it fires the
weapon's attack and the riders the hit itself triggers, never a magic item
property the wielder activates (a Trident of Fish Command's Dominate Beast,
a Mace of Terror's Wave of Terror). Those are a ``use_item``'s, which spends
their charge.
"""

from __future__ import annotations

from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader, OverlayAssetLoader
from dnd5e_srd_data.schema.common import (
    ActivationBlock,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
)

from dnd5e_engine.events import AttackRolled, SaveRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from tests.c20_support import act, events, pc, start

SRD = BundledAssetLoader()


def _with_homebrew(*items: Any) -> None:
    set_lib_loader_for_tests(OverlayAssetLoader(base=SRD, overlay=MemoryAssetLoader(items=items)))


def _save(activation: str) -> SaveActivity:
    return SaveActivity(
        id="save0000000000aa",
        activation=ActivationBlock(type=activation),
        save=SaveBlock(ability=["con"], dc=SaveDcBlock(formula="15")),
        damage=SaveDamageBlock(on_save="half", parts=[]),
        effects=[],
        applied_effects=[],
    )


def _spear_with(slug: str, extra: SaveActivity) -> Any:
    spear = SRD.get_weapon("spear")
    assert spear is not None
    return spear.model_copy(update={"slug": slug, "activities": [*spear.activities, extra]})


# ── an attack fires the swing, not the weapon's activated properties ─────────


def test_a_swing_never_fires_a_save_the_wielder_activates() -> None:
    _with_homebrew(_spear_with("storm-spear", _save("action")))
    handle, live = start([pc()], seed=1)
    act(handle, "char:hero", intent_type="attack", weapon_id="storm-spear", target_id="mon:foe")
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:foe"]
    assert events(live, SaveRolled) == []


def test_a_swing_still_fires_a_rider_the_hit_triggers() -> None:
    """An activity with no activation of its own is not the wielder's to
    choose: it rides the swing (a Mace of Disruption's save, a Sword of
    Wounding's)."""
    _with_homebrew(_spear_with("storm-spear", _save("")))
    handle, live = start([pc()], seed=1)
    act(handle, "char:hero", intent_type="attack", weapon_id="storm-spear", target_id="mon:foe")
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:foe"]
    assert [e.target_id for e in events(live, SaveRolled)] == ["mon:foe"]


def test_a_mace_of_disruption_swing_still_forces_its_save() -> None:
    handle, live = start([pc(equipment=("mace-of-disruption",))], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="mace-of-disruption",
        target_id="mon:foe",
    )
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:foe"]
    assert [e.target_id for e in events(live, SaveRolled)] == ["mon:foe"]


def test_a_trident_of_fish_command_swing_casts_nothing_and_spends_no_charge() -> None:
    handle, live = start([pc(equipment=("trident-of-fish-command",))], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="attack",
        weapon_id="trident-of-fish-command",
        target_id="mon:foe",
    )
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:foe"]
    # The trident's Topple mastery may still force its Constitution save.
    assert [e.ability for e in events(live, SaveRolled)] in ([], ["con"])
    assert not any(e.type == "effect_applied" for e in live.event_log)
    spent = live.custom_counters_by_entity.get("char:hero", {}).get(
        "item_use:trident-of-fish-command"
    )
    assert spent in (None, {"spent": 0})


def test_using_a_trident_of_fish_command_casts_its_spell_and_spends_a_charge() -> None:
    """SRD 5.2 Trident of Fish Command: "you can expend 1 charge to cast
    Dominate Beast (save DC 15) from it" — a use of the item, not a swing."""
    handle, live = start([pc(equipment=("trident-of-fish-command",))], seed=1)
    act(
        handle,
        "char:hero",
        intent_type="use_item",
        item_id="trident-of-fish-command",
        target_id="mon:foe",
    )
    assert events(live, AttackRolled) == []
    saves = events(live, SaveRolled)
    assert [(e.target_id, e.dc) for e in saves] == [("mon:foe", 15)]
    assert live.custom_counters_by_entity["char:hero"]["item_use:trident-of-fish-command"] == {
        "spent": 1
    }
