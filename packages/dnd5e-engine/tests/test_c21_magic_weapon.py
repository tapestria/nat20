"""Magic Weapon (SRD 5.2), a per-weapon enchantment (C21): the cast names its
weapon, the rider lands on the touched creature tagged with that weapon's slug,
and the attack path applies it to that weapon only."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CombatHandle
from dnd5e_engine.activities.conjuration import ENCHANTED_WEAPON_FLAG, enchant_weapon
from dnd5e_engine.events import (
    AttackRolled,
    CastFailed,
    DamageApplied,
    EffectApplied,
    EffectExpired,
)
from dnd5e_engine.lib_loader import set_lib_loader_for_tests
from dnd5e_engine.orchestrator import _LiveCombat
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.specs import PartyMemberSpec
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange, ActiveEffectDuration
from tests.c21_support import act, combatant, events, foe, monster_turn, pc, start

LOADER = BundledAssetLoader()


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _hero(entity_id: str = "char:hero", **fields: Any) -> PartyMemberSpec:
    """S04's hero: STR 16, level 5, Magic Weapon known, one level-2 slot."""
    base: dict[str, Any] = {
        "strength": 16,
        "character_level": 5,
        "spells_known": ["magic-weapon"],
        "spell_slots": {2: 1},
    }
    return pc(entity_id, **(base | fields))


def _enchant(
    handle: CombatHandle,
    weapon_id: str | None = "longsword",
    *,
    caster: str = "char:hero",
    target: str = "char:hero",
    **extra: Any,
) -> None:
    act(
        handle,
        caster,
        intent_type="cast_spell",
        spell_id="magic-weapon",
        target_id=target,
        weapon_id=weapon_id,
        **extra,
    )


def _swing(handle: CombatHandle, weapon_id: str = "longsword", actor: str = "char:hero") -> None:
    act(handle, actor, intent_type="attack", weapon_id=weapon_id, target_id="mon:foe")


def _swing_numbers(live: _LiveCombat) -> tuple[int, int]:
    [attack] = events(live, AttackRolled)
    [damage] = events(live, DamageApplied)
    return attack.roll_total, damage.amount


def _rider(weapon: str, bonus: str) -> ActiveEffect:
    """The corpus rider's two mechanical changes, tagged for ``weapon``."""
    return ActiveEffect(
        id=f"effect:magic_weapon_+{bonus}",
        name=f"Magic Weapon +{bonus}",
        origin=f"cast:magic_weapon_+{bonus}:char:hero",
        target_id="char:hero",
        duration=ActiveEffectDuration(seconds=3600),
        changes=[
            ActiveEffectChange(key="system.properties", mode="add", value="mgc"),
            ActiveEffectChange(key="system.magicalBonus", mode="upgrade", value=bonus),
        ],
        flags={ENCHANTED_WEAPON_FLAG: weapon},
    )


def test_enchant_weapon_applies_only_to_its_own_weapon() -> None:
    """``upgrade`` raises the bonus to the rider's value and never stacks; a
    rider tagged for another weapon, or no rider, returns the weapon itself."""
    longsword = LOADER.get_weapon("longsword")
    assert longsword is not None
    assert enchant_weapon(longsword, []) is longsword
    assert enchant_weapon(longsword, [_rider("dagger", "2")]) is longsword
    enchanted = enchant_weapon(longsword, [_rider("longsword", "1"), _rider("longsword", "1")])
    assert (enchanted.magical_bonus, enchanted.magical) == (1, True)
    plus_two = longsword.model_copy(update={"magical_bonus": 2})
    assert enchant_weapon(plus_two, [_rider("longsword", "1")]).magical_bonus == 2


