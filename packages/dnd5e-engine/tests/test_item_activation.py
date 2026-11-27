"""Which of an item's activities an intent fires, and what that costs.

SRD 5.2 §Making an Attack: an attack with a weapon is a swing — it fires the
weapon's attack and the riders the hit itself triggers, never a magic item
property the wielder activates (a Trident of Fish Command's Dominate Beast,
a Mace of Terror's Wave of Terror). Those are a ``use_item``'s, which spends
their charge.

SRD 5.2 §Bonus Actions: "You can take a Bonus Action only when a special
ability, a spell, or another feature of the game states that you can do
something as a Bonus Action", and you get one per turn — a Potion of Healing
is drunk as a Bonus Action, so it leaves the turn's Action for an attack.
"""

from __future__ import annotations

from typing import Any

from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader, OverlayAssetLoader
from dnd5e_srd_data.schema.common import (
    ActivationBlock,
    ConsumptionBlock,
    ConsumptionTargetEntry,
    DamagePartBlock,
    HealActivity,
    RangeBlock,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
)
from dnd5e_srd_data.schema.item import ItemUses

from dnd5e_engine.events import AttackRolled, CastFailed, HealingApplied, SaveRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _current_actor
from tests.c20_support import act, combatant, events, foe, pc, start

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


def _draught(activation: str, *, uses: str = "1") -> Any:
    """A one-activity healing draught, activated as ``activation``."""
    base = SRD.get_item("pipes-of-haunting")
    assert base is not None
    heal = HealActivity(
        id="heal0000000000aa",
        activation=ActivationBlock(type=activation),
        healing=DamagePartBlock(number=2, denomination=4, bonus="2", types=["healing"]),
        range=RangeBlock(units="self"),
        consumption=ConsumptionBlock(targets=[ConsumptionTargetEntry(type="itemUses", value="1")]),
    )
    return base.model_copy(
        update={
            "slug": "draught",
            "passive_effects": [],
            "uses": ItemUses(max=uses, auto_destroy=uses == "1", recovery=[]),
            "activities": [heal],
        }
    )


def _hurt_hero() -> Any:
    return pc(hp_current=5, hp_max=40)


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


# ── a Bonus Action item keeps the turn ───────────────────────────────────────


def test_a_bonus_action_item_keeps_the_turn_and_leaves_the_action() -> None:
    _with_homebrew(_draught("bonus"))
    handle, live = start([_hurt_hero()], seed=1)
    act(handle, "char:hero", intent_type="use_item", item_id="draught", target_id="char:hero")
    assert [e.target_id for e in events(live, HealingApplied)] == ["char:hero"]
    hero = combatant(live)
    assert _current_actor(live).entity_id == "char:hero"
    assert hero.bonus_action_available is False
    assert hero.action_available is True
    act(handle, "char:hero", intent_type="attack", weapon_id="spear", target_id="mon:foe")
    assert [e.target_id for e in events(live, AttackRolled)] == ["mon:foe"]


def test_a_second_bonus_action_item_in_one_turn_is_refused() -> None:
    _with_homebrew(_draught("bonus", uses="2"))
    handle, live = start([_hurt_hero()], seed=1)
    act(handle, "char:hero", intent_type="use_item", item_id="draught", target_id="char:hero")
    act(handle, "char:hero", intent_type="use_item", item_id="draught", target_id="char:hero")
    assert [e.reason for e in events(live, CastFailed)] == ["no_action_economy"]
    assert len(events(live, HealingApplied)) == 1
    assert live.custom_counters_by_entity["char:hero"]["item_use:draught"] == {"spent": 1}
    assert _current_actor(live).entity_id == "char:hero"


def test_an_action_item_still_ends_the_turn() -> None:
    _with_homebrew(_draught("action"))
    handle, live = start([_hurt_hero()], seed=1)
    act(handle, "char:hero", intent_type="use_item", item_id="draught", target_id="char:hero")
    assert [e.target_id for e in events(live, HealingApplied)] == ["char:hero"]
    assert _current_actor(live).entity_id == "mon:foe"


def test_drinking_a_potion_of_healing_keeps_the_turn() -> None:
    handle, live = start([_hurt_hero()], seed=1, encounter=[foe()])
    act(
        handle,
        "char:hero",
        intent_type="use_item",
        item_id="potion-of-healing",
        target_id="char:hero",
    )
    assert [e.target_id for e in events(live, HealingApplied)] == ["char:hero"]
    assert _current_actor(live).entity_id == "char:hero"
    assert combatant(live).action_available is True
