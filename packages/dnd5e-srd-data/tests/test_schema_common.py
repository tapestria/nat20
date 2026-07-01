from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from dnd5e_srd_data.schema.common import (
    Activity,
    ActivityKind,
    AttackActivity,
    AttackBlock,
    AttackDamageBlock,
    AttackTypeBlock,
    CastActivity,
    CastSpellBlock,
    CheckActivity,
    CheckBlock,
    DamageActivity,
    DamageActivityDamageBlock,
    DamagePart,
    DamagePartBlock,
    EnchantActivity,
    EnchantRestrictionsBlock,
    HealActivity,
    Movement,
    PassiveEffect,
    Provenance,
    Range,
    RangeUnits,
    ReviewState,
    SaveActivity,
    SaveBlock,
    SaveDamageBlock,
    SaveDcBlock,
    Senses,
    SummonActivity,
    SummonProfile,
    Target,
    TargetTemplate,
    TargetTemplateShape,
    TransformActivity,
    TransformProfile,
    UtilityActivity,
)

# Reusable TypeAdapter for round-tripping the discriminated union.
_ACTIVITY = TypeAdapter(Activity)


def _roundtrip(activity) -> None:
    """Serialize → re-validate via the discriminated-union TypeAdapter and
    assert equality. Catches: (a) discriminator wiring, (b) sub-block default
    drift, (c) alias round-trip (``_id``)."""
    dumped = activity.model_dump(mode="json", by_alias=True)
    restored = _ACTIVITY.validate_python(dumped)
    assert restored == activity, f"{type(activity).__name__} did not round-trip"


def test_provenance_round_trips():
    p = Provenance(
        source="foundry",
        source_url="https://github.com/foundryvtt/dnd5e/blob/master/packs/_source/monsters/aboleth.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
        srd_version={"5.1"},
        license_tag="CC-BY-4.0",
    )
    j = p.model_dump_json()
    p2 = Provenance.model_validate_json(j)
    assert p == p2


def test_provenance_rejects_unknown_source():
    with pytest.raises(ValidationError):
        Provenance(
            source="kobold_press",  # type: ignore[arg-type]
            source_url="x",
            ingest_date=date(2026, 5, 30),
            ingest_version="x",
            srd_version={"5.1"},
            license_tag="CC-BY-4.0",
        )


def test_review_state_defaults_to_unreviewed():
    r = ReviewState()
    assert r.known_divergence is None
    assert r.requires_user_decision is False


def test_damage_part_pair():
    d = DamagePart(dice="1d8", damage_type="slashing")
    assert d.dice == "1d8"
    assert d.damage_type == "slashing"


def test_range_self_ignores_value_units():
    r = Range(kind="self")
    assert r.kind == "self"
    assert r.value is None


def test_range_with_units():
    r = Range(kind="ranged", value=120, units=RangeUnits.FEET, long=480)
    assert r.value == 120
    assert r.long == 480


def test_target_with_template():
    t = Target(
        kind="creature",
        count=1,
        template=TargetTemplate(shape=TargetTemplateShape.CONE, size=30, units=RangeUnits.FEET),
    )
    assert t.template is not None
    assert t.template.shape == TargetTemplateShape.CONE


# ---------------------------------------------------------------------------
# Per-kind activity round-trips. One per Foundry activity kind. Each
# constructs a minimal-but-meaningful instance, asserts the discriminator
# and a kind-specific field, then round-trips through the discriminated-union
# TypeAdapter so the union wiring + sub-block defaults are exercised end-to-end.
# ---------------------------------------------------------------------------


def test_attack_activity_round_trip():
    a = AttackActivity(
        id="dnd5eactivity000",
        name="Longsword Slash",
        attack=AttackBlock(
            ability="str",
            type=AttackTypeBlock(value="melee", classification="weapon"),
        ),
        damage=AttackDamageBlock(
            parts=[DamagePartBlock(number=1, denomination=8, types=["slashing"])],
        ),
    )
    assert a.kind == "attack"
    assert a.attack.type.value == "melee"
    assert a.damage.parts[0].denomination == 8
    _roundtrip(a)


def test_cast_activity_round_trip():
    a = CastActivity(
        id="dnd5eactivity001",
        name="Cast Magic Missile",
        spell=CastSpellBlock(level=1, uuid="Compendium.dnd5e.spells.Item.magicmissile00"),
    )
    assert a.kind == "cast"
    assert a.spell.level == 1
    _roundtrip(a)


def test_check_activity_round_trip():
    a = CheckActivity(
        id="dnd5eactivity002",
        name="Pick Lock",
        check=CheckBlock(
            ability="dex",
            associated=["thi"],
            dc=SaveDcBlock(calculation="", formula="15"),
        ),
    )
    assert a.kind == "check"
    assert a.check.ability == "dex"
    _roundtrip(a)


