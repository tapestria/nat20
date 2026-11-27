"""An item's own ``save`` activity: its DC and its effect riders.

SRD 5.2 Pipes of Haunting: "Each creature of your choice within 30 feet of you
must succeed on a DC 15 Wisdom saving throw or have the Frightened condition
for 1 minute." A magic item prints its own save DC; Foundry ships it as an empty
``save.dc.calculation`` with a flat ``save.dc.formula``. An adventuring item
such as Acid ships an ability calculation instead (SRD 5.2 Acid: "DC 8 plus
your Dexterity modifier and Proficiency Bonus"). Neither is the user's spell
save DC; that DC belongs to a spell, including one an item casts without a
fixed challenge DC.

The rider an item's save activity names (``effects[].id``) points into the
item's own ``passive_effects``. Foundry per-effect semantics: a ref applies on
a failed save, and on a successful one only when its ``on_save`` is set.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader
from dnd5e_srd_data.schema.common import (
    AppliedEffectRef,
    PassiveEffect,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
)

from dnd5e_engine.events import ConditionApplied, EffectApplied, EffectExpired, SaveRolled
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from tests.c20_support import act, events, foe, monster_turn, pc, start, wizard

_SRD = BundledAssetLoader()
_HERO = "char:hero"
_FOE = "mon:foe"
_EFFECT_ID = "itemrider0000001"


@pytest.fixture(autouse=True)
def _reset_lib_loader() -> Iterator[None]:
    yield
    set_lib_loader_for_tests(None)


def _save(dc: str, *, on_save: bool | None = None, rider: bool = False) -> SaveActivity:
    return SaveActivity(
        id="itemsave00000001",
        save=SaveBlock(ability=["con"], dc=SaveDcBlock(formula=dc)),
        damage=SaveDamageBlock(on_save="half", parts=[]),
        effects=[AppliedEffectRef(id=_EFFECT_ID, on_save=on_save)] if rider else [],
    )


def _rider() -> PassiveEffect:
    return PassiveEffect(
        id=_EFFECT_ID,
        name="Poisoned",
        statuses=["poisoned"],
        duration={"rounds": 3},
        transfer=False,
    )


def _homebrew(slug: str, activity: SaveActivity, *, passive: list[PassiveEffect]):
    base = _SRD.get_item("pipes-of-haunting")
    assert base is not None
    return base.model_copy(
        update={"slug": slug, "uses": None, "activities": [activity], "passive_effects": passive}
    )


def _load(*items) -> None:
    poisoned = _SRD.get_condition("poisoned")
    assert poisoned is not None
    set_lib_loader_for_tests(MemoryAssetLoader(items=list(items), conditions=[poisoned]))


def _use(handle, item_id: str, **intent) -> None:
    act(handle, _HERO, intent_type="use_item", item_id=item_id, target_id=_FOE, **intent)


# ── the save DC ──────────────────────────────────────────────────────────────


def test_an_items_flat_save_dc_is_its_own() -> None:
    _load(_homebrew("dc-rod", _save("15"), passive=[]))
    handle, live = start([pc()], seed=1)
    _use(handle, "dc-rod")
    assert [s.dc for s in events(live, SaveRolled)] == [15]


def test_pipes_of_haunting_rolls_against_its_printed_dc() -> None:
    handle, live = start([pc()], seed=1)
    _use(handle, "pipes-of-haunting")
    assert [s.dc for s in events(live, SaveRolled)] == [15]


def test_an_items_ability_save_dc_uses_the_users_ability_and_proficiency() -> None:
    """Acid at character level 5 (PB +3) with DEX 18 (+4): DC 8 + 4 + 3."""
    handle, live = start([pc(character_level=5, dexterity=18)], seed=1)
    _use(handle, "acid")
    assert [s.dc for s in events(live, SaveRolled)] == [15]


def test_an_item_cast_without_a_fixed_dc_keeps_the_users_spell_dc() -> None:
    """Hat of Many Spells' Fireball names no challenge DC, so the delegated
    spell's ``spellcasting`` DC is the user's (no spellcasting class here:
    8 + 2 + the attack-bonus-derived modifier 4)."""
    handle, live = start([pc(attack_bonus=6)], seed=1)
    _use(handle, "hat-of-many-spells", activity_id="1Oov0JtLLqUAI5g2")
    saves = events(live, SaveRolled)
    assert saves
    assert {s.dc for s in saves} == {14}


def test_a_spell_save_keeps_the_casters_spell_dc() -> None:
    """A Wizard 5 with INT 20 casts Hold Person at DC 8 + 3 + 5."""
    handle, live = start([wizard(initiative=25)], seed=1)
    act(
        handle,
        "char:wiz",
        intent_type="cast_spell",
        spell_id="hold-person",
        target_id=_FOE,
        slot_level=2,
    )
    assert [s.dc for s in events(live, SaveRolled)] == [16]


# ── the effect rider ─────────────────────────────────────────────────────────


def _rider_events(live) -> list[ConditionApplied]:
    return [e for e in events(live, ConditionApplied) if e.target_id == _FOE]


def test_an_items_rider_lands_on_a_failed_save() -> None:
    _load(_homebrew("censer", _save("30", rider=True), passive=[_rider()]))
    handle, live = start([pc()], seed=1)
    _use(handle, "censer")
    [save] = events(live, SaveRolled)
    assert not save.succeeded
    assert [(e.target_id, e.condition) for e in _rider_events(live)] == [(_FOE, "poisoned")]
    assert "poisoned" in live.active_conditions[_FOE]
    [applied] = events(live, EffectApplied)
    assert applied.effect.duration.rounds == 3


def test_an_items_rider_skips_a_successful_save() -> None:
    _load(_homebrew("censer", _save("1", rider=True), passive=[_rider()]))
    handle, live = start([pc()], seed=5)
    _use(handle, "censer")
    [save] = events(live, SaveRolled)
    assert save.succeeded
    assert _rider_events(live) == []
    assert "poisoned" not in live.active_conditions.get(_FOE, set())


def test_an_on_save_rider_lands_even_on_a_successful_save() -> None:
    _load(_homebrew("censer", _save("1", on_save=True, rider=True), passive=[_rider()]))
    handle, live = start([pc()], seed=5)
    _use(handle, "censer")
    [save] = events(live, SaveRolled)
    assert save.succeeded
    assert [e.condition for e in _rider_events(live)] == ["poisoned"]


def test_an_items_rider_expires_after_its_rounds() -> None:
    """The rider's three rounds count down at its user's turn ends, the turn
    it landed in included, so the foe is still poisoned through its own next
    two turns and free once the user's third turn ends."""
    _load(_homebrew("censer", _save("30", rider=True), passive=[_rider()]))
    handle, live = start([pc()], seed=1)
    _use(handle, "censer")
    for _ in range(2):
        monster_turn(handle)
        assert "poisoned" in live.active_conditions[_FOE]
        act(handle, _HERO, intent_type="pass")
    assert "poisoned" not in live.active_conditions.get(_FOE, set())
    assert [e.target_id for e in events(live, EffectExpired)] == [_FOE]


