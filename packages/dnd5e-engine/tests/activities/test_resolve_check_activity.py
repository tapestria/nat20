"""Behavioral tests for the ``check`` kind handler (``activities/check.py``).

A ``CheckActivity`` makes ONE actor roll a d20-based ability or skill check
against a DC. The rules the handler owns, and that a host would notice
breaking:

- **Who rolls.** The first target when the check is imposed on someone
  (escape the manacles, resist Banish to Maze), otherwise the caster. Rolling
  for the wrong actor silently uses the wrong modifier.
- **Which modifier.** The named skill's resolved modifier off the sidecar when
  present, else the governing ability's, else +0. Never rebuilt from scores.
- **DC resolution.** ``"spellcasting"`` derives ``8 + prof + ability mod``;
  ``"flat"`` and an empty calculation both use the literal formula; both
  empty means a no-DC informational check where ``succeeded`` is ``None``.
  An unknown calculation raises rather than silently defaulting to a DC the
  designer never wrote.
- **Skill→ability.** ``check.associated`` carries Foundry 3-letter codes, so
  ``"ath"`` must resolve to Strength. An unrecognized entry (a tool slug)
  falls back to the explicit ability but is still reported as the skill label.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from dnd5e_srd_data.schema.common import CheckActivity

from dnd5e_engine.activities.actor_stats import _SCORE_ATTR
from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.check import (
    _SKILL_CODE_TO_SLUG,
    _SKILL_TO_ABILITY,
    FORCE_CHECK_D20,
    resolve_check,
)
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import CheckRolled
from dnd5e_engine.orchestrator import _build_hydration_payload, _get_live, start_combat
from dnd5e_engine.rules.skills import SKILL_ABILITIES
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange, ActiveEffectDuration
from tests.e2e.harness import run_async, single_zone

ABILITIES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def _combatant(entity_id: str, name: str = "Someone") -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Character",
        name=name,
        initiative=10,
        hp_current=20,
        hp_max=20,
    )


def _activity(
    *,
    ability: str = "",
    associated: list[str] | None = None,
    calculation: str = "",
    formula: str = "",
) -> CheckActivity:
    return CheckActivity(
        kind="check",
        check={
            "ability": ability,
            "associated": associated or [],
            "dc": {"calculation": calculation, "formula": formula},
        },
    )


def _ctx(
    *,
    targets: list[Combatant] | None = None,
    forced_d20: int | None = 10,
    check_modifiers: dict[str, dict[str, dict[str, int]]] | None = None,
    caster_abilities: dict[str, int] | None = None,
    **kwargs: Any,
) -> tuple[ActivityResolutionContext, list[Any]]:
    events: list[Any] = []
    variables: dict[str, Any] = {}
    if forced_d20 is not None:
        variables[FORCE_CHECK_D20] = forced_d20
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_combatant("char:hero", "Hero"),
        targets=targets or [],
        event_emitter=events.append,
        caster_abilities=caster_abilities or dict(ABILITIES),
        variables=variables,
        check_modifiers=check_modifiers or {},
        **kwargs,
    )
    return ctx, events


def _only_check(events: list[Any]) -> CheckRolled:
    checks = [e for e in events if isinstance(e, CheckRolled)]
    assert len(checks) == 1, f"expected exactly one CheckRolled, got {events!r}"
    return checks[0]


# ---------------------------------------------------------------------------
# Who rolls
# ---------------------------------------------------------------------------


def test_the_caster_rolls_a_self_check() -> None:
    """No target -> the caster rolls (a PC's own Stealth check)."""
    ctx, events = _ctx()

    resolve_check(_activity(associated=["ste"], calculation="flat", formula="15"), ctx)

    assert _only_check(events).actor_id == "char:hero"


def test_the_first_target_rolls_an_imposed_check() -> None:
    """An imposed check (escape the manacles) is rolled by the bound creature,
    not by whoever applied it."""
    ctx, events = _ctx(targets=[_combatant("npc:bound"), _combatant("npc:other")])

    resolve_check(_activity(associated=["slt"], calculation="flat", formula="15"), ctx)

    assert _only_check(events).actor_id == "npc:bound"


# ---------------------------------------------------------------------------
# Skill / ability resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,ability",
    [
        ("ath", "str"),
        ("acr", "dex"),
        ("ste", "dex"),
        ("slt", "dex"),
        ("arc", "int"),
        ("inv", "int"),
        ("prc", "wis"),
        ("sur", "wis"),
        ("per", "cha"),
        ("itm", "cha"),
    ],
)
def test_skill_codes_map_to_their_governing_ability(code: str, ability: str) -> None:
    ctx, events = _ctx()

    resolve_check(_activity(associated=[code], calculation="flat", formula="10"), ctx)

    event = _only_check(events)
    assert event.skill == code
    assert event.ability == ability


