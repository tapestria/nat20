"""Multiattack fan-out fidelity against the shipped SRD corpus.

A multiattack names its sub-attacks only in prose. Getting the join wrong is not
cosmetic: it changes how much damage a monster deals every round. These tests
pin the parse against real corpus entries covering each prose shape.
"""

from __future__ import annotations

import pytest
from dnd5e_srd_data import BundledAssetLoader

from dnd5e_engine.activities.monster_actions import (
    _action_is_usage_gated,
    _multiattack_clause,
    _name_from_foundry_id,
    _parse_item_counts,
    expand_action_to_activities,
    expand_action_to_parts,
)


@pytest.fixture(scope="module")
def loader() -> BundledAssetLoader:
    return BundledAssetLoader()


def _multiattack_activity_count(loader: BundledAssetLoader, slug: str) -> int:
    monster = loader.get_monster(slug)
    assert monster is not None, f"corpus is missing {slug}"
    action = next((a for a in monster.actions if a.slug == "multiattack"), None)
    assert action is not None, f"{slug} has no multiattack"
    return len(expand_action_to_activities(monster, action))


@pytest.mark.parametrize(
    ("slug", "expected", "srd_text"),
    [
        # Heterogeneous, name-form tokens: each sibling keeps its OWN count.
        ("chuul", 3, "2 Pincer attacks and uses Paralyzing Tentacles"),
        ("otyugh", 3, "one Bite attack and two Tentacle attacks"),
        ("cloaker", 3, "one Attach attack and two Tail attacks"),
        ("grick", 2, "one Beak attack and one Tentacles attack"),
        ("unicorn", 2, "one Hooves attack and one Radiant Horn attack"),
        ("sphinx-of-valor", 3, "two Claw attacks and uses Roar"),
        # Heterogeneous, bare mnemonic Foundry ids recovered by name.
        ("mummy", 3, "two Rotting Fist attacks and uses Dreadful Glare"),
        ("pit-fiend", 4, "one Bite attack, two Claw attacks, and one Tail attack"),
        ("xorn", 4, "one Bite attack and three Claw attacks"),
        ("marilith", 7, "six Pact Blade attacks and uses Tail"),
        # Homogeneous with a "can replace" rider — the rider is NOT an extra
        # attack, so the count must stay at the leading number.
        ("adult-red-dragon", 3, "three Rend attacks (may replace one w/ Spellcasting)"),
        ("solar", 2, "two Flying Sword attacks (may replace one w/ Slaying Bow)"),
        ("guardian-naga", 2, "two Bite attacks (may replace any w/ Poisonous Spittle)"),
    ],
)
def test_multiattack_fans_out_to_the_srd_attack_count(
    loader: BundledAssetLoader, slug: str, expected: int, srd_text: str
) -> None:
    assert _multiattack_activity_count(loader, slug) == expected, srd_text


def test_rider_sentence_is_stripped_even_without_a_space_after_the_period() -> None:
    """``young-bronze-dragon`` ships "attacks.It can replace…" — no space."""
    clause = _multiattack_clause("makes three [[/item Rend]] attacks.It can replace one attack")
    assert "replace" not in clause


def test_free_choice_clause_falls_back_rather_than_guessing_a_sequence() -> None:
    """ "Slam or Force Bolt in any combination" is alternatives, not a sequence."""
    assert (
        _parse_item_counts(
            "The golem makes two attacks, using [[/item Slam]] or [[/item Force Bolt]] "
            "in any combination."
        )
        is None
    )


def test_opaque_foundry_ids_stay_unjoinable() -> None:
    """A random document key must not be coerced into a bogus action name."""
    assert _name_from_foundry_id("w3cX0piuU875Hc2M") is None
    assert _parse_item_counts("makes two attacks, using [[/item .w3cX0piuU875Hc2M]]") is None


def test_mnemonic_foundry_ids_recover_their_action_name() -> None:
    assert _name_from_foundry_id("mmRottingFist000") == "Rotting Fist"
    assert _name_from_foundry_id("mmBite0000000000") == "Bite"