def test_damage_activity_round_trip():
    a = DamageActivity(
        id="dnd5eactivity003",
        name="Acid Splash Tick",
        damage=DamageActivityDamageBlock(
            parts=[DamagePartBlock(number=2, denomination=4, types=["acid"])],
        ),
    )
    assert a.kind == "damage"
    assert a.damage.parts[0].number == 2
    assert a.damage.critical.allow is False  # default
    _roundtrip(a)


def test_enchant_activity_round_trip():
    a = EnchantActivity(
        id="dnd5eactivity004",
        name="Enchant Weapon",
        restrictions=EnchantRestrictionsBlock(
            allow_magical=False,
            type="weapon",
            categories=["simple", "martial"],
        ),
    )
    assert a.kind == "enchant"
    assert a.restrictions.type == "weapon"
    _roundtrip(a)


def test_heal_activity_round_trip():
    a = HealActivity(
        id="dnd5eactivity005",
        name="Cure Wounds",
        healing=DamagePartBlock(number=1, denomination=8, bonus="@mod", types=["healing"]),
    )
    assert a.kind == "heal"
    assert a.healing.bonus == "@mod"
    _roundtrip(a)


def test_save_activity_round_trip():
    a = SaveActivity(
        id="dnd5eactivity006",
        name="Fireball",
        save=SaveBlock(ability=["dex"], dc=SaveDcBlock(calculation="spellcasting", formula="")),
        damage=SaveDamageBlock(
            on_save="half",
            parts=[DamagePartBlock(number=8, denomination=6, types=["fire"])],
        ),
    )
    assert a.kind == "save"
    assert a.save.ability == ["dex"]
    assert a.damage.on_save == "half"
    _roundtrip(a)


def test_summon_activity_round_trip():
    a = SummonActivity(
        id="dnd5eactivity007",
        name="Conjure Animals",
        profiles=[
            SummonProfile(
                id="profile000",
                name="Wolf",
                cr="1/4",
                count="4",
                uuid="Compendium.dnd5e.monsters.Actor.wolf00000000",
            )
        ],
    )
    assert a.kind == "summon"
    assert len(a.profiles) == 1
    assert a.profiles[0].name == "Wolf"
    _roundtrip(a)


def test_transform_activity_round_trip():
    a = TransformActivity(
        id="dnd5eactivity008",
        name="Polymorph",
        profiles=[
            TransformProfile(
                id="profile001",
                name="Giant Ape",
                cr="7",
                uuid="Compendium.dnd5e.monsters.Actor.giantape0000",
            )
        ],
    )
    assert a.kind == "transform"
    assert a.transform.mode == "cr"  # default
    assert len(a.profiles) == 1
    _roundtrip(a)


def test_utility_activity_round_trip():
    a = UtilityActivity(
        id="dnd5eactivity009",
        name="Roll Investigation",
        roll={"formula": "1d20+@mod", "name": "Investigation", "prompt": True, "visible": True},
    )
    assert a.kind == "utility"
    assert a.roll.formula == "1d20+@mod"
    _roundtrip(a)


def test_activity_union_discriminator_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _ACTIVITY.validate_python({"kind": "bogus"})


def test_activity_union_dispatches_on_kind():
    """Validating raw dicts via the union picks the right per-kind class."""
    payload = {
        "kind": "save",
        "save": {"ability": ["wis"], "dc": {"calculation": "", "formula": "13"}},
        "damage": {"on_save": "none", "parts": []},
    }
    activity = _ACTIVITY.validate_python(payload)
    assert isinstance(activity, SaveActivity)
    assert activity.save.dc.formula == "13"


def test_activity_kind_enum_values_match_discriminator_literals():
    """ActivityKind exists as a convenience export; each value must match a
    per-kind class's Literal discriminator so callers can use either form."""
    expected = {
        ActivityKind.ATTACK.value,
        ActivityKind.CAST.value,
        ActivityKind.CHECK.value,
        ActivityKind.DAMAGE.value,
        ActivityKind.ENCHANT.value,
        ActivityKind.HEAL.value,
        ActivityKind.SAVE.value,
        ActivityKind.SUMMON.value,
        ActivityKind.TRANSFORM.value,
        ActivityKind.UTILITY.value,
    }
    actual = {
        AttackActivity().kind,
        CastActivity().kind,
        CheckActivity().kind,
        DamageActivity().kind,
        EnchantActivity().kind,
        HealActivity().kind,
        SaveActivity().kind,
        SummonActivity().kind,
        TransformActivity().kind,
        UtilityActivity().kind,
    }
    assert expected == actual


def test_movement_walk_only():
    m = Movement(walk=30)
    assert m.walk == 30
    assert m.fly is None


def test_senses_darkvision():
    s = Senses(darkvision=60)
    assert s.darkvision == 60
    assert s.blindsight is None


def test_passive_effect_carries_id_and_statuses():
    pe = PassiveEffect.model_validate(
        {"_id": "abc123", "name": "Paralyzed", "statuses": ["paralyzed"], "changes": []}
    )
    assert pe.id == "abc123"
    assert pe.statuses == ["paralyzed"]
    assert pe.model_dump(by_alias=True)["_id"] == "abc123"