def test_raw_ability_check_reports_no_skill() -> None:
    ctx, events = _ctx()

    resolve_check(_activity(ability="int", calculation="flat", formula="20"), ctx)

    event = _only_check(events)
    assert event.skill is None
    assert event.ability == "int"


def test_unknown_associated_entry_falls_back_to_the_explicit_ability() -> None:
    """A tool slug in `associated` is not a skill code; the ability comes from
    `check.ability` but the slug is still surfaced as the label."""
    ctx, events = _ctx()

    resolve_check(
        _activity(ability="dex", associated=["thief"], calculation="flat", formula="15"), ctx
    )

    event = _only_check(events)
    assert event.skill == "thief"
    assert event.ability == "dex"


def test_a_check_with_neither_a_known_skill_nor_an_ability_raises() -> None:
    """Silently defaulting the ability would roll the wrong modifier forever."""
    ctx, _ = _ctx()

    with pytest.raises(ValueError, match="no resolvable ability"):
        resolve_check(_activity(calculation="flat", formula="15"), ctx)


def test_an_invalid_ability_code_raises() -> None:
    ctx, _ = _ctx()

    with pytest.raises(ValueError, match="no resolvable ability"):
        resolve_check(_activity(ability="luck", calculation="flat", formula="15"), ctx)


# ---------------------------------------------------------------------------
# Modifier sourcing
# ---------------------------------------------------------------------------


def test_skill_modifier_from_the_sidecar_is_added_to_the_roll() -> None:
    ctx, events = _ctx(
        forced_d20=10,
        check_modifiers={"char:hero": {"skills": {"ste": 7}, "ability_mods": {"dex": 2}}},
    )

    resolve_check(_activity(associated=["ste"], calculation="flat", formula="15"), ctx)

    event = _only_check(events)
    assert event.roll_total == 17, "the skill modifier wins over the ability modifier"
    assert event.succeeded is True


def test_ability_modifier_is_used_when_the_skill_is_absent_from_the_sidecar() -> None:
    ctx, events = _ctx(
        forced_d20=10,
        check_modifiers={"char:hero": {"skills": {}, "ability_mods": {"dex": 3}}},
    )

    resolve_check(_activity(associated=["ste"], calculation="flat", formula="15"), ctx)

    assert _only_check(events).roll_total == 13


def test_an_actor_missing_from_the_sidecar_rolls_flat() -> None:
    ctx, events = _ctx(forced_d20=10, check_modifiers={"someone:else": {"skills": {"ste": 9}}})

    resolve_check(_activity(associated=["ste"], calculation="flat", formula="15"), ctx)

    assert _only_check(events).roll_total == 10


def test_the_modifier_is_read_for_the_rolling_actor_not_the_caster() -> None:
    """The sidecar is keyed by entity; an imposed check must not borrow the
    caster's skill modifier."""
    ctx, events = _ctx(
        targets=[_combatant("npc:bound")],
        forced_d20=10,
        check_modifiers={
            "char:hero": {"skills": {"slt": 10}},
            "npc:bound": {"skills": {"slt": 1}},
        },
    )

    resolve_check(_activity(associated=["slt"], calculation="flat", formula="15"), ctx)

    assert _only_check(events).roll_total == 11


def test_a_negative_modifier_lowers_the_total() -> None:
    ctx, events = _ctx(forced_d20=10, check_modifiers={"char:hero": {"ability_mods": {"str": -2}}})

    resolve_check(_activity(ability="str", calculation="flat", formula="15"), ctx)

    event = _only_check(events)
    assert event.roll_total == 8
    assert event.succeeded is False


# ---------------------------------------------------------------------------
# DC resolution
# ---------------------------------------------------------------------------