def test_corpus_wide_precise_join_rate_does_not_regress(loader: BundledAssetLoader) -> None:
    """Ratchet: the share of multiattacks resolving without a lossy fallback.

    Was 6/180 before the name-form + mnemonic-id join landed, 127/180 before a
    clause stopped ending inside an item token (the pirate's "two Dagger
    attacks"). This floor exists so a translator or parser change that
    silently reverts that is caught.
    """
    import logging

    import dnd5e_engine.activities.monster_actions as module

    lossy = 0
    total = 0
    original = module._LOGGER.warning

    def count_lossy(msg: str, *args: object, **kwargs: object) -> None:
        nonlocal lossy
        if "multiattack_join_unresolved" in str(msg):
            lossy += 1

    module._LOGGER.warning = count_lossy  # type: ignore[assignment]
    try:
        logging.disable(logging.CRITICAL)
        for slug in loader.list_slugs("monsters"):
            monster = loader.get_monster(slug)
            if monster is None:
                continue
            action = next((a for a in monster.actions if a.slug == "multiattack"), None)
            if action is None:
                continue
            total += 1
            expand_action_to_activities(monster, action)
    finally:
        module._LOGGER.warning = original  # type: ignore[assignment]
        logging.disable(logging.NOTSET)

    precise = total - lossy
    assert total >= 180, f"corpus shrank unexpectedly: {total} multiattacks"
    assert precise >= 128, f"precise multiattack joins regressed to {precise}/{total}"


def _multiattack(loader: BundledAssetLoader, slug: str):
    monster = loader.get_monster(slug)
    assert monster is not None, f"corpus is missing {slug}"
    return monster, next(a for a in monster.actions if a.slug == "multiattack")


def test_the_fallback_repeats_only_an_attack_the_clause_names(loader: BundledAssetLoader) -> None:
    """ "The djinni makes three attacks, using Storm Blade or Storm Bolt in any
    combination" — never its Create Whirlwind, at any distance; the iron
    golem's "using Bladed Arm or Fiery Bolt" never breathes."""
    djinni, multiattack = _multiattack(loader, "djinni")
    for distance, slug in [(None, "storm-blade"), (5, "storm-blade"), (60, "storm-bolt")]:
        parts = expand_action_to_parts(djinni, multiattack, target_distance_ft=distance)
        assert [action.slug for action, _ in parts] == [slug] * 3, distance
    golem, golem_multiattack = _multiattack(loader, "iron-golem")
    parts = expand_action_to_parts(golem, golem_multiattack, target_distance_ft=30)
    assert [action.slug for action, _ in parts] == ["fiery-bolt", "fiery-bolt"]


def test_a_clause_reads_past_an_item_id_that_starts_with_a_capital(
    loader: BundledAssetLoader,
) -> None:
    """The goblin boss's Shortbow token is ``[[/item .XbNHC5OBGT6VQF40]]``: the
    period before its capital ``X`` is no sentence break."""
    boss, multiattack = _multiattack(loader, "goblin-boss")
    assert "{Shortbow}" in _multiattack_clause(multiattack.description)
    parts = expand_action_to_parts(boss, multiattack, target_distance_ft=30)
    assert [action.slug for action, _ in parts] == ["shortbow", "shortbow"]


def test_a_form_qualified_action_answers_to_its_plain_name(loader: BundledAssetLoader) -> None:
    """The wererat's clause names "Hand Crossbow"; its action is "Hand Crossbow
    (Humanoid or Hybrid Form Only)", still the attack it repeats at 30 ft."""
    wererat, multiattack = _multiattack(loader, "wererat")
    parts = expand_action_to_parts(wererat, multiattack, target_distance_ft=30)
    assert [action.slug for action, _ in parts] == ["hand-crossbow", "hand-crossbow"]


