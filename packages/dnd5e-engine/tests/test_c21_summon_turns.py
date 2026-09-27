"""A summoned creature's turn (C21): SRD 5.2 Summon Dragon — "It obeys your
verbal commands (no action required by you). If you don't issue any, it takes
the Dodge action and uses its movement to avoid danger." ``advance_monster_turn``
plays the uncommanded Dodge; a host commands the Draconic Spirit through
``submit_player_intent`` with one ``stat_block_action_id`` swing per Rend, at
its summoner's numbers: "Bonus equals your spell attack modifier"; "Hit: 1d6 +
4 + the spell's level Piercing damage"; "a number of Rend attacks equal to half
the spell's level (round down)".

The cast and the Dodge draw nothing and every initiative is explicit, so each
seeded test's first draws are its first attack's d20 (two under Disadvantage),
then its damage dice.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import CombatHandle, get_live
from dnd5e_engine.activities.conjuration import TRANSFORM_FORM_FLAG
from dnd5e_engine.events import (
    AttackFailed,
    AttackRolled,
    CombatantJoined,
    CombatantLeft,
    ConcentrationDropped,
    ConditionApplied,
    DamageApplied,
    EffectExpired,
    IntentSubmitted,
    SaveRolled,
    TurnEnded,
    TurnPhase,
    TurnStarted,
    Unconscious,
)
from dnd5e_engine.lib_loader import get_lib_loader, set_lib_loader_for_tests
from dnd5e_engine.orchestrator import (
    _apply_transform,
    _emit,
    _LiveCombat,
    _stat_block_magnitudes_of,
)
from dnd5e_engine.spatial import cell_id
from dnd5e_engine.types.effects import ActiveEffect
from tests.c21_support import (
    act,
    combatant,
    events,
    foe,
    joined,
    monster_turn,
    pc,
    roster,
    start,
    summoner,
)

SUMMONER = "char:summoner"
SPIRIT = "summon:char:summoner:draconic-spirit:1"


@pytest.fixture(autouse=True)
def _bundled_loader() -> Iterator[None]:
    set_lib_loader_for_tests(BundledAssetLoader())
    yield
    set_lib_loader_for_tests(None)


def _summoned(seed: int, *, level: int = 5, **fields: Any) -> tuple[CombatHandle, _LiveCombat]:
    """The summoner casts Summon Dragon at ``level``; the default foe holds 1,0,
    so the spirit manifests at 0,1, 5 feet from it, and it is the spirit's turn."""
    handle, live = start([summoner(spell_slots={level: 1}, **fields)], seed=seed)
    act(handle, SUMMONER, intent_type="cast_spell", spell_id="summon-dragon", slot_level=level)
    assert live.current_actor_id == SPIRIT
    return handle, live


def _rend(handle: CombatHandle, target_id: str = "mon:foe", **extra: Any) -> None:
    act(
        handle,
        SPIRIT,
        intent_type="attack",
        stat_block_action_id="rend",
        target_id=target_id,
        **extra,
    )


def _economy(live: _LiveCombat, entity_id: str) -> tuple[bool, bool, bool]:
    c = combatant(live, entity_id)
    return (c.action_available, c.bonus_action_available, c.reaction_available)


# ── The uncommanded turn ─────────────────────────────────────────────────────


def test_advance_monster_turn_on_a_summon_takes_the_dodge_and_draws_nothing() -> None:
    handle, live = _summoned(seed=1)
    state, first = live.rng.getstate(), len(live.event_log)
    monster_turn(handle)
    assert live.rng.getstate() == state
    assert [type(e) for e in live.event_log[first:]] == [
        IntentSubmitted,
        TurnPhase,
        TurnEnded,
        TurnStarted,
        TurnPhase,
    ]
    assert live.event_log[first] == IntentSubmitted(actor_id=SPIRIT, intent_type="dodge")
    spirit = combatant(live, SPIRIT)
    assert spirit.dodging
    assert (live.actor_zone[SPIRIT], spirit.movement_remaining) == (cell_id(0, 1), 30)
    assert live.current_actor_id == "mon:foe"


def test_the_dodge_gives_attackers_disadvantage_until_its_next_turn() -> None:
    """With the summoner at 60 HP, the spirit (50) is the foe's lowest-HP
    enemy. Seed 1, the foe's attack under Disadvantage: d20 5 and 19, the 5
    kept; +0 misses AC 19. The benefit lasts "until the start of your next
    turn"."""
    handle, live = _summoned(seed=1, hp_current=60, hp_max=60)
    monster_turn(handle)  # the spirit's Dodge
    monster_turn(handle)  # the foe attacks the spirit
    [roll] = events(live, AttackRolled)
    assert (roll.attacker_id, roll.target_id) == ("mon:foe", SPIRIT)
    assert (roll.advantage, roll.disadvantage_sources) == ("disadvantage", ["dodge"])
    assert (roll.natural, roll.is_hit) == (5, False)
    act(handle, SUMMONER, intent_type="pass")
    assert live.current_actor_id == SPIRIT
    assert not combatant(live, SPIRIT).dodging