def test_flat_dc_is_read_from_the_formula() -> None:
    ctx, events = _ctx(forced_d20=10)

    resolve_check(_activity(ability="int", calculation="flat", formula="20"), ctx)

    event = _only_check(events)
    assert event.dc == 20
    assert event.succeeded is False


def test_empty_calculation_with_a_formula_is_treated_as_flat() -> None:
    """Every canonical check ships `calculation=""` plus a literal formula."""
    ctx, events = _ctx(forced_d20=10)

    resolve_check(_activity(ability="int", calculation="", formula="12"), ctx)

    assert _only_check(events).dc == 12


def test_no_calculation_and_no_formula_is_an_informational_check() -> None:
    """The actor still rolls and the event is still emitted, but there is no
    pass/fail verdict to report."""
    ctx, events = _ctx(forced_d20=10)

    resolve_check(_activity(ability="int"), ctx)

    event = _only_check(events)
    assert event.dc is None
    assert event.succeeded is None
    assert event.roll_total == 10


def test_spellcasting_dc_is_eight_plus_proficiency_plus_ability() -> None:
    ctx, events = _ctx(
        forced_d20=10,
        caster_abilities={**ABILITIES, "int": 18},
        caster_proficiency_bonus=4,
        spellcasting_ability="int",
    )

    resolve_check(_activity(ability="str", calculation="spellcasting"), ctx)

    assert _only_check(events).dc == 16  # 8 + 4 + 4


def test_spellcasting_dc_without_a_spellcasting_ability_raises() -> None:
    ctx, _ = _ctx(spellcasting_ability=None)

    with pytest.raises(ValueError, match="requires a caster spellcasting ability"):
        resolve_check(_activity(ability="str", calculation="spellcasting"), ctx)


def test_an_unknown_dc_calculation_raises() -> None:
    """Loud failure beats silently rolling against a DC nobody authored."""
    ctx, _ = _ctx()

    with pytest.raises(ValueError, match="not resolvable"):
        resolve_check(_activity(ability="str", calculation="max", formula="10"), ctx)


# ---------------------------------------------------------------------------
# Success comparison and the d20 seam
# ---------------------------------------------------------------------------


def test_meeting_the_dc_exactly_succeeds() -> None:
    ctx, events = _ctx(forced_d20=15)

    resolve_check(_activity(ability="str", calculation="flat", formula="15"), ctx)

    assert _only_check(events).succeeded is True


def test_falling_one_short_fails() -> None:
    ctx, events = _ctx(forced_d20=14)

    resolve_check(_activity(ability="str", calculation="flat", formula="15"), ctx)

    assert _only_check(events).succeeded is False


def test_without_the_forced_seam_the_roll_comes_from_the_seeded_rng() -> None:
    """Same seed, same roll — the handler must not reach for global random."""
    totals = []
    for _ in range(2):
        ctx, events = _ctx(forced_d20=None)
        resolve_check(_activity(ability="str", calculation="flat", formula="15"), ctx)
        totals.append(_only_check(events).roll_total)

    assert totals[0] == totals[1]
    assert 1 <= totals[0] <= 20


# ---------------------------------------------------------------------------
# F1d — the sidecar the handler reads is populated by the orchestrator
# ---------------------------------------------------------------------------
#
# The modifier above is read off ``ctx.check_modifiers``; these tests pin WHERE
# that sidecar comes from. The orchestrator projects every combatant's six
# ability-check modifiers and every proficient skill's modifier through
# ``activities.actor_stats.check_modifier`` (SRD 5.2 §D20 Tests: d20 + ability
# modifier + proficiency bonus if proficient, doubled with Expertise), folds the
# ``abilities.check`` / ``abilities.skill`` / ``abilities.<ab>.save`` active-effect
# buckets on top, and ``build_activity_context`` threads the payload through.


def _f1d_party(**kw: Any) -> list[PartyMemberSpec]:
    base: dict[str, Any] = {
        "entity_id": "char:a",
        "name": "A",
        "initiative": 10,
        "hp_current": 20,
        "hp_max": 20,
        "zone_id": "zone:start",
    }
    base.update(kw)
    return [PartyMemberSpec(**base)]


def _f1d_foe() -> list[EncounterMemberSpec]:
    return [
        EncounterMemberSpec(
            entity_id="mon:f",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=7,
            hp_max=7,
            zone_id="zone:start",
        )
    ]


