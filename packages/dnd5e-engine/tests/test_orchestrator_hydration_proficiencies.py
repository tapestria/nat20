"""F1b — proficiency + monster-template ability-score hydration onto Combatant.

Covers: ``PartyMemberSpec`` proficiency fields threading through to the live
``Combatant``, and ``EncounterMemberSpec.monster_template_slug`` hydrating the
five non-DEX ability scores, proficiency bonus, and save/skill proficiencies
from the SRD monster template. Dexterity is spec-authoritative only when the
host set it away from the ``10`` sentinel default.
"""

from dnd5e_engine.orchestrator import _get_live, start_combat
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import run_async, single_zone


def _combatant(start, eid):
    return next(c for c in _get_live(start.handle).initiative if c.entity_id == eid)


def _filler_foe(entity_id="mon:filler"):
    return EncounterMemberSpec(
        entity_id=entity_id,
        entity_type="Monster",
        name="Filler",
        initiative=1,
        hp_current=7,
        hp_max=7,
        zone_id="zone:start",
    )


def _filler_pc(entity_id="char:filler"):
    return PartyMemberSpec(
        entity_id=entity_id,
        name="Filler",
        initiative=1,
        hp_current=10,
        hp_max=10,
        zone_id="zone:start",
    )


def test_pc_spec_proficiencies_reach_combatant():
    pc = PartyMemberSpec(
        entity_id="char:a",
        name="A",
        initiative=10,
        hp_current=10,
        hp_max=10,
        zone_id="zone:start",
        save_proficiencies=("str", "con"),
        skill_proficiencies=("athletics",),
        skill_expertise=("athletics",),
    )
    h = run_async(
        start_combat(
            session_id="t5-pc-prof",
            party=[pc],
            encounter=[_filler_foe()],
            scene_zones=single_zone(),
            rng_seed=1,
        )
    )
    c = _combatant(h, "char:a")
    assert c.save_proficiencies == ["str", "con"]
    assert c.skill_expertise == ["athletics"]


def test_monster_template_hydrates_scores_and_proficiencies():
    foe = EncounterMemberSpec(
        entity_id="mon:g",
        entity_type="Monster",
        name="Goblin",
        initiative=1,
        hp_current=7,
        hp_max=7,
        zone_id="zone:start",
        monster_template_slug="goblin-warrior",
    )
    h = run_async(
        start_combat(
            session_id="t5-monster-hydrate",
            party=[_filler_pc()],
            encounter=[foe],
            scene_zones=single_zone(),
            rng_seed=1,
        )
    )
    c = _combatant(h, "mon:g")
    assert c.proficiency_bonus_override == 2
    # SRD goblin ability scores.
    assert c.strength == 8
    assert c.dexterity == 15
    assert c.constitution == 10
    assert "stealth" in c.skill_proficiencies


def test_spec_dexterity_wins_over_template():
    foe = EncounterMemberSpec(
        entity_id="mon:g",
        entity_type="Monster",
        name="G",
        initiative=1,
        hp_current=7,
        hp_max=7,
        zone_id="zone:start",
        dexterity=20,
        monster_template_slug="goblin-warrior",
    )
    h = run_async(
        start_combat(
            session_id="t5-dex-wins",
            party=[_filler_pc()],
            encounter=[foe],
            scene_zones=single_zone(),
            rng_seed=1,
        )
    )
    assert _combatant(h, "mon:g").dexterity == 20
