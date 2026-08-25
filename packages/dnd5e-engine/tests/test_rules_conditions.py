"""Behavioral tests for ``dnd5e_engine.rules.conditions``.

The SRD condition rules this module encodes are the ones combat resolution
reads on every roll, so the assertions target the rules rather than the data
structures:

- Implication: Unconscious *is* Incapacitated and Prone. Anything that asks
  "is this creature incapacitated?" must say yes for an unconscious creature
  even though only "unconscious" was applied.
- Advantage/disadvantage: attacking an unconscious/paralyzed/stunned/blinded
  target grants advantage; being blinded/poisoned/frightened/restrained
  imposes disadvantage; the two combine independently (the caller reconciles).
- The sidecar projections are what the orchestrator hydrates before running
  the per-effect handlers — a wrong ability code or a missing ``"all"``
  marker silently drops a condition's mechanical effect.
"""

from __future__ import annotations

import pytest

from dnd5e_engine.rules.conditions import (
    CONDITION_EFFECTS,
    CONDITION_IMPLIES,
    Condition,
    active_condition_names,
    apply_condition,
    apply_condition_with_implies,
    check_immunity,
    conditions_grant_advantage_on_attack,
    conditions_grant_disadvantage_on_ability_checks,
    get_condition_effects,
    is_condition_active,
    project_passive_check_modifiers,
    project_passive_damage_modifiers,
    project_passive_save_modifiers,
    remove_condition,
    remove_condition_with_implies,
)
from dnd5e_engine.types.conditions import ActiveCondition

SOURCE = "npc:abc123def456"


def _active(condition: str, source: str = SOURCE, **kwargs: object) -> ActiveCondition:
    return ActiveCondition(condition=condition, source_entity_id=source, scope="combat", **kwargs)


# ---------------------------------------------------------------------------
# is_condition_active
# ---------------------------------------------------------------------------


def test_direct_condition_is_active() -> None:
    assert is_condition_active(Condition.POISONED, ["poisoned"]) is True


def test_absent_condition_is_not_active() -> None:
    assert is_condition_active(Condition.POISONED, ["prone"]) is False


def test_condition_matching_is_case_insensitive() -> None:
    assert is_condition_active(Condition.STUNNED, ["Stunned"]) is True


@pytest.mark.parametrize(
    "applied,implied",
    [
        ("paralyzed", Condition.INCAPACITATED),
        ("petrified", Condition.INCAPACITATED),
        ("stunned", Condition.INCAPACITATED),
        ("unconscious", Condition.INCAPACITATED),
        ("unconscious", Condition.PRONE),
    ],
)
def test_implied_conditions_read_as_active(applied: str, implied: Condition) -> None:
    """A creature that is only tagged 'unconscious' is still incapacitated
    and prone for every rule that checks those."""
    assert is_condition_active(implied, [applied]) is True


def test_implication_does_not_run_backwards() -> None:
    """Being incapacitated does not make a creature unconscious."""
    assert is_condition_active(Condition.UNCONSCIOUS, ["incapacitated"]) is False


def test_prone_is_not_implied_by_paralysis() -> None:
    """Only Unconscious knocks a creature prone — paralysis leaves it standing."""
    assert is_condition_active(Condition.PRONE, ["paralyzed"]) is False


def test_empty_condition_list_is_never_active() -> None:
    assert is_condition_active(Condition.BLINDED, []) is False


# ---------------------------------------------------------------------------
# apply / remove (string list form)
# ---------------------------------------------------------------------------


def test_apply_condition_appends() -> None:
    assert apply_condition(Condition.PRONE, ["poisoned"]) == ["poisoned", "prone"]


def test_apply_condition_is_idempotent() -> None:
    existing = ["prone"]

    assert apply_condition(Condition.PRONE, existing) == ["prone"]


def test_apply_condition_does_not_mutate_the_input() -> None:
    existing = ["poisoned"]

    apply_condition(Condition.PRONE, existing)

    assert existing == ["poisoned"]


def test_remove_condition_drops_matching_entries_case_insensitively() -> None:
    assert remove_condition(Condition.PRONE, ["Prone", "poisoned"]) == ["poisoned"]


def test_remove_condition_absent_is_a_no_op() -> None:
    assert remove_condition(Condition.PRONE, ["poisoned"]) == ["poisoned"]


# ---------------------------------------------------------------------------
# Condition effect text
# ---------------------------------------------------------------------------


def test_every_condition_has_effect_text() -> None:
    """The effects table drives player-facing descriptions; a missing entry
    would render a condition as having no effect at all."""
    for condition in Condition:
        assert CONDITION_EFFECTS.get(condition), f"{condition.value} has no effect text"


def test_get_condition_effects_returns_the_table_entry() -> None:
    effects = get_condition_effects(Condition.RESTRAINED)

    assert "Speed becomes 0" in effects


