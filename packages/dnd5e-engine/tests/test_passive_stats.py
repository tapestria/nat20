"""Unit tests for the pure passive-stat interpreter.

Exercises the allowlist (trait_grants + Foundry change-keys → typed derived
stats), the deferred-key handling (movement / ci / languages → skipped_keys),
sense mode semantics (mode 4 = max, mode 2 = add), and species-senses merge.
The interpreter is PURE — it never logs or raises; allowlist misses and
non-literal values land in ``skipped_keys`` for the seam to log.
"""

from dnd5e_srd_data.schema.common import PassiveEffectChange, Senses

from dnd5e_engine.activities.passive_stats import (
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


def test_unknown_and_movement_keys_go_to_skipped_not_raised():
    out = interpret_passive_stats(
        changes=[
            PassiveEffectChange(key="system.bonuses.mwak.damage", mode=2, value="+2"),
            PassiveEffectChange(key="system.attributes.movement.walk", mode=2, value="10"),
        ],
        trait_grants=[],
        species_senses=None,
    )
    assert out.resistances == ()
    assert out.senses.darkvision is None
    assert "system.attributes.movement.walk" in out.skipped_keys
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


def test_ci_change_key_skipped_with_quote_escaping_stripped():
    # ci is deferred (no condition_immunities field); the quote-escaped value
    # must not crash and the key lands in skipped_keys (not resistances).
    out = interpret_passive_stats(
        changes=[PassiveEffectChange(key="system.traits.ci.value", mode=2, value='"poison"')],
        trait_grants=[],
        species_senses=None,
    )
    assert "system.traits.ci.value" in out.skipped_keys
    assert out.resistances == ()


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