def test_a_non_transfer_item_effect_never_reaches_its_holder() -> None:
    _load(_homebrew("censer", _save("30", rider=True), passive=[_rider()]))
    handle, live = start([pc()], seed=1)
    assert _HERO not in live.active_effects
    _use(handle, "censer")
    assert all(e.effect.target_id == _FOE for e in events(live, EffectApplied))
    assert not live.active_effects.get(_HERO)
    assert "poisoned" not in live.active_conditions.get(_HERO, set())


def test_pipes_of_haunting_frighten_on_a_failed_save() -> None:
    handle, live = start([pc()], seed=1, encounter=[foe()])
    _use(handle, "pipes-of-haunting")
    [save] = events(live, SaveRolled)
    assert not save.succeeded
    assert [e.condition for e in _rider_events(live)] == ["frightened"]


def test_an_item_cast_still_applies_the_spells_own_rider() -> None:
    """Staff of Power's Hold Monster is a delegated cast: its Paralyzed rider
    lives on the spell, not on the staff."""
    staff = _SRD.get_item("staff-of-power")
    assert staff is not None
    [hold_monster] = [
        a for a in staff.activities if a.kind == "cast" and "HoldMonste" in a.spell.uuid
    ]
    handle, live = start([pc()], seed=1)
    _use(handle, "staff-of-power", activity_id=hold_monster.id)
    [save] = events(live, SaveRolled)
    assert not save.succeeded
    assert [e.condition for e in _rider_events(live)] == ["paralyzed"]
