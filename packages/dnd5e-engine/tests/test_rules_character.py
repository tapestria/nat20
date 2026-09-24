"""Pure character-derivation rules (rules/character.py): one section per plan task."""

from __future__ import annotations

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.rules import character as rc

LOADER = BundledAssetLoader()


# ── Task 3 ──


def test_extra_attack_count_takes_the_highest_tier_never_the_sum() -> None:
    assert rc.extra_attack_count([]) == 0
    assert rc.extra_attack_count(["extra-attack"]) == 1
    assert rc.extra_attack_count(["extra-attack", "two-extra-attacks"]) == 2
    assert rc.extra_attack_count(["extra-attack", "two-extra-attacks", "three-extra-attacks"]) == 3


def test_leveled_feature_slugs_uses_each_sources_own_level() -> None:
    slugs = rc.leveled_feature_slugs(
        [(LOADER.get_class("fighter"), 1), (LOADER.get_class("wizard"), 4), (None, 9)]
    )
    assert "second-wind" in slugs
    assert "arcane-recovery" in slugs
    assert "extra-attack" not in slugs
    assert "action-surge" not in slugs


def test_granted_feature_slugs_keeps_its_single_level_contract() -> None:
    fighter = LOADER.get_class("fighter")
    assert rc.granted_feature_slugs([fighter, None], level=5) == rc.leveled_feature_slugs(
        [(fighter, 5)]
    )


def test_subclass_gate_level_is_3_for_every_srd_class() -> None:
    for slug in LOADER.list_slugs("classes"):
        cls = LOADER.get_class(slug)
        assert cls is not None
        assert rc.subclass_gate_level(cls) == 3, slug