def test_exhaustion_describes_the_srd_52_scaling_rule() -> None:
    """SRD 5.2 replaced the 2014 six-tier ladder with two per-level penalties
    (D20 Tests -2 x level, Speed -5 ft x level) and death at level 6."""
    text = " ".join(get_condition_effects(Condition.EXHAUSTION)).lower()
    assert "d20 test" in text
    assert "speed" in text
    assert "level 6" in text
    assert "death" in text
    assert "halved" not in text  # the 2014 wording


def test_implied_table_only_references_real_conditions() -> None:
    for root, implied in CONDITION_IMPLIES.items():
        assert isinstance(root, Condition)
        assert all(isinstance(c, Condition) for c in implied)


# ---------------------------------------------------------------------------
# check_immunity
# ---------------------------------------------------------------------------


def test_check_immunity_hit_and_miss() -> None:
    assert check_immunity("poisoned", ["poisoned", "charmed"]) is True
    assert check_immunity("stunned", ["poisoned"]) is False
    assert check_immunity("poisoned", []) is False


# ---------------------------------------------------------------------------
# Ability-check and attack modifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "conditions,expected",
    [
        (["exhaustion"], True),
        (["poisoned"], True),
        (["prone"], False),
        ([], False),
    ],
)
def test_disadvantage_on_ability_checks(conditions: list[str], expected: bool) -> None:
    assert conditions_grant_disadvantage_on_ability_checks(conditions) is expected


def test_invisible_attacker_has_advantage() -> None:
    advantage, disadvantage = conditions_grant_advantage_on_attack(["invisible"], [])

    assert (advantage, disadvantage) == (True, False)


@pytest.mark.parametrize("condition", ["blinded", "poisoned", "frightened", "restrained"])
def test_attacker_conditions_impose_disadvantage(condition: str) -> None:
    advantage, disadvantage = conditions_grant_advantage_on_attack([condition], [])

    assert disadvantage is True
    assert advantage is False


@pytest.mark.parametrize("condition", ["paralyzed", "stunned", "unconscious", "blinded"])
def test_target_conditions_grant_the_attacker_advantage(condition: str) -> None:
    advantage, disadvantage = conditions_grant_advantage_on_attack([], [condition])

    assert advantage is True
    assert disadvantage is False


def test_advantage_and_disadvantage_are_reported_independently() -> None:
    """A poisoned attacker swinging at an unconscious target has both; the
    caller reconciles them into a flat roll."""
    advantage, disadvantage = conditions_grant_advantage_on_attack(["poisoned"], ["unconscious"])

    assert (advantage, disadvantage) == (True, True)


def test_no_conditions_means_a_flat_roll() -> None:
    assert conditions_grant_advantage_on_attack([], []) == (False, False)


# ---------------------------------------------------------------------------
# Structured (ActiveCondition) application
# ---------------------------------------------------------------------------


def test_active_condition_names_projects_to_strings() -> None:
    conditions = [_active("poisoned"), _active("prone")]

    assert active_condition_names(conditions) == ["poisoned", "prone"]


def test_apply_with_implies_adds_root_and_implied_entries() -> None:
    result = apply_condition_with_implies(Condition.UNCONSCIOUS, SOURCE, "combat", [])

    by_name = {c.condition: c for c in result}
    assert set(by_name) == {"unconscious", "incapacitated", "prone"}
    assert by_name["unconscious"].source_entity_id == SOURCE
    assert by_name["incapacitated"].source_entity_id == "implied:unconscious"
    assert by_name["prone"].source_entity_id == "implied:unconscious"


def test_apply_with_implies_carries_duration_and_dc_on_the_root_only() -> None:
    result = apply_condition_with_implies(
        Condition.STUNNED,
        SOURCE,
        "combat",
        [],
        duration_rounds=3,
        save_dc=15,
        applied_round=2,
        source_effect_id="fx:abc123def456",
    )

    root = next(c for c in result if c.condition == "stunned")
    implied = next(c for c in result if c.condition == "incapacitated")

    assert (root.duration_rounds, root.save_dc, root.source_effect_id) == (3, 15, "fx:abc123def456")
    # Implied entries carry no effect link or duration of their own — they are
    # cleaned up with the root.
    assert implied.duration_rounds is None
    assert implied.source_effect_id is None
    assert implied.applied_round == 2


def test_apply_with_implies_is_idempotent_per_condition_name() -> None:
    first = apply_condition_with_implies(Condition.PARALYZED, SOURCE, "combat", [])
    second = apply_condition_with_implies(Condition.PARALYZED, SOURCE, "combat", first)

    assert len(second) == len(first)
    assert [c.condition for c in second] == [c.condition for c in first]


def test_apply_with_implies_keeps_an_existing_root_from_another_source() -> None:
    """Re-applying must not duplicate or re-source an entry already present."""
    existing = [_active("incapacitated", source="npc:fff111222333")]

    result = apply_condition_with_implies(Condition.STUNNED, SOURCE, "combat", existing)

    incapacitated = [c for c in result if c.condition == "incapacitated"]
    assert len(incapacitated) == 1
    assert incapacitated[0].source_entity_id == "npc:fff111222333"


