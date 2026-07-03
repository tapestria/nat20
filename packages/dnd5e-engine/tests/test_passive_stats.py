"""Unit tests for the pure passive-stat interpreter.

Exercises the allowlist (trait_grants + Foundry change-keys → typed derived
stats), the deferred-key handling (movement / ci / languages → skipped_keys),
sense mode semantics (mode 4 = max, mode 2 = add), and species-senses merge.
The interpreter is PURE — it never logs or raises; allowlist misses and
non-literal values land in ``skipped_keys`` for the seam to log.
"""

from dnd5e_srd_data.schema.common import PassiveEffectChange, Senses

from dnd5e_engine.activities.passive_stats import (
    CombatantMovementModes,
    CombatantSenses,
    DerivedPassiveStats,
    interpret_passive_stats,
)


def test_species_trait_grant_dr_to_resistance():
    out = interpret_passive_stats(changes=[], trait_grants=["dr:poison"], species_senses=None)
    assert isinstance(out, DerivedPassiveStats)
    assert "poison" in out.resistances


def test_species_trait_grant_di_to_immunity():
    out = interpret_passive_stats(changes=[], trait_grants=["di:fire"], species_senses=None)
    assert "fire" in out.immunities


def test_senses_change_sets_darkvision_max():
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.senses.darkvision", mode=4, value="120")
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.senses.darkvision == 120


def test_senses_change_mode_add_accumulates():
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.senses.tremorsense", mode=2, value="30"),
            PassiveEffectChange(key="system.attributes.senses.tremorsense", mode=2, value="30"),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.senses.tremorsense == 60


def test_species_senses_merge_max_with_change():
    # species darkvision 60 + a feature upgrade to 120 → 120 (max wins)
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.senses.darkvision", mode=4, value="120")
        ],
        trait_grants=[],
        species_senses=Senses(darkvision=60),
    )
    assert out.senses.darkvision == 120


def test_species_senses_alone_project():
    out = interpret_passive_stats(changes=[], trait_grants=[], species_senses=Senses(darkvision=60))
    assert out.senses.darkvision == 60
    assert out.senses.blindsight is None


def test_unknown_bonus_key_goes_to_skipped_not_raised():
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.bonuses.mwak.damage", mode=2, value="+2"),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.resistances == ()
    assert out.senses.darkvision is None
    assert "system.bonuses.mwak.damage" in out.skipped_keys


def test_non_literal_sense_value_skipped():
    # a symbolic @scale value is not a numeric literal -> skipped, not crashed
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(
                key="system.attributes.senses.darkvision", mode=4, value="@scale.foo.bar"
            )
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.senses.darkvision is None
    assert "system.attributes.senses.darkvision" in out.skipped_keys


def test_ci_and_languages_trait_grants_skipped():
    out = interpret_passive_stats(
        changes=[],
        trait_grants=["ci:poison", "languages:standard:dwarvish"],
        species_senses=None,
    )
    assert "ci:poison" in out.skipped_keys
    assert "languages:standard:dwarvish" in out.skipped_keys
    assert out.resistances == ()


def test_dr_change_key_projects_resistance():
    out = interpret_passive_stats(
        changes=[PassiveEffectChange(key="system.traits.dr.value", mode=2, value="slashing")],
        trait_grants=[],
        species_senses=None,
    )
    assert "slashing" in out.resistances


def test_ci_change_key_projects_condition_immunity_with_quote_stripped():
    # C08-S02: ci is now projected. The quote-escaped Foundry token "poison" is
    # stripped AND normalized to the condition slug "poisoned" (the sole
    # irregular ci token); it lands in condition_immunities, not resistances,
    # and does not go to skipped_keys.
    out = interpret_passive_stats(
        changes=[PassiveEffectChange(key="system.traits.ci.value", mode=2, value='"poison"')],
        trait_grants=[],
        species_senses=None,
    )
    assert out.condition_immunities == ("poisoned",)
    assert out.resistances == ()
    assert "system.traits.ci.value" not in out.skipped_keys


def test_ci_change_key_non_poison_token_passes_through_unmapped():
    # A ci token that already equals its condition slug is stored verbatim.
    out = interpret_passive_stats(
        changes=[PassiveEffectChange(key="system.traits.ci.value", mode=2, value="frightened")],
        trait_grants=[],
        species_senses=None,
    )
    assert out.condition_immunities == ("frightened",)


def test_di_change_key_projects_immunity():
    out = interpret_passive_stats(
        changes=[PassiveEffectChange(key="system.traits.di.value", mode=2, value="fire")],
        trait_grants=[],
        species_senses=None,
    )
    assert "fire" in out.immunities


def test_combatant_senses_default_all_none():
    s = CombatantSenses()
    assert s.darkvision is None
    assert s.blindsight is None
    assert s.tremorsense is None
    assert s.truesight is None


# --- C08-S04: movement modes -------------------------------------------------


def test_movement_modes_default_all_none():
    m = CombatantMovementModes()
    assert m.climb is None
    assert m.swim is None
    assert m.fly is None
    assert m.burrow is None


def test_walk_speed_bonus_folds_additively_from_literal_change():
    # Roving's flat +10 walk change lands on walk_speed_bonus, not skipped.
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.movement.walk", mode=2, value="10"),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.walk_speed_bonus == 10
    assert "system.attributes.movement.walk" not in out.skipped_keys


def test_roving_climb_swim_resolve_symbolic_token_to_boosted_walk():
    # Roving: climb/swim (mode=4, value "@attributes.movement.walk") resolve to
    # the BOOSTED walk speed (species 30 + the +10 bonus = 40), not the base.
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.movement.walk", mode=2, value="10"),
            PassiveEffectChange(
                key="system.attributes.movement.climb",
                mode=4,
                value="@attributes.movement.walk",
            ),
            PassiveEffectChange(
                key="system.attributes.movement.swim",
                mode=4,
                value="@attributes.movement.walk",
            ),
        ],
        trait_grants=[],
        species_senses=None,
        species_base_speed=30,
    )
    assert out.walk_speed_bonus == 10
    assert out.movement_modes == CombatantMovementModes(climb=40, swim=40)
    assert out.skipped_keys == ()


def test_literal_int_movement_mode_projects_directly():
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.attributes.movement.fly", mode=4, value="60"),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.movement_modes.fly == 60


def test_unresolvable_symbolic_movement_mode_goes_to_skipped():
    # A symbolic token other than @attributes.movement.walk is not resolved.
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(
                key="system.attributes.movement.burrow", mode=4, value="@scale.foo.bar"
            ),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.movement_modes.burrow is None
    assert "system.attributes.movement.burrow" in out.skipped_keys