def _f1d_payload(*, party: list[PartyMemberSpec], effects: tuple[Any, ...] = ()) -> dict[str, Any]:
    start = run_async(
        start_combat(
            session_id="f1d-check-mods",
            party=party,
            encounter=_f1d_foe(),
            scene_zones=single_zone(),
            rng_seed=1,
            active_effects=effects,
        )
    )
    return _build_hydration_payload(_get_live(start.handle), caster=None)


def _f1d_ctx(payload: dict[str, Any], events: list[Any]) -> ActivityResolutionContext:
    """An activity context threading the hydration payload's check sidecar."""
    ctx = build_activity_context(
        _combatant("char:a"),
        [],
        rng=random.Random(1),
        event_emitter=events.append,
        slot_level=None,
        base_spell_level=None,
        spellcasting_ability=None,
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers=payload["passive_damage_modifiers"],
        save_modifiers=payload["save_modifiers"],
        check_modifiers=payload["check_modifiers"],
    )
    ctx.variables[FORCE_CHECK_D20] = 10
    return ctx


def _check_bonus(key: str, value: int) -> tuple[Any, ...]:
    return (
        ActiveEffect(
            id="effect:buff",
            name="Buff",
            origin="test",
            target_id="char:a",
            duration=ActiveEffectDuration(),
            changes=[ActiveEffectChange(key=key, mode="add", value=value)],
        ),
    )


def test_skill_modifier_is_ability_mod_plus_proficiency_plus_effect_bonus() -> None:
    """WIS 14 (+2), level 5 (PB +3), Perception proficiency, +2 abilities.check."""
    payload = _f1d_payload(
        party=_f1d_party(wisdom=14, character_level=5, skill_proficiencies=("perception",)),
        effects=_check_bonus("abilities.check", 2),
    )

    assert payload["check_modifiers"]["char:a"]["skills"]["perception"] == 2 + 3 + 2


def test_every_ability_check_modifier_is_projected() -> None:
    payload = _f1d_payload(party=_f1d_party(wisdom=14, strength=8, character_level=5))

    ability_mods = payload["check_modifiers"]["char:a"]["ability_mods"]
    assert set(ability_mods) == {"str", "dex", "con", "int", "wis", "cha"}
    assert ability_mods["wis"] == 2
    assert ability_mods["str"] == -1
    # No skill proficiencies -> no skill entries (the handler falls back to the
    # ability modifier).
    assert payload["check_modifiers"]["char:a"]["skills"] == {}


def test_expertise_doubles_the_proficiency_bonus() -> None:
    payload = _f1d_payload(
        party=_f1d_party(
            dexterity=14,
            character_level=5,
            skill_proficiencies=("stealth",),
            skill_expertise=("stealth",),
        )
    )

    assert payload["check_modifiers"]["char:a"]["skills"]["stealth"] == 2 + 6


def test_abilities_check_bonus_reaches_every_ability_and_skill() -> None:
    payload = _f1d_payload(
        party=_f1d_party(skill_proficiencies=("perception",)),
        effects=_check_bonus("abilities.check", 2),
    )

    entry = payload["check_modifiers"]["char:a"]
    assert all(mod == 2 for mod in entry["ability_mods"].values())
    assert entry["skills"]["perception"] == 2 + 2


def test_abilities_skill_bonus_reaches_skills_only() -> None:
    payload = _f1d_payload(
        party=_f1d_party(skill_proficiencies=("perception",)),
        effects=_check_bonus("abilities.skill", 3),
    )

    entry = payload["check_modifiers"]["char:a"]
    assert entry["skills"]["perception"] == 2 + 3
    assert all(mod == 0 for mod in entry["ability_mods"].values())


def test_per_ability_save_bonus_folds_into_that_save_only() -> None:
    payload = _f1d_payload(
        party=_f1d_party(wisdom=14),
        effects=_check_bonus("abilities.wis.save", 1),
    )

    saves = payload["save_modifiers"]["char:a"]["saves"]
    assert saves["wis"] == 2 + 1
    assert saves["cha"] == 0