def test_apply_with_implies_preserves_unrelated_conditions() -> None:
    existing = [_active("poisoned")]

    result = apply_condition_with_implies(Condition.PRONE, SOURCE, "combat", existing)

    assert {c.condition for c in result} == {"poisoned", "prone"}


def test_apply_condition_without_implications_adds_only_itself() -> None:
    result = apply_condition_with_implies(Condition.POISONED, SOURCE, "combat", [])

    assert [c.condition for c in result] == ["poisoned"]


def test_exhaustion_level_is_carried_through() -> None:
    result = apply_condition_with_implies(
        Condition.EXHAUSTION, SOURCE, "session", [], exhaustion_level=3
    )

    assert result[0].exhaustion_level == 3
    assert result[0].scope == "session"


# ---------------------------------------------------------------------------
# Structured removal
# ---------------------------------------------------------------------------


def test_remove_with_implies_clears_the_root_and_its_implied_entries() -> None:
    applied = apply_condition_with_implies(Condition.UNCONSCIOUS, SOURCE, "combat", [])

    result = remove_condition_with_implies(Condition.UNCONSCIOUS, applied)

    assert result == []


def test_remove_with_implies_keeps_independently_sourced_conditions() -> None:
    """Prone applied on its own must survive waking up — it was not implied
    by the unconscious condition."""
    conditions = [
        *apply_condition_with_implies(Condition.UNCONSCIOUS, SOURCE, "combat", []),
    ]
    # Re-tag prone as independently applied.
    conditions = [c for c in conditions if c.condition != "prone"] + [_active("prone")]

    result = remove_condition_with_implies(Condition.UNCONSCIOUS, conditions)

    assert [c.condition for c in result] == ["prone"]


def test_remove_with_implies_leaves_unrelated_conditions() -> None:
    conditions = [
        _active("poisoned"),
        *apply_condition_with_implies(Condition.STUNNED, SOURCE, "combat", []),
    ]

    result = remove_condition_with_implies(Condition.STUNNED, conditions)

    assert [c.condition for c in result] == ["poisoned"]


def test_remove_with_implies_of_an_absent_condition_is_a_no_op() -> None:
    conditions = [_active("poisoned")]

    assert remove_condition_with_implies(Condition.STUNNED, conditions) == conditions


# ---------------------------------------------------------------------------
# Sidecar projections
# ---------------------------------------------------------------------------


def test_petrified_projects_blanket_resistance_and_poison_immunity() -> None:
    out = project_passive_damage_modifiers(["petrified"])

    assert out["resistances"] == ["all"]
    assert out["immunities"] == ["poison"]
    assert out["vulnerabilities"] == []


def test_damage_projection_is_empty_for_other_conditions() -> None:
    out = project_passive_damage_modifiers(["prone", "poisoned"])

    assert out == {"resistances": [], "vulnerabilities": [], "immunities": []}


def test_damage_projection_is_case_insensitive() -> None:
    assert project_passive_damage_modifiers(["Petrified"])["resistances"] == ["all"]


def test_restrained_projects_dex_save_disadvantage_only() -> None:
    out = project_passive_save_modifiers(["restrained"])

    assert out["passive_save_dis"] == ["DEX"]
    assert out["passive_save_auto_fail"] == []
    assert out["passive_save_adv"] == []


@pytest.mark.parametrize("condition", ["paralyzed", "stunned", "petrified", "unconscious"])
def test_helpless_conditions_auto_fail_strength_and_dexterity_saves(condition: str) -> None:
    out = project_passive_save_modifiers([condition])

    assert out["passive_save_auto_fail"] == ["STR", "DEX"]
    # Disadvantage is kept as a fallback for handlers without the short-circuit.
    assert set(out["passive_save_dis"]) == {"STR", "DEX"}


def test_restrained_and_paralyzed_do_not_duplicate_the_dex_entry() -> None:
    out = project_passive_save_modifiers(["restrained", "paralyzed"])

    assert out["passive_save_dis"].count("DEX") == 1


def test_save_projection_is_empty_without_relevant_conditions() -> None:
    out = project_passive_save_modifiers(["poisoned", "prone"])

    assert out == {
        "passive_save_adv": [],
        "passive_save_dis": [],
        "passive_save_auto_fail": [],
    }


@pytest.mark.parametrize("condition", ["frightened", "poisoned", "exhaustion"])
def test_check_projection_marks_blanket_disadvantage(condition: str) -> None:
    out = project_passive_check_modifiers([condition])

    assert out["passive_check_dis"] == ["all"]
    assert out["passive_check_adv"] == []


def test_check_projection_does_not_stack_the_marker() -> None:
    out = project_passive_check_modifiers(["frightened", "poisoned", "exhaustion"])

    assert out["passive_check_dis"] == ["all"]


def test_check_projection_is_empty_for_unrelated_conditions() -> None:
    out = project_passive_check_modifiers(["prone", "restrained"])

    assert out == {"passive_check_adv": [], "passive_check_dis": []}