def test_each_part_names_its_action_and_an_unavailable_one_sits_out(
    loader: BundledAssetLoader,
) -> None:
    """ "The doppelganger makes two Slam attacks and uses Unsettling Visage if
    available": each part carries the action it comes from, and an action the
    caller reports unavailable (a spent Recharge) is left out."""
    doppelganger, multiattack = _multiattack(loader, "doppelganger")
    parts = expand_action_to_parts(doppelganger, multiattack)
    assert [action.slug for action, _ in parts] == ["slam", "slam", "unsettling-visage"]
    assert all(activity in action.activities for action, activity in parts)
    assert expand_action_to_activities(doppelganger, multiattack) == [a for _, a in parts]
    spent = expand_action_to_parts(
        doppelganger, multiattack, is_available=lambda action: action.slug != "unsettling-visage"
    )
    assert [action.slug for action, _ in spent] == ["slam", "slam"]


def test_the_fallback_never_repeats_a_usage_gated_sibling(loader: BundledAssetLoader) -> None:
    """The aboleth's Dominate Mind (2/Day) and the ancient gold dragon's Fire
    Breath (Recharge 5-6) both carry a self/cone activity whose reach
    ``_activity_range_ft`` can't resolve — so distance never disqualified
    either, and each used to win its monster's range tie-break and get
    repeated past its own budget. The fallback must drop both from its
    candidate pool outright, never conditionally on ``is_available``.

    At 30 ft the aboleth resolves to its OTHER at-will save, Consume
    Memories (its own 30 ft range covers; Tentacle's melee-only reach
    doesn't); within Tentacle's melee reach, Tentacle wins the tie over
    Consume Memories (also covering) by list order. Nothing at-will covers
    past Consume Memories' 30 ft, so beyond it the existing no-reach fallback
    returns the first at-will sibling in list order — Tentacle again, the
    same behaviour as when no sibling covers at all.
    """
    aboleth, aboleth_multiattack = _multiattack(loader, "aboleth")
    for distance, slugs in [
        (30, ["consume-memories", "consume-memories"]),
        (5, ["tentacle", "tentacle"]),  # within Tentacle's melee reach
        (60, ["tentacle", "tentacle"]),  # no-reach fallback: siblings[0]
    ]:
        parts = expand_action_to_parts(aboleth, aboleth_multiattack, target_distance_ft=distance)
        assert [action.slug for action, _ in parts] == slugs, distance
        assert not any(_action_is_usage_gated(action) for action, _ in parts), distance

    dragon, dragon_multiattack = _multiattack(loader, "ancient-gold-dragon")
    for distance, slugs in [
        (60, ["weakening-breath"]),  # Fire Breath (Recharge 5-6) excluded
        (5, ["rend"]),  # within Rend's melee reach
    ]:
        parts = expand_action_to_parts(dragon, dragon_multiattack, target_distance_ft=distance)
        assert [action.slug for action, _ in parts] == slugs, distance
        assert not any(_action_is_usage_gated(action) for action, _ in parts), distance


def test_corpus_wide_fallback_never_yields_a_usage_gated_part(
    loader: BundledAssetLoader,
) -> None:
    """For every bundled Multiattack, at a spread of distances, no resolved
    part ever names a usage-gated action — whichever branch resolves it.
    ``is_available`` already excludes them from the precise join; passing
    the same predicate here must see that reflected from the fallback too,
    which never consults ``is_available`` at all and must exclude them on
    its own.
    """
    for slug in loader.list_slugs("monsters"):
        monster = loader.get_monster(slug)
        if monster is None:
            continue
        action = next((a for a in monster.actions if a.slug == "multiattack"), None)
        if action is None:
            continue
        for distance in (5, 30, 60, 120):
            parts = expand_action_to_parts(
                monster,
                action,
                target_distance_ft=distance,
                is_available=lambda a: not _action_is_usage_gated(a),
            )
            gated = [a.slug for a, _ in parts if _action_is_usage_gated(a)]
            assert not gated, f"{slug} at {distance} ft: {gated}"
