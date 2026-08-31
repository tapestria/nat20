"""C22-S06 — bandit-captain's Multiattack joins to Scimitar + Pistol once the
translator labels its opaque ``[[/item .<id>]]`` tokens."""

from __future__ import annotations

import logging

from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import AttackActivity

from dnd5e_engine.activities.monster_actions import expand_action_to_activities


def test_bandit_captain_multiattack_is_one_scimitar_and_one_pistol(caplog):
    monster = BundledAssetLoader().get_monster("bandit-captain")
    assert monster is not None
    multiattack = next(a for a in monster.actions if a.slug == "multiattack")
    with caplog.at_level(logging.WARNING, logger="dnd5e_engine.activities.monster_actions"):
        activities = expand_action_to_activities(monster, multiattack)
    assert len(activities) == 2
    assert all(isinstance(a, AttackActivity) for a in activities)
    types = {a.damage.parts[0].types[0] for a in activities}
    assert types == {"slashing", "piercing"}
    assert "multiattack_join_unresolved" not in caplog.text


def test_any_combination_is_distributed_range_aware_for_the_scout():
    scout = BundledAssetLoader().get_monster("scout")
    multiattack = next(a for a in scout.actions if a.slug == "multiattack")
    far = expand_action_to_activities(
        scout, multiattack, target_distance_ft=100, behavior_profile="RANGED", melee_reach_ft=5
    )
    assert [a.range.value for a in far] == ["150", "150"]  # only the longbow covers 100 ft
    near = expand_action_to_activities(
        scout, multiattack, target_distance_ft=5, behavior_profile="AGGRESSIVE", melee_reach_ft=5
    )
    assert sorted(a.range.value for a in near) == ["150", "5"]  # both cover: one of each
    unknown = expand_action_to_activities(scout, multiattack)
    assert sorted(a.range.value for a in unknown) == ["150", "5"]


def test_any_combination_keeps_the_ranged_profile_tiebreak():
    scout = BundledAssetLoader().get_monster("scout")
    multiattack = next(a for a in scout.actions if a.slug == "multiattack")
    acts = expand_action_to_activities(
        scout, multiattack, target_distance_ft=5, behavior_profile="RANGED", melee_reach_ft=5
    )
    assert [a.range.value for a in acts] == ["150", "150"]