def test_an_incapacitated_summon_passes() -> None:
    """SRD 5.2 Incapacitated: "You can't take any action" — no Dodge either."""
    handle, live = _summoned(seed=1)
    _emit(live, ConditionApplied(target_id=SPIRIT, condition="paralyzed"))
    first = len(live.event_log)
    monster_turn(handle)
    assert live.event_log[first] == IntentSubmitted(actor_id=SPIRIT, intent_type="pass")
    assert not combatant(live, SPIRIT).dodging
    assert live.current_actor_id == "mon:foe"


def test_a_summon_whose_action_was_spent_passes() -> None:
    """One commanded Rend spends the spirit's Action; ``advance_monster_turn``
    then ends its turn with a pass. Seed 3: d20 8 + 8 hits AC 1; d6 5 + 9."""
    handle, live = _summoned(seed=3)
    _rend(handle)
    assert live.current_actor_id == SPIRIT
    first = len(live.event_log)
    monster_turn(handle)
    assert live.event_log[first] == IntentSubmitted(actor_id=SPIRIT, intent_type="pass")
    assert not combatant(live, SPIRIT).dodging
    assert live.current_actor_id == "mon:foe"


# ── Commands ─────────────────────────────────────────────────────────────────


def test_a_commanded_rend() -> None:
    """The Wizard 9's spirit at a level-5 slot: Rend at +8 (the summoner's
    spell attack) for 1d6 + 4 (STR 19) + 5 Piercing, reach 10 feet. The two
    refusals draw nothing, so seed 1's first draws are the Rend's: d20 5 → 13
    hits AC 1; d6 5 → 14. The summoner spends nothing: "no action required by
    you"."""
    handle, live = start(
        [summoner()],
        seed=1,
        encounter=[
            foe(entity_id="mon:near", zone_id=cell_id(2, 1)),
            foe(entity_id="mon:far", zone_id=cell_id(3, 1)),
        ],
    )
    act(
        handle,
        SUMMONER,
        intent_type="cast_spell",
        spell_id="summon-dragon",
        target_zone_id=cell_id(0, 1),
    )
    caster_economy = _economy(live, SUMMONER)
    _rend(handle, "mon:far")  # 15 feet away
    act(
        handle,
        SPIRIT,
        intent_type="attack",
        stat_block_action_id="breath-weapon",
        target_id="mon:near",
    )
    assert [e.reason for e in events(live, AttackFailed)] == ["out_of_range", "action_unavailable"]
    assert combatant(live, SPIRIT).action_available
    _rend(handle, "mon:near")  # 10 feet away
    [roll] = events(live, AttackRolled)
    [damage] = events(live, DamageApplied)
    assert (roll.attacker_id, roll.natural, roll.modifier, roll.roll_total) == (SPIRIT, 5, 8, 13)
    assert (damage.target_id, damage.amount, damage.damage_type) == ("mon:near", 14, "piercing")
    assert _economy(live, SUMMONER) == caster_economy


@pytest.mark.parametrize(("level", "count"), [(5, 2), (9, 4)])
def test_the_summon_swings_half_the_spell_level(level: int, count: int) -> None:
    """Its Attack action has ``floor(level / 2)`` Rends; the host picks each
    swing, one more is refused, and a multi-attack actor keeps its turn until
    it passes (C21a's stat-block command rule)."""
    handle, live = _summoned(seed=1, level=level)
    assert get_live(handle).turn.attacks_remaining == count
    for left in range(count - 1, -1, -1):
        _rend(handle)
        assert (live.current_actor_id, get_live(handle).turn.attacks_remaining) == (SPIRIT, left)
    _rend(handle)
    assert len(events(live, AttackRolled)) == count
    assert [e.reason for e in events(live, AttackFailed)] == ["no_action_economy"]
    act(handle, SPIRIT, intent_type="pass")
    assert live.current_actor_id == "mon:foe"


def test_a_classless_casters_spirit_rolls_at_the_legacy_to_hit() -> None:
    """S01's caster is a classless level-9 character: no spellcasting ability,
    so its spell attack is PB 4 + 0, and its spirit's Rend is +4 (damage is
    still 1d6 + 4 + 5). Seed 12: d20 16 → 20; d6 3 → 12."""
    handle, live = start(
        [
            pc(
                SUMMONER,
                character_level=9,
                spells_known=["summon-dragon"],
                spell_slots={5: 1},
                hp_current=60,
                hp_max=60,
            )
        ],
        seed=12,
    )
    act(handle, SUMMONER, intent_type="cast_spell", spell_id="summon-dragon")
    assert live.summons[SPIRIT].magnitudes.attack_bonus == 4
    _rend(handle)
    [roll] = events(live, AttackRolled)
    [damage] = events(live, DamageApplied)
    assert (roll.natural, roll.modifier, roll.roll_total) == (16, 4, 20)
    assert damage.amount == 12