@pytest.mark.parametrize(
    ("condition", "expected"),
    [("poisoned", True), ("frightened", True), ("exhaustion", False), ("prone", False)],
)
def test_condition_disadvantage_merges_with_the_projected_modifiers(
    condition: str, expected: bool
) -> None:
    start = run_async(
        start_combat(
            session_id="f1d-check-dis",
            party=_f1d_party(wisdom=14),
            encounter=_f1d_foe(),
            scene_zones=single_zone(),
            rng_seed=1,
        )
    )
    live = _get_live(start.handle)
    actor = next(c for c in live.initiative if c.entity_id == "char:a")
    actor.conditions.append(
        ActiveCondition(condition=condition, source_entity_id="npc:abc123def456", scope="combat")
    )

    entry = _build_hydration_payload(live, caster=None)["check_modifiers"]["char:a"]
    # SRD 5.2 §Exhaustion is a numeric -2 x level penalty on every D20 Test (C12,
    # rules/conditions.py::d20_test_penalty); it no longer projects disadvantage.
    assert entry["disadvantage"] is expected
    assert entry["passive_check_dis"] == (["all"] if expected else [])
    assert entry["ability_mods"]["wis"] == 2


def test_the_payload_reaches_the_activity_context_and_the_handler() -> None:
    payload = _f1d_payload(
        party=_f1d_party(wisdom=14, character_level=5, skill_proficiencies=("perception",)),
        effects=_check_bonus("abilities.check", 2),
    )
    actor = _combatant("char:a")
    events: list[Any] = []
    ctx = build_activity_context(
        actor,
        [],
        rng=random.Random(1),
        event_emitter=events.append,
        slot_level=None,
        base_spell_level=None,
        spellcasting_ability=None,
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers=payload["passive_damage_modifiers"],
        save_modifiers=payload["save_modifiers"],
        check_modifiers=payload["check_modifiers"],
    )

    assert ctx.check_modifiers["char:a"]["skills"]["perception"] == 2 + 3 + 2
    assert ctx.check_modifiers["char:a"]["ability_mods"]["wis"] == 2 + 2

    ctx.variables[FORCE_CHECK_D20] = 10
    resolve_check(_activity(ability="wis", calculation="flat", formula="10"), ctx)

    assert _only_check(events).roll_total == 10 + 4


def test_a_prc_check_picks_up_the_actors_perception_proficiency() -> None:
    """The IR carries ``"prc"``; the sidecar is keyed ``"perception"``.

    WIS 14 (+2) at level 5 (PB +3), proficient in Perception → +5 on a
    Perception check. The 3-letter → slug translation is the handler's job.
    """
    payload = _f1d_payload(
        party=_f1d_party(wisdom=14, character_level=5, skill_proficiencies=("perception",))
    )
    events: list[Any] = []
    ctx = _f1d_ctx(payload, events)

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    assert _only_check(events).roll_total - 10 == 5


def test_an_unproficient_actor_gets_only_the_ability_modifier() -> None:
    payload = _f1d_payload(party=_f1d_party(wisdom=14, character_level=5))
    events: list[Any] = []
    ctx = _f1d_ctx(payload, events)

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    assert _only_check(events).roll_total - 10 == 2


def test_a_sidecar_keyed_by_the_legacy_3_letter_code_still_resolves() -> None:
    """Legacy fallback — a host-built sidecar keyed by code keeps working."""
    ctx, events = _ctx(check_modifiers={"char:hero": {"skills": {"prc": 7}}})

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    assert _only_check(events).roll_total == 10 + 7


def test_every_foundry_skill_code_maps_to_a_known_srd_slug() -> None:
    """The two skill tables must not drift apart."""
    assert set(_SKILL_CODE_TO_SLUG) == set(_SKILL_TO_ABILITY)
    for code, slug in _SKILL_CODE_TO_SLUG.items():
        assert SKILL_ABILITIES[slug] == _SCORE_ATTR[_SKILL_TO_ABILITY[code]]


# ---------------------------------------------------------------------------
# F2c — the check's D20 Test (``roll_d20_test``)
# ---------------------------------------------------------------------------


def test_the_check_reports_its_natural_modifier_and_sources() -> None:
    ctx, events = _ctx(forced_d20=11, check_modifiers={"char:hero": {"skills": {"perception": 4}}})

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    check = _only_check(events)
    assert (check.natural, check.modifier) == (11, 4)
    assert check.roll_total == check.natural + check.modifier
    assert check.advantage == "normal"
    assert check.sources == []


