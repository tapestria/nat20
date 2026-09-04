"""C18 Task 3 — ``rank_monster_actions`` selection priority (S01).

SRD 5.2 "Recharge X-Y" traits are the monster's biggest hitters (breath
weapons, area saves); today's ``select_typed_monster_action`` always returns
multiattack-or-first-offensive in list order, so a recharge action buried
after Claw in ``Monster.actions`` was structurally unreachable even when
available. ``rank_monster_actions`` is the pure ranking function driving the
new priority: available recharge actions first, then available limited-use
(N/Day) offensive casts, then multiattack, then everything else offensive in
list order. ``select_typed_monster_action`` itself stays byte-identical —
pinned here too.
"""

from __future__ import annotations

from datetime import date

from dnd5e_srd_data import Provenance, ReviewState
from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackDamageBlock,
    CastActivity,
    CastSpellBlock,
    DamagePartBlock,
    RangeBlock,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
    TargetBlock,
    TargetTemplateBlock,
    UsesBlock,
    UsesRecoveryEntry,
    UtilityActivity,
)
from dnd5e_srd_data.schema.monster import (
    AbilityScores,
    CreatureSize,
    CreatureType,
    Monster,
    MonsterAction,
    MonsterActionKind,
    Movement,
    SavingThrowProficiencies,
    Senses,
    SkillProficiencies,
)

from dnd5e_engine.activities.monster_actions import (
    rank_monster_actions,
    select_typed_monster_action,
)


def _claw() -> MonsterAction:
    """A leaf melee attack action — mirrors
    ``test_orchestrator_monster_typed.py::_melee_attack``."""
    return MonsterAction(
        slug="claw",
        name="Claw",
        kind=MonsterActionKind.ACTION,
        description="Melee Weapon Attack. Claw.",
        activities=[
            AttackActivity(
                name="Claw",
                range=RangeBlock(units="self", value=None),
                damage=AttackDamageBlock(
                    parts=[DamagePartBlock(number=1, denomination=6, types=["slashing"])]
                ),
            )
        ],
    )


def _multiattack() -> MonsterAction:
    return MonsterAction(
        slug="multiattack",
        name="Multiattack",
        kind=MonsterActionKind.ACTION,
        description="The creature makes two attacks.",
        activities=[UtilityActivity(name="Multiattack")],
    )


def _breath(*, recharge: str = "6") -> MonsterAction:
    """A recharge-gated self-centered AoE save — mirrors
    ``test_orchestrator_monster_typed.py::_breath_weapon``."""
    return MonsterAction(
        slug="fire-breath",
        name="Fire Breath",
        kind=MonsterActionKind.ACTION,
        description="Fire Breath. Each creature in a 15-foot cone must make a save.",
        recharge=recharge,
        activities=[
            SaveActivity(
                name="Fire Breath",
                range=RangeBlock(units="self", value=None),
                target=TargetBlock(
                    template=TargetTemplateBlock(type="cone", size="15", units="ft")
                ),
                save=SaveBlock(ability=["dex"], dc=SaveDcBlock(calculation="", formula="12")),
                damage=SaveDamageBlock(
                    on_save="half",
                    parts=[DamagePartBlock(number=4, denomination=6, types=["fire"])],
                ),
            )
        ],
    )


def _spellcasting(
    *, slug: str = "spellcasting", limited_use: bool = False, uses_max: str = "2"
) -> MonsterAction:
    """A cast-only action. ``limited_use=True`` gives its sole activity an
    integer ``uses.max`` recovering ``day`` (Innate Spellcasting's "N/Day"
    shape); otherwise it's an at-will cast with no tracked uses."""
    uses = (
        UsesBlock(max=uses_max, recovery=[UsesRecoveryEntry(period="day")])
        if limited_use
        else UsesBlock()
    )
    return MonsterAction(
        slug=slug,
        name="Spellcasting",
        kind=MonsterActionKind.ACTION,
        description="The creature casts a spell.",
        activities=[CastActivity(name="Spellcasting", spell=CastSpellBlock(uuid="x"), uses=uses)],
    )


def _monster(actions: list[MonsterAction]) -> Monster:
    return Monster(
        slug="ranking-fixture",
        name="Ranking Fixture",
        description="A test beast.",
        creature_type=CreatureType.BEAST,
        creature_size=CreatureSize.LARGE,
        hp=50,
        hp_dice="7d10+14",
        ability_scores=AbilityScores(str=18, dex=12, con=14, int=3, wis=12, cha=7),
        movement=Movement(walk=40),
        senses=Senses(),
        cr=3.0,
        proficiency_bonus=2,
        saving_throws=SavingThrowProficiencies(),
        skills=SkillProficiencies(),
        provenance=Provenance(
            source="foundry",
            source_url="x",
            ingest_date=date(2026, 6, 3),
            ingest_version="v1",
            srd_version=frozenset({"5.1"}),
        ),
        review=ReviewState(),
        actions=actions,
    )


def test_available_recharge_action_outranks_multiattack_and_first_melee():
    claw, multiattack, breath = _claw(), _multiattack(), _breath()
    ranked = rank_monster_actions([claw, multiattack, breath], is_available=lambda a: True)
    assert [a.slug for a in ranked] == ["fire-breath", "multiattack", "claw"]


def test_spent_recharge_action_drops_out_entirely():
    claw, breath = _claw(), _breath()
    ranked = rank_monster_actions([claw, breath], is_available=lambda a: a.slug != "fire-breath")
    assert [a.slug for a in ranked] == ["claw"]


def test_limited_use_cast_outranks_multiattack_but_not_recharge():
    multiattack = _multiattack()
    spellcasting = _spellcasting(limited_use=True, uses_max="2")
    breath = _breath()
    ranked = rank_monster_actions([multiattack, spellcasting, breath], is_available=lambda a: True)
    assert [a.slug for a in ranked][:2] == ["fire-breath", "spellcasting"]


def test_at_will_cast_only_action_ranks_after_multiattack_in_list_order():
    multiattack = _multiattack()
    spellcasting_at_will_only = _spellcasting(limited_use=False)
    claw = _claw()
    ranked = rank_monster_actions(
        [multiattack, spellcasting_at_will_only, claw], is_available=lambda a: True
    )
    assert [a.slug for a in ranked] == ["multiattack", "spellcasting", "claw"]


def test_select_typed_monster_action_is_unchanged():
    monster_with_claw_then_breath = _monster([_claw(), _breath()])
    action = select_typed_monster_action(monster_with_claw_then_breath)
    assert action is not None
    assert action.slug == "claw"
