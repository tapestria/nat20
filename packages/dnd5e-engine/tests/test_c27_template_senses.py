"""A templated foe takes its stat block's senses and condition immunities.

SRD 5.2 stat blocks list Senses (Blindsight, Darkvision, Tremorsense,
Truesight) and Condition Immunities. ``start_combat`` copies both onto a foe
whose ``monster_template_slug`` resolves, unless the host set them:
``EncounterMemberSpec.senses`` (``None`` defers to the template) and a
non-empty ``condition_immunities``.
"""

from __future__ import annotations

from typing import Any

import pytest

from dnd5e_engine.activities.passive_stats import CombatantSenses
from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, grid_scene, run_async


def _foe(**fields: Any) -> EncounterMemberSpec:
    base: dict[str, Any] = {
        "entity_id": "mon:foe",
        "entity_type": "Monster",
        "name": "Foe",
        "initiative": 1,
        "hp_current": 30,
        "hp_max": 30,
        "zone_id": cell(1, 0),
    }
    return EncounterMemberSpec(**(base | fields))


def _seated(foe: EncounterMemberSpec):
    """The live ``Combatant`` ``start_combat`` builds for ``foe``."""
    hero = PartyMemberSpec(
        entity_id="char:hero",
        name="Hero",
        initiative=20,
        hp_current=10,
        hp_max=10,
        zone_id=cell(0, 0),
    )

    async def _inner():
        start = await start_combat(
            session_id="c27-template-senses",
            party=[hero],
            encounter=[foe],
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        return _get_live(start.handle)

    live = run_async(_inner())
    return next(c for c in live.initiative if c.entity_id == foe.entity_id)


@pytest.mark.parametrize(
    "slug,senses",
    [
        # SRD 5.2: Goblin Warrior "Darkvision 60 ft."; Bat "Blindsight 60 ft.";
        # Adult Red Dragon "Blindsight 60 ft., Darkvision 120 ft.".
        ("goblin-warrior", CombatantSenses(darkvision=60)),
        ("bat", CombatantSenses(blindsight=60)),
        ("adult-red-dragon", CombatantSenses(blindsight=60, darkvision=120)),
        ("guard", CombatantSenses()),
    ],
)
def test_a_templated_foe_takes_its_stat_blocks_senses(slug: str, senses: CombatantSenses) -> None:
    assert _seated(_foe(monster_template_slug=slug)).senses == senses


def test_explicit_senses_win_over_the_template() -> None:
    blind = _seated(_foe(monster_template_slug="goblin-warrior", senses=CombatantSenses()))
    assert blind.senses == CombatantSenses()
    keen = _seated(_foe(monster_template_slug="goblin-warrior", senses={"truesight": 30}))
    assert keen.senses == CombatantSenses(truesight=30)


def test_a_foe_without_a_template_has_only_the_senses_it_is_given() -> None:
    assert _seated(_foe()).senses == CombatantSenses()
    assert _seated(_foe(monster_template_slug="no-such-monster")).senses == CombatantSenses()
    assert _seated(_foe(senses={"darkvision": 60})).senses == CombatantSenses(darkvision=60)


def test_the_senses_default_survives_a_round_trip() -> None:
    # ``None`` means "use the template"; a JSON dump and re-validate keeps it so.
    spec = _foe(monster_template_slug="bat")
    again = EncounterMemberSpec.model_validate_json(spec.model_dump_json())
    assert again.senses is None
    assert _seated(again).senses == CombatantSenses(blindsight=60)


def test_a_templated_foe_takes_its_condition_immunities_when_the_spec_has_none() -> None:
    # SRD 5.2 Skeleton: "Condition Immunities Exhaustion, Poisoned".
    skeleton = _seated(_foe(monster_template_slug="skeleton"))
    assert sorted(skeleton.condition_immunities) == ["exhaustion", "poisoned"]
    # A host list wins outright: it is not merged with the template's.
    host = _seated(_foe(monster_template_slug="skeleton", condition_immunities=["charmed"]))
    assert host.condition_immunities == ["charmed"]