def test_the_cast_tags_the_touched_creature_and_keeps_the_turn() -> None:
    """SRD 5.2: "You touch a nonmagical weapon. Until the spell ends, that weapon
    becomes a magic weapon". A Bonus Action: the slot and the Bonus Action are
    spent, the Action and the turn are not. The level-2 rider keeps its corpus
    duration (3600 seconds)."""
    handle, live = start([_hero()], seed=11)
    _enchant(handle)
    [applied] = events(live, EffectApplied)
    effect = applied.effect
    assert (effect.id, effect.origin, effect.target_id) == (
        "effect:magic_weapon_+1",
        "cast:magic_weapon_+1:char:hero",
        "char:hero",
    )
    assert effect.flags == {ENCHANTED_WEAPON_FLAG: "longsword"}
    assert effect.duration.seconds == 3600
    hero = combatant(live)
    assert (hero.action_available, hero.bonus_action_available) == (True, False)
    assert live.spell_slots_by_entity["char:hero"][2] == 0
    assert live.current_actor_id == "char:hero"


@pytest.mark.parametrize(("enchanted", "numbers"), [(False, (20, 11)), (True, (21, 12))])
def test_enchantment_rides_on_a_pinned_attack_bonus(
    enchanted: bool, numbers: tuple[int, int]
) -> None:
    """S04: a host-pinned +5 to hit. Seed 11 draws d20 15 and d8 8 in both
    runs (the cast draws nothing). Plain: 15 + 5 = 20, 8 + 3 (STR) = 11.
    Enchanted: 15 + 5 + 1 = 21, 8 + 3 + 1 = 12."""
    handle, live = start([_hero(attack_bonus=5)], seed=11)
    if enchanted:
        _enchant(handle)
    _swing(handle)
    assert _swing_numbers(live) == numbers


@pytest.mark.parametrize(("enchanted", "numbers"), [(False, (21, 11)), (True, (22, 12))])
def test_an_unpinned_attack_counts_the_bonus_once(
    enchanted: bool, numbers: tuple[int, int]
) -> None:
    """No pinned to-hit: PB 3 + STR 3 = +6, and the weapon's own
    ``magical_bonus`` adds the +1 (no second +1 from the pinned-bonus path).
    Seed 11: 15 + 6 (+ 1); 8 + 3 (+ 1)."""
    handle, live = start([_hero()], seed=11)
    if enchanted:
        _enchant(handle)
    _swing(handle)
    assert _swing_numbers(live) == numbers


def test_other_weapons_are_not_enchanted() -> None:
    """The longsword is enchanted; a Mace swing gets nothing. Seed 11: d20 15
    + 5 = 20; the Mace's d6 draws 5, + 3 = 8."""
    handle, live = start([_hero(attack_bonus=5)], seed=11)
    _enchant(handle)
    _swing(handle, "mace")
    assert _swing_numbers(live) == (20, 8)


def test_the_enchanted_creature_is_the_one_touched() -> None:
    """A cleric enchants the fighter's Longsword: the rider lands on the
    fighter, keyed to the cleric's cast, and the fighter's swing gets the +1.
    Seed 11 (the cast and the cleric's ``pass`` draw nothing): 15 + 5 + 1 = 21,
    8 + 3 + 1 = 12."""
    handle, live = start(
        [
            _hero("char:cleric"),
            pc(
                "char:fighter",
                initiative=15,
                zone_id=cell_id(0, 1),
                strength=16,
                attack_bonus=5,
            ),
        ],
        seed=11,
    )
    _enchant(handle, caster="char:cleric", target="char:fighter")
    [applied] = events(live, EffectApplied)
    assert (applied.effect.target_id, applied.effect.origin) == (
        "char:fighter",
        "cast:magic_weapon_+1:char:cleric",
    )
    act(handle, "char:cleric", intent_type="pass")
    _swing(handle, actor="char:fighter")
    assert _swing_numbers(live) == (21, 12)


def test_a_level_3_slot_gives_plus_2() -> None:
    """SRD 5.2: "The bonus increases to +2 with a level 3–5 spell slot." Seed
    11: 15 + 5 + 2 = 22; 8 + 3 + 2 = 13."""
    handle, live = start([_hero(attack_bonus=5, spell_slots={3: 1})], seed=11)
    _enchant(handle, slot_level=3)
    [applied] = events(live, EffectApplied)
    assert applied.effect.id == "effect:magic_weapon_+2"
    _swing(handle)
    assert _swing_numbers(live) == (22, 13)