def test_a_check_with_no_disadvantage_draws_exactly_one_d20() -> None:
    """Determinism: the pre-F2c stream for an unflagged actor is unchanged."""
    ctx, events = _ctx(forced_d20=None)
    expected = random.Random(1).randint(1, 20)

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    assert _only_check(events).natural == expected


def test_condition_disadvantage_makes_the_actor_keep_the_lower_die() -> None:
    """SRD 5.2 §Frightened / §Poisoned — disadvantage on ability checks. The
    flag is projected by F1d and consumed here for the first time (F2c), so a
    flagged actor draws TWO dice."""
    ctx, events = _ctx(
        forced_d20=None,
        check_modifiers={"char:hero": {"ability_mods": {"wis": 0}, "disadvantage": True}},
    )
    rolls = random.Random(1)
    expected = min(rolls.randint(1, 20), rolls.randint(1, 20))

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    check = _only_check(events)
    assert check.natural == expected
    assert check.advantage == "disadvantage"
    assert check.sources == ["condition:attacker"]


def test_the_disadvantage_flag_is_scoped_to_the_rolling_actor() -> None:
    """An imposed check reads the flag off the TARGET that rolls, not the
    caster who applied it."""
    ctx, events = _ctx(
        forced_d20=None,
        targets=[_combatant("npc:bound")],
        check_modifiers={"char:hero": {"disadvantage": True}},
    )
    expected = random.Random(1).randint(1, 20)

    resolve_check(_activity(associated=["slt"], calculation="flat", formula="10"), ctx)

    check = _only_check(events)
    assert check.actor_id == "npc:bound"
    assert check.natural == expected
    assert check.advantage == "normal"
    assert check.sources == []


def test_a_forced_check_d20_bypasses_the_disadvantage_draw() -> None:
    ctx, events = _ctx(
        forced_d20=19,
        check_modifiers={"char:hero": {"disadvantage": True}},
    )
    expected_next = random.Random(1).randint(1, 20)

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    assert _only_check(events).natural == 19
    assert ctx.rng.randint(1, 20) == expected_next


def test_a_poisoned_pc_draws_two_dice_through_the_live_orchestrator() -> None:
    """End-to-end on the production path: SRD 5.2 §Poisoned — *"the creature
    has Disadvantage on attack rolls and ability checks"*. The condition is
    projected by the orchestrator (F1d), survives the hydration payload and
    ``build_activity_context``'s sidecar narrowing, and is consumed by the
    handler (F2c), so the actor draws TWO d20s and keeps the lower.

    """
    start = run_async(
        start_combat(
            session_id="f2c-check-poisoned",
            party=_f1d_party(wisdom=14, character_level=5),
            encounter=_f1d_foe(),
            scene_zones=single_zone(),
            rng_seed=1,
        )
    )
    live = _get_live(start.handle)
    actor = next(c for c in live.initiative if c.entity_id == "char:a")
    actor.conditions.append(
        ActiveCondition(condition="poisoned", source_entity_id="npc:abc123def456", scope="combat")
    )
    payload = _build_hydration_payload(live, caster=None)

    events: list[Any] = []
    ctx = build_activity_context(
        _combatant("char:a"),
        [],
        rng=random.Random(7),
        event_emitter=events.append,
        slot_level=None,
        base_spell_level=None,
        spellcasting_ability=None,
        concentration=False,
        source_passive_effects=[],
        spell_book={},
        passive_damage_modifiers=payload["passive_damage_modifiers"],
        save_modifiers=payload["save_modifiers"],
        check_modifiers=payload["check_modifiers"],
    )
    assert ctx.check_modifiers["char:a"]["disadvantage"] is True

    resolve_check(_activity(associated=["prc"], calculation="flat", formula="10"), ctx)

    rolls = random.Random(7)
    expected = min(rolls.randint(1, 20), rolls.randint(1, 20))
    check = _only_check(events)
    assert check.natural == expected
    assert check.modifier == 2  # WIS 14, not proficient in Perception
    assert check.roll_total == expected + 2
    assert check.advantage == "disadvantage"
    assert check.sources == ["condition:attacker"]