def test_transformed_numbers_are_unchanged() -> None:
    """C21a's Wolf form: the summon rules add no flat to-hit and no damage
    bonus to a transform. Seed 11: d20 15 + 4 → 19; d6 5 + 2 → 7."""
    handle, live = start([pc()], seed=11)
    wolf = get_lib_loader().get_monster("wolf")
    assert wolf is not None
    _apply_transform(
        live,
        "char:hero",
        wolf,
        source="wild-shape",
        effect=ActiveEffect(
            id="effect:wild-shape",
            name="Wild Shape",
            origin="cast:wild-shape:char:hero",
            target_id="char:hero",
            flags={TRANSFORM_FORM_FLAG: "wolf"},
        ),
        temp_hp=1,
    )
    magnitudes = _stat_block_magnitudes_of(live, combatant(live))
    assert magnitudes is not None
    assert (magnitudes.attack_bonus, magnitudes.attack_damage_bonus) == (None, 0)
    act(handle, "char:hero", intent_type="attack", stat_block_action_id="bite", target_id="mon:foe")
    [roll] = events(live, AttackRolled)
    [damage] = events(live, DamageApplied)
    assert (roll.natural, roll.modifier, roll.roll_total) == (15, 4, 19)
    assert damage.amount == 7


# ── Dismissal end to end ─────────────────────────────────────────────────────


def test_a_broken_concentration_dismisses_the_spirit_on_seed_4() -> None:
    """S02's combat, seed 4. The cast and the spirit's Dodge draw nothing. The
    hill giant ``mon:breaker`` attacks the druid, the lowest-HP enemy at 15
    against the spirit's 50: d20 8 misses AC 10, d20 10 hits, and Tree Club's
    3d8 is 2 + 7 + 8 = 17. SRD 5.2 Concentration: "The DC equals 10 or half the
    damage taken (round down)" — DC 10; the save's d20 5 fails. The drop comes
    before the 0-HP branch, so the spirit leaves with ``concentration_drop``
    and the druid then falls Unconscious."""
    druid = pc(
        "char:druid",
        character_level=9,
        spells_known=["summon-dragon"],
        spell_slots={5: 1},
        hp_current=15,
        hp_max=15,
    )
    breaker = foe(
        entity_id="mon:breaker",
        name="Breaker",
        initiative=19,
        hp_current=100,
        hp_max=100,
        monster_template_slug="hill-giant",
    )
    distant = foe(zone_id=cell_id(2, 0), initiative=5, ac=15, hp_current=100, hp_max=100)
    handle, live = start([druid], seed=4, encounter=[distant, breaker])
    act(
        handle,
        "char:druid",
        intent_type="cast_spell",
        spell_id="summon-dragon",
        target_id="mon:foe",
    )
    [spirit] = [e.entity_id for e in joined(live, "char:druid")]
    assert (spirit, live.actor_zone[spirit]) == ("summon:char:druid:draconic-spirit:1", "0,1")
    state = live.rng.getstate()
    monster_turn(handle)  # the spirit's Dodge
    assert live.rng.getstate() == state
    assert roster(live) == ["char:druid", spirit, "mon:breaker", "mon:foe"]
    first = len(live.event_log)
    monster_turn(handle)  # the breaker's Multiattack against the druid
    rolls = [(e.target_id, e.natural, e.is_hit) for e in events(live, AttackRolled)]
    assert rolls == [("char:druid", 8, False), ("char:druid", 10, True)]
    [damage] = events(live, DamageApplied)
    assert (damage.target_id, damage.amount, damage.damage_type) == (
        "char:druid",
        17,
        "bludgeoning",
    )
    [save] = events(live, SaveRolled)
    assert (save.ability, save.dc, save.natural, save.succeeded) == ("con", 10, 5, False)
    cascade = [
        e
        for e in live.event_log[first:]
        if isinstance(e, (ConcentrationDropped, EffectExpired, CombatantLeft, Unconscious))
    ]
    assert [type(e) for e in cascade] == [
        ConcentrationDropped,
        EffectExpired,
        CombatantLeft,
        Unconscious,
    ]
    _, expired, left, _ = cascade
    assert isinstance(expired, EffectExpired)
    assert expired.effect_id == "effect:summon-dragon"
    assert left == CombatantLeft(entity_id=spirit, reason="concentration_drop")
    assert roster(live) == ["char:druid", "mon:breaker", "mon:foe"]
    assert len(events(live, CombatantJoined)) == 1
