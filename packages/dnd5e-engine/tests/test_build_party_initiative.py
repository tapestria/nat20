"""``CombatInstance.initiative=None``: the engine rolls a built character's Initiative.

SRD 5.2 Initiative: "every participant rolls Initiative; they make a Dexterity
check". Alert: "When you roll Initiative, you can add your Proficiency Bonus to
the roll." A host that builds its party with ``build_party_member`` reaches
the engine's roll — the derived Dexterity, and Alert — by passing ``None``; an
int is seated as given, and ``0`` stays the default.
"""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import CombatInstance, make_build_spec
from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, grid_scene, run_async

_LOADER = BundledAssetLoader()

# A Criminal Rogue 1: raw DEX 15, +2 from the background (17, so +3), and the
# Criminal's Origin feat, Alert (Proficiency Bonus +2 at level 1).
_CRIMINAL = make_build_spec(
    species_slug="human",
    class_slug="rogue",
    level=1,
    ability_scores={"dex": 15},
    background_slug="criminal",
    selected_choices=("background:dex+2,con+1",),
)


def _member(**instance: object) -> PartyMemberSpec:
    return build_party_member(
        _CRIMINAL,
        CombatInstance(entity_id="char:nyx", name="Nyx", zone_id=cell(0, 0), **instance),
        loader=_LOADER,
    )


def test_an_instance_initiative_reaches_the_party_spec_as_given() -> None:
    assert _member().initiative == 0
    assert _member(initiative=12).initiative == 12
    assert _member(initiative=None).initiative is None
    # A JSON round trip keeps "roll it".
    instance = CombatInstance(entity_id="char:nyx", name="Nyx", initiative=None)
    assert CombatInstance.model_validate_json(instance.model_dump_json()).initiative is None


def _initiative(member: PartyMemberSpec, seed: int) -> int:
    foe = EncounterMemberSpec(
        entity_id="mon:foe",
        entity_type="Monster",
        name="Foe",
        initiative=1,  # seated as given: it draws no die
        hp_current=10,
        hp_max=10,
        zone_id=cell(1, 0),
    )

    async def _start():
        start = await start_combat(
            session_id=f"build-initiative-{seed}",
            party=[member],
            encounter=[foe],
            grid_scene=grid_scene(),
            rng_seed=seed,
        )
        return _get_live(start.handle)

    live = run_async(_start())
    return next(c.initiative for c in live.initiative if c.entity_id == "char:nyx")


def test_the_engine_rolls_a_built_characters_initiative_with_its_derived_dexterity() -> None:
    member = _member(initiative=None)
    assert (member.dexterity, member.feats) == (17, ("alert",))
    for seed in (1, 2, 3):
        d20 = random.Random(seed).randint(1, 20)
        assert _initiative(member, seed) == d20 + 3 + 2
    # A pinned Initiative is seated as given, Alert or not.
    assert _initiative(_member(initiative=12), 1) == 12
