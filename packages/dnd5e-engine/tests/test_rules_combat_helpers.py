"""Behavioral tests for ``dnd5e_engine.rules.combat_helpers``.

The module is the pure projection layer between raw MonsterTemplate/NPC
property bags (as a host reads them out of its own store) and the typed
combat records the orchestrator consumes. Every invariant asserted here is
one a host depends on:

- Templates arrive with ability scores / actions / resistance lists either as
  native Python or as JSON strings, depending on the store. Both shapes must
  project identically, and malformed JSON must degrade rather than raise —
  a template with a bad field must not abort combat start.
- ``attack_bonus`` on a seeded action wins over the CR-derived formula. The
  formula reads STR, so nimble attackers (SRD Goblin: STR 8, +4 scimitar)
  resolve far too low without the override.
- ``hp_max_override`` layering uses ``is not None``, so an explicit ``0``
  survives instead of silently falling back to template HP — that fallback
  would let the ``Combatant`` entry and the ``CombatNPC`` sidecar disagree
  about the same NPC.
- The death-save state machine implements SRD death saving throws, including
  nat 1 = two failures and damage-while-unconscious.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from dnd5e_engine.rules.combat_helpers import (
    DeathSaveState,
    build_combat_npc_from_template,
    build_combatant_from_npc,
    extract_template_combat_stats,
    health_descriptor,
    roll_and_sort_initiative,
)

# ---------------------------------------------------------------------------
# extract_template_combat_stats
# ---------------------------------------------------------------------------


def test_extract_defaults_when_template_is_empty() -> None:
    """An empty property bag must still yield a usable combatant: SRD-minimum
    values, never None or a KeyError at combat start."""
    stats = extract_template_combat_stats({})

    assert stats["ac"] == 10
    assert stats["hp"] == 1
    assert stats["xp_value"] == 0
    assert stats["challenge_rating"] == 0.0
    assert stats["damage_dice"] == "1d6"
    assert stats["damage_type"] == "bludgeoning"
    assert stats["has_ranged_attack"] is False
    assert stats["damage_resistances"] == []
    assert stats["damage_immunities"] == []
    # No ability scores -> every score defaults to 10.
    for ability in (
        "strength",
        "dexterity",
        "constitution",
        "wisdom",
        "intelligence",
        "charisma",
    ):
        assert stats[ability] == 10


def test_extract_reads_flat_numeric_fields() -> None:
    stats = extract_template_combat_stats(
        {"armor_class": 15, "hit_points": 33, "xp": 450, "challenge_rating": 2}
    )

    assert (stats["ac"], stats["hp"], stats["xp_value"]) == (15, 33, 450)
    assert stats["challenge_rating"] == 2.0


def test_extract_coerces_string_numerics() -> None:
    """Stores that stringify numbers must not produce str-typed combat stats."""
    stats = extract_template_combat_stats(
        {"armor_class": "15", "hit_points": "33", "xp": "450", "challenge_rating": "0.5"}
    )

    assert stats["ac"] == 15
    assert stats["hp"] == 33
    assert stats["xp_value"] == 450
    assert stats["challenge_rating"] == 0.5


def test_extract_accepts_ability_scores_as_json_string() -> None:
    native = extract_template_combat_stats(
        {"ability_scores": {"strength": 16, "dexterity": 14, "constitution": 15}}
    )
    encoded = extract_template_combat_stats(
        {"ability_scores": '{"strength": 16, "dexterity": 14, "constitution": 15}'}
    )

    assert native == encoded
    assert encoded["strength"] == 16
    assert encoded["dexterity"] == 14
    assert encoded["constitution"] == 15


def test_extract_accepts_abbreviated_ability_keys() -> None:
    """Some templates carry `str`/`dex`/... rather than full names."""
    stats = extract_template_combat_stats(
        {"ability_scores": {"str": 18, "dex": 8, "con": 16, "wis": 12, "int": 6, "cha": 5}}
    )

    assert stats["strength"] == 18
    assert stats["dexterity"] == 8
    assert stats["constitution"] == 16
    assert stats["wisdom"] == 12
    assert stats["intelligence"] == 6
    assert stats["charisma"] == 5


def test_extract_malformed_ability_scores_fall_back_to_defaults() -> None:
    """Bad JSON must degrade to defaults, not raise mid combat-start."""
    stats = extract_template_combat_stats({"ability_scores": "{not json"})

    assert stats["strength"] == 10
    assert stats["dexterity"] == 10


def test_extract_attack_bonus_derived_from_cr_and_strength() -> None:
    """With no per-action attack_bonus, the formula is STR mod + CR-derived
    proficiency (min +2)."""
    stats = extract_template_combat_stats(
        {"challenge_rating": 5, "ability_scores": {"strength": 18}}
    )

    # STR 18 -> +4; proficiency = max(2, 5//4 + 2) = 3
    assert stats["attack_bonus"] == 7


def test_extract_proficiency_floor_is_two_at_low_cr() -> None:
    stats = extract_template_combat_stats(
        {"challenge_rating": 0.25, "ability_scores": {"strength": 10}}
    )

    assert stats["attack_bonus"] == 2


def test_extract_action_attack_bonus_overrides_the_formula() -> None:
    """SRD Goblin regression: STR 8 makes the CR formula produce +1, but the
    seeded scimitar action states +4. The stated value must win."""
    stats = extract_template_combat_stats(
        {
            "challenge_rating": 0.25,
            "ability_scores": {"strength": 8, "dexterity": 14},
            "actions": [
                {
                    "name": "Scimitar",
                    "attack_bonus": 4,
                    "attack_type": "Melee Weapon Attack",
                    "damage": [{"damage_dice": "1d6+2", "damage_type": {"name": "Slashing"}}],
                }
            ],
        }
    )

    assert stats["attack_bonus"] == 4
    assert stats["damage_dice"] == "1d6+2"
    assert stats["damage_type"] == "slashing"


def test_extract_non_integer_action_attack_bonus_is_ignored() -> None:
    """Only a sane int overrides the formula — a stringified bonus falls back."""
    stats = extract_template_combat_stats(
        {
            "challenge_rating": 0.25,
            "ability_scores": {"strength": 8},
            "actions": [{"attack_bonus": "+4"}],
        }
    )

    # STR 8 -> -1, proficiency +2
    assert stats["attack_bonus"] == 1


def test_extract_reads_actions_from_json_string() -> None:
    stats = extract_template_combat_stats(
        {
            "actions": (
                '[{"attack_bonus": 6, "attack_type": "Ranged Weapon Attack", '
                '"damage": [{"damage_dice": "2d6", "damage_type": {"name": "Piercing"}}]}]'
            )
        }
    )

    assert stats["attack_bonus"] == 6
    assert stats["damage_dice"] == "2d6"
    assert stats["damage_type"] == "piercing"
    assert stats["has_ranged_attack"] is True


def test_extract_malformed_actions_fall_back_to_default_attack() -> None:
    stats = extract_template_combat_stats({"actions": "[[[", "ability_scores": {"strength": 10}})

    assert stats["damage_dice"] == "1d6"
    assert stats["damage_type"] == "bludgeoning"
    assert stats["attack_bonus"] == 2


def test_extract_only_first_action_is_used() -> None:
    """The projection deliberately reads the first action only — a second
    ranged action must not flip has_ranged_attack for a melee brute."""
    stats = extract_template_combat_stats(
        {
            "actions": [
                {
                    "attack_bonus": 5,
                    "attack_type": "Melee Weapon Attack",
                    "damage": [{"damage_dice": "1d12", "damage_type": {"name": "Slashing"}}],
                },
                {
                    "attack_bonus": 9,
                    "attack_type": "Ranged Weapon Attack",
                    "damage": [{"damage_dice": "3d8", "damage_type": {"name": "Fire"}}],
                },
            ]
        }
    )

    assert stats["attack_bonus"] == 5
    assert stats["damage_dice"] == "1d12"
    assert stats["has_ranged_attack"] is False


def test_extract_skips_non_dict_actions() -> None:
    """A malformed leading entry must not crash or be treated as an attack."""
    stats = extract_template_combat_stats(
        {
            "ability_scores": {"strength": 10},
            "actions": ["Multiattack", {"attack_bonus": 7}],
        }
    )

    assert stats["attack_bonus"] == 7


def test_extract_damage_as_json_string_within_action() -> None:
    stats = extract_template_combat_stats(
        {"actions": [{"damage": '[{"damage_dice": "1d8", "damage_type": {"name": "Cold"}}]'}]}
    )

    assert stats["damage_dice"] == "1d8"
    assert stats["damage_type"] == "cold"


def test_extract_malformed_damage_keeps_defaults() -> None:
    stats = extract_template_combat_stats({"actions": [{"damage": "not-json"}]})

    assert stats["damage_dice"] == "1d6"
    assert stats["damage_type"] == "bludgeoning"


def test_extract_plain_string_damage_type_is_lowercased() -> None:
    stats = extract_template_combat_stats(
        {"actions": [{"damage": [{"damage_dice": "1d4", "damage_type": "Acid"}]}]}
    )

    assert stats["damage_type"] == "acid"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["fire", "cold"], ["fire", "cold"]),
        ('["fire", "cold"]', ["fire", "cold"]),
        ("not-json", []),
        ('{"fire": true}', []),  # valid JSON but not a list
        (None, []),
        (42, []),
        ([1, 2], ["1", "2"]),  # coerced to str
    ],
)
def test_extract_resistance_list_parsing(raw: Any, expected: list[str]) -> None:
    """Resistance/immunity lists arrive native or JSON-encoded; anything else
    degrades to an empty list rather than raising."""
    stats = extract_template_combat_stats({"damage_resistances": raw, "damage_immunities": raw})

    assert stats["damage_resistances"] == expected
    assert stats["damage_immunities"] == expected


# ---------------------------------------------------------------------------
# health_descriptor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hp_current,hp_max,expected",
    [
        (10, 10, "Healthy"),
        (5, 10, "Healthy"),  # exactly 50% is still Healthy
        (4, 10, "Bloodied"),
        (25, 100, "Bloodied"),  # exactly 25% is still Bloodied
        (24, 100, "Near death"),
        (1, 100, "Near death"),
        (0, 10, "Dead"),
        (-5, 10, "Dead"),  # overkill damage
        (5, 0, "Dead"),  # zero-max template guards against ZeroDivisionError
    ],
)
def test_health_descriptor_thresholds(hp_current: int, hp_max: int, expected: str) -> None:
    assert health_descriptor(hp_current, hp_max) == expected


# ---------------------------------------------------------------------------
# roll_and_sort_initiative
# ---------------------------------------------------------------------------


def test_initiative_returns_descending_order_with_all_combatants() -> None:
    random.seed(20)
    combatants = [
        {"entity_id": f"npc:{i}", "name": f"NPC {i}", "dexterity": 10, "entity_type": "NPC"}
        for i in range(8)
    ]

    result = roll_and_sort_initiative(combatants)

    assert len(result) == len(combatants)
    assert {e["entity_id"] for e in result} == {c["entity_id"] for c in combatants}
    initiatives = [e["initiative"] for e in result]
    assert initiatives == sorted(initiatives, reverse=True)


def test_initiative_adds_dex_modifier_and_keeps_input_fields() -> None:
    random.seed(1)
    result = roll_and_sort_initiative(
        [{"entity_id": "char:a", "name": "Rogue", "dexterity": 18, "entity_type": "Character"}]
    )

    entry = result[0]
    assert entry["dex_modifier"] == 4
    assert entry["name"] == "Rogue"
    assert entry["entity_type"] == "Character"
    # d20 + 4 -> within [5, 24]
    assert 5 <= entry["initiative"] <= 24


def test_initiative_does_not_leak_the_tiebreak_field() -> None:
    """`_tiebreak` is an internal sort key; leaking it would end up serialized
    into host state."""
    random.seed(3)
    result = roll_and_sort_initiative(
        [{"entity_id": "npc:a", "name": "A", "dexterity": 10, "entity_type": "NPC"}]
    )

    assert "_tiebreak" not in result[0]


def test_initiative_does_not_mutate_the_input_dicts() -> None:
    random.seed(7)
    original = {"entity_id": "npc:a", "name": "A", "dexterity": 12, "entity_type": "NPC"}

    roll_and_sort_initiative([original])

    assert original == {
        "entity_id": "npc:a",
        "name": "A",
        "dexterity": 12,
        "entity_type": "NPC",
    }


def test_initiative_defaults_missing_dexterity_to_ten() -> None:
    random.seed(11)
    result = roll_and_sort_initiative([{"entity_id": "npc:a", "name": "A", "entity_type": "NPC"}])

    assert result[0]["dex_modifier"] == 0


def test_initiative_breaks_ties_by_dex_modifier() -> None:
    """When the d20s land equal, the higher DEX modifier must go first. Seeding
    the RNG makes the tie reproducible."""
    high_dex_first = 0
    trials = 40
    for seed in range(trials):
        random.seed(seed)
        result = roll_and_sort_initiative(
            [
                {"entity_id": "npc:low", "name": "Low", "dexterity": 6, "entity_type": "NPC"},
                {"entity_id": "npc:high", "name": "High", "dexterity": 20, "entity_type": "NPC"},
            ]
        )
        # Wherever the totals tie, DEX must decide.
        if result[0]["initiative"] == result[1]["initiative"]:
            assert result[0]["dex_modifier"] >= result[1]["dex_modifier"]
        if result[0]["entity_id"] == "npc:high":
            high_dex_first += 1

    # Sanity: the +5 DEX combatant wins the majority of the time.
    assert high_dex_first > trials // 2


def test_initiative_of_empty_roster_is_empty() -> None:
    assert roll_and_sort_initiative([]) == []


# ---------------------------------------------------------------------------
# DeathSaveState
# ---------------------------------------------------------------------------


def test_death_save_nat20_reports_critical_success_without_counting() -> None:
    """A nat 20 regains 1 HP; counters are irrelevant and must not advance."""
    state = DeathSaveState(successes=1, failures=2)

    assert state.apply_save(success=True, is_critical=True) == "critical_success"
    assert (state.successes, state.failures) == (1, 2)


def test_death_save_three_successes_stabilize() -> None:
    state = DeathSaveState()

    assert state.apply_save(success=True, is_critical=False) == "ongoing"
    assert state.apply_save(success=True, is_critical=False) == "ongoing"
    assert state.apply_save(success=True, is_critical=False) == "stabilized"
    assert state.is_stable is True


def test_death_save_three_failures_kill() -> None:
    state = DeathSaveState()

    assert state.apply_save(success=False, is_critical=False) == "ongoing"
    assert state.apply_save(success=False, is_critical=False) == "ongoing"
    assert state.apply_save(success=False, is_critical=False) == "dead"


def test_death_save_nat1_counts_as_two_failures() -> None:
    state = DeathSaveState()

    assert state.apply_save(success=False, is_critical=True) == "ongoing"
    assert state.failures == 2
    # One more ordinary failure reaches three.
    assert state.apply_save(success=False, is_critical=False) == "dead"


def test_death_save_nat1_from_one_failure_is_immediately_lethal() -> None:
    state = DeathSaveState(failures=1)

    assert state.apply_save(success=False, is_critical=True) == "dead"
    assert state.failures == 3


def test_death_save_failure_takes_priority_over_stabilizing() -> None:
    """At 2 successes and 2 failures a final failure kills — the death check
    runs before the stabilize check."""
    state = DeathSaveState(successes=2, failures=2)

    assert state.apply_save(success=False, is_critical=False) == "dead"
    assert state.is_stable is False


def test_damage_while_unconscious_is_one_failure() -> None:
    state = DeathSaveState()

    assert state.apply_damage_while_unconscious(is_melee_within_5ft=False) == "ongoing"
    assert state.failures == 1


def test_melee_damage_within_5ft_is_an_auto_crit_worth_two_failures() -> None:
    state = DeathSaveState()

    assert state.apply_damage_while_unconscious(is_melee_within_5ft=True) == "ongoing"
    assert state.failures == 2
    assert state.apply_damage_while_unconscious(is_melee_within_5ft=True) == "dead"


def test_death_save_reset_clears_all_state() -> None:
    state = DeathSaveState(successes=3, failures=2, is_stable=True)

    state.reset()

    assert (state.successes, state.failures, state.is_stable) == (0, 0, False)


def test_death_save_round_trips_through_dict() -> None:
    state = DeathSaveState(successes=2, failures=1, is_stable=False)

    restored = DeathSaveState.from_dict(state.to_dict())

    assert restored == state


def test_death_save_from_dict_tolerates_missing_keys() -> None:
    """Legacy Redis payloads predate some fields; defaults must apply."""
    restored = DeathSaveState.from_dict({})

    assert (restored.successes, restored.failures, restored.is_stable) == (0, 0, False)


# ---------------------------------------------------------------------------
# build_combatant_from_npc
# ---------------------------------------------------------------------------


def _template(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "tpl:bandit",
        "armor_class": 12,
        "hit_points": 11,
        "challenge_rating": 0.125,
        "ability_scores": {
            "strength": 11,
            "dexterity": 12,
            "constitution": 12,
            "wisdom": 10,
            "intelligence": 10,
            "charisma": 10,
        },
        "actions": [
            {
                "attack_bonus": 3,
                "attack_type": "Melee Weapon Attack",
                "damage": [{"damage_dice": "1d6+1", "damage_type": {"name": "Slashing"}}],
            }
        ],
    }
    base.update(overrides)
    return base


def test_build_combatant_projects_template_stats() -> None:
    combatant = build_combatant_from_npc(
        {"id": "npc:abc123def456", "name": "Bandit Captain"}, _template()
    )

    assert combatant["entity_id"] == "npc:abc123def456"
    assert combatant["entity_type"] == "NPC"
    assert combatant["name"] == "Bandit Captain"
    assert combatant["ac"] == 12
    assert combatant["attack_bonus"] == 3
    assert combatant["damage_dice"] == "1d6+1"
    assert combatant["damage_type"] == "slashing"
    assert combatant["dexterity"] == 12
    # Caller runs initiative separately.
    assert "initiative" not in combatant


def test_build_combatant_starts_at_full_template_hp() -> None:
    """Combat HP is ephemeral — NPCs always enter combat at full HP."""
    combatant = build_combatant_from_npc({"id": "npc:a", "name": "A"}, _template())

    assert combatant["hp_max"] == 11
    assert combatant["hp_current"] == 11


def test_build_combatant_hp_max_override_wins() -> None:
    combatant = build_combatant_from_npc(
        {"id": "npc:a", "name": "A"}, _template(), overrides={"hp_max_override": 42}
    )

    assert combatant["hp_max"] == 42
    assert combatant["hp_current"] == 42


def test_build_combatant_default_behavior_profile_is_defensive() -> None:
    combatant = build_combatant_from_npc({"id": "npc:a", "name": "A"}, _template())

    assert combatant["behavior_profile"] == "DEFENSIVE"


def test_build_combatant_behavior_profile_override_wins() -> None:
    combatant = build_combatant_from_npc(
        {"id": "npc:a", "name": "A"},
        _template(),
        overrides={"behavior_profile": "AGGRESSIVE"},
    )

    assert combatant["behavior_profile"] == "AGGRESSIVE"


def test_build_combatant_tolerates_missing_name() -> None:
    combatant = build_combatant_from_npc({"id": "npc:a"}, _template())

    assert combatant["name"] == ""


def test_build_combatant_accepts_none_overrides() -> None:
    """Legacy graph state carries no combat_overrides at all."""
    combatant = build_combatant_from_npc({"id": "npc:a", "name": "A"}, _template(), overrides=None)

    assert combatant["hp_max"] == 11
    assert combatant["behavior_profile"] == "DEFENSIVE"


# ---------------------------------------------------------------------------
# build_combat_npc_from_template
# ---------------------------------------------------------------------------


def test_build_combat_npc_carries_template_and_ability_detail() -> None:
    npc = build_combat_npc_from_template(
        {"id": "npc:abc123def456", "name": "Bandit"},
        _template(damage_resistances=["fire"], damage_immunities='["poison"]'),
    )

    assert npc.npc_id == "npc:abc123def456"
    assert npc.template_id == "tpl:bandit"
    assert npc.name == "Bandit"
    assert npc.ac == 12
    assert npc.attack_bonus == 3
    assert npc.constitution == 12
    assert npc.damage_resistances == ["fire"]
    assert npc.damage_immunities == ["poison"]
    assert npc.is_alive is True


def test_build_combat_npc_defaults_name_when_absent() -> None:
    npc = build_combat_npc_from_template({"id": "npc:a"}, _template())

    assert npc.name == "NPC"


def test_build_combat_npc_zero_hp_override_survives() -> None:
    """Regression: `0 or template_hp` would silently restore template HP and
    let the sidecar disagree with the initiative entry about the same NPC."""
    npc = build_combat_npc_from_template(
        {"id": "npc:a", "name": "A"}, _template(), {"hp_max_override": 0}
    )

    assert npc.hp_max == 0
    assert npc.hp_current == 0


def test_sidecar_and_combatant_agree_on_hp_under_override() -> None:
    overrides = {"hp_max_override": 0}
    npc_props = {"id": "npc:a", "name": "A"}

    combatant = build_combatant_from_npc(npc_props, _template(), overrides=overrides)
    sidecar = build_combat_npc_from_template(npc_props, _template(), overrides)

    assert combatant["hp_max"] == sidecar.hp_max
    assert combatant["hp_current"] == sidecar.hp_current


def test_build_combat_npc_behavior_profile_override_wins() -> None:
    npc = build_combat_npc_from_template(
        {"id": "npc:a", "name": "A"}, _template(), {"behavior_profile": "COWARDLY"}
    )

    assert npc.behavior_profile == "COWARDLY"


def test_build_combat_npc_defaults_behavior_profile_to_defensive() -> None:
    npc = build_combat_npc_from_template({"id": "npc:a", "name": "A"}, _template())

    assert npc.behavior_profile == "DEFENSIVE"
