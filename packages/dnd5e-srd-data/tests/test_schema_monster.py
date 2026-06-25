from datetime import date

import pytest
from pydantic import ValidationError

from dnd5e_srd_data.schema.common import (
    AttackActivity,
    AttackBlock,
    AttackDamageBlock,
    AttackTypeBlock,
    DamagePartBlock,
    Movement,
    Provenance,
    ReviewState,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
    Senses,
    TargetAffectsBlock,
    TargetBlock,
    TargetTemplateBlock,
)
from dnd5e_srd_data.schema.monster import (
    AbilityScores,
    CreatureSize,
    CreatureType,
    Monster,
    MonsterAction,
    MonsterActionKind,
    SavingThrowProficiencies,
    SkillProficiencies,
)


def _prov():
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
        srd_version=frozenset({"5.1"}),
    )


def test_monster_minimal_goblin():
    m = Monster(
        slug="goblin",
        name="Goblin",
        description="A small humanoid.",
        creature_type=CreatureType.HUMANOID,
        creature_size=CreatureSize.SMALL,
        ac=15,
        hp=7,
        hp_dice="2d6",
        ability_scores=AbilityScores(str=8, dex=14, con=10, int=10, wis=8, cha=8),
        movement=Movement(walk=30),
        senses=Senses(darkvision=60, passive_perception=9),
        cr=0.25,
        proficiency_bonus=2,
        saving_throws=SavingThrowProficiencies(),
        skills=SkillProficiencies(stealth=6),
        provenance=_prov(),
        review=ReviewState(),
        actions=[
            MonsterAction(
                slug="scimitar",
                name="Scimitar",
                kind=MonsterActionKind.ACTION,
                description="Melee Weapon Attack: +4 to hit, reach 5 ft.",
                activities=[
                    AttackActivity(
                        attack=AttackBlock(
                            ability="str",
                            type=AttackTypeBlock(value="melee", classification="weapon"),
                        ),
                        damage=AttackDamageBlock(
                            parts=[
                                DamagePartBlock(
                                    number=1,
                                    denomination=6,
                                    bonus="2",
                                    types=["slashing"],
                                )
                            ],
                        ),
                    ),
                ],
            ),
        ],
    )
    assert m.hp == 7
    assert m.movement.walk == 30
    assert m.senses.darkvision == 60
    assert len(m.actions) == 1


def test_monster_legendary_actions_separate_from_actions():
    m = Monster(
        slug="aboleth",
        name="Aboleth",
        description="x",
        creature_type=CreatureType.ABERRATION,
        creature_size=CreatureSize.LARGE,
        ac=17,
        hp=135,
        hp_dice="18d10+36",
        ability_scores=AbilityScores(str=21, dex=9, con=15, int=18, wis=15, cha=18),
        movement=Movement(walk=10, swim=40),
        senses=Senses(darkvision=120, passive_perception=20),
        cr=10,
        proficiency_bonus=4,
        saving_throws=SavingThrowProficiencies(con=6, int=8, wis=6),
        skills=SkillProficiencies(history=12, perception=10),
        provenance=_prov(),
        review=ReviewState(),
        actions=[
            MonsterAction(
                slug="tentacle",
                name="Tentacle",
                kind=MonsterActionKind.ACTION,
                description="x",
            ),
        ],
        legendary_actions=[
            MonsterAction(
                slug="tail-swipe",
                name="Tail Swipe",
                kind=MonsterActionKind.LEGENDARY,
                description="x",
                legendary_cost=1,
            ),
        ],
    )
    assert len(m.actions) == 1
    assert len(m.legendary_actions) == 1
    assert m.legendary_actions[0].legendary_cost == 1


def test_aoe_action_carries_template():
    a = MonsterAction(
        slug="fire-breath",
        name="Fire Breath",
        kind=MonsterActionKind.ACTION,
        description="x",
        activities=[
            SaveActivity(
                save=SaveBlock(
                    ability=["dex"],
                    dc=SaveDcBlock(calculation="", formula="14"),
                ),
                damage=SaveDamageBlock(
                    on_save="half",
                    parts=[DamagePartBlock(number=6, denomination=6, types=["fire"])],
                ),
                target=TargetBlock(
                    template=TargetTemplateBlock(type="cone", size="30", units="ft"),
                    affects=TargetAffectsBlock(type="creature"),
                ),
            ),
        ],
    )
    save_activity = a.activities[0]
    assert isinstance(save_activity, SaveActivity)
    assert save_activity.target.template.type == "cone"
    assert save_activity.save.dc.formula == "14"


def test_ability_scores_rejects_zero():
    with pytest.raises(ValidationError):
        AbilityScores(str=0, dex=10, con=10, int=10, wis=10, cha=10)
