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

from dnd5e_engine.activities.check import FORCE_CHECK_D20, resolve_check
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.events import CheckRolled
from dnd5e_engine.types.combat import Combatant

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