@pytest.mark.parametrize(
    "weapon_id",
    [None, "no-such-weapon", "shield", "flame-tongue", "dagger-of-venom", "unarmed-strike"],
)
def test_a_cast_without_a_nonmagical_weapon_is_refused_before_spending(
    weapon_id: str | None,
) -> None:
    """No weapon, an unknown slug, a Shield (armor), a magical weapon (Flame
    Tongue), a +1 weapon (Dagger of Venom) and an Unarmed Strike (not a weapon)
    are all refused before the slot or the Bonus Action is spent."""
    handle, live = start([_hero()], seed=11)
    _enchant(handle, weapon_id)
    assert [(e.spell_id, e.reason) for e in events(live, CastFailed)] == [
        ("magic-weapon", "target_invalid")
    ]
    hero = combatant(live)
    assert (hero.action_available, hero.bonus_action_available) == (True, True)
    assert live.spell_slots_by_entity["char:hero"] == {2: 1}
    assert not events(live, EffectApplied)


def test_casting_it_again_ends_the_first_enchantment() -> None:
    """SRD 5.2: "The spell ends early if you cast it again." The second cast, on
    the next turn, enchants the Dagger and ends the Longsword's rider."""
    handle, live = start([_hero(attack_bonus=5, spell_slots={2: 2})], seed=11)
    _enchant(handle)
    act(handle, "char:hero", intent_type="pass")
    monster_turn(handle)
    _enchant(handle, "dagger")
    [expired] = events(live, EffectExpired)
    assert (expired.effect_id, expired.target_id, expired.origin, expired.reason) == (
        "effect:magic_weapon_+1",
        "char:hero",
        "cast:magic_weapon_+1:char:hero",
        "remove_ieffect",
    )
    assert [e.flags for e in live.active_effects["char:hero"]] == [
        {ENCHANTED_WEAPON_FLAG: "dagger"}
    ]


@pytest.mark.parametrize(("enchanted", "damage"), [(False, 5), (True, 12)])
def test_the_enchanted_weapon_overcomes_nonmagical_resistance(enchanted: bool, damage: int) -> None:
    """The foe resists nonmagical Slashing (``EncounterMemberSpec``'s default).
    Seed 11: the plain 8 + 3 = 11 is halved to 5; the magic weapon's 12 is not."""
    handle, live = start(
        [_hero(attack_bonus=5)], seed=11, encounter=[foe(damage_resistances=["slashing"])]
    )
    if enchanted:
        _enchant(handle)
    _swing(handle)
    assert _swing_numbers(live)[1] == damage


def test_a_seeded_enchantment_enchants_the_weapon() -> None:
    """A cast made before combat: the rider's corpus changes plus the flag,
    passed to ``start_combat(active_effects=)``, behave like the cast."""
    handle, live = start(
        [_hero(attack_bonus=5)], seed=11, active_effects=[_rider("longsword", "1")]
    )
    _swing(handle)
    assert _swing_numbers(live) == (21, 12)


def test_readying_magic_weapon_is_refused() -> None:
    """A readied cast cannot carry the weapon it enchants."""
    handle, live = start([_hero()], seed=11)
    act(
        handle,
        "char:hero",
        intent_type="ready",
        spell_id="magic-weapon",
        reaction_trigger="hit_by_attack",
    )
    assert [(e.spell_id, e.reason) for e in events(live, CastFailed)] == [
        ("magic-weapon", "target_invalid")
    ]
    assert combatant(live).action_available
    assert not live.pending_reactions


def test_sacred_weapon_stays_narrative_and_free() -> None:
    """Sacred Weapon's enchant is not allowlisted: it applies nothing and, as a
    free ``special`` activation (C20), spends no action."""
    handle, live = start(
        [pc(class_slug="paladin", subclass_slug="devotion", character_level=3)], seed=1
    )
    act(handle, "char:hero", intent_type="use_feature", feature_id="sacred-weapon")
    hero = combatant(live)
    assert not events(live, EffectApplied)
    assert (hero.action_available, hero.bonus_action_available) == (True, True)
    assert live.current_actor_id == "char:hero"
