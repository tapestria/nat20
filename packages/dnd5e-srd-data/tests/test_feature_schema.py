from dnd5e_srd_data.schema.feature import Feature
from dnd5e_srd_data.schema.refs import GrantRef

_PROV = {
    "source": "foundry",
    "source_url": "x",
    "srd_version": ["5.2"],
    "ingest_date": "2026-06-04",
    "ingest_version": "foundry-translator-v1",
}


def test_feature_round_trips_with_activity_and_passive_effect():
    raw = {
        "slug": "rage",
        "name": "Rage",
        "description": "In battle, you fight with primal ferocity.",
        "feature_type": "class_feature",
        "foundry_id": "phbbrbRage000000",
        "source_slug": "barbarian",
        "activities": [{"_id": "dnd5eactivity000", "kind": "utility", "name": "Expend Rage"}],
        "passive_effects": [
            {
                "_id": "G5XZTi4zYTFiHVll",
                "name": "Rage",
                "changes": [
                    {
                        "key": "system.bonuses.mwak.damage",
                        "mode": 2,
                        "value": "+@scale.barbarian.rage-damage",
                    }
                ],
            }
        ],
        "provenance": _PROV,
        "review": {},
    }
    feat = Feature.model_validate(raw)
    assert feat.slug == "rage"
    assert feat.feature_type == "class_feature"
    assert feat.entry_kind == "feature"
    assert feat.activities[0].kind == "utility"
    assert feat.passive_effects[0].changes[0].value == "+@scale.barbarian.rage-damage"


def test_prose_only_feature_has_empty_activities_and_effects():
    feat = Feature.model_validate(
        {
            "slug": "dwarven-resilience",
            "name": "Dwarven Resilience",
            "description": "...",
            "feature_type": "species_trait",
            "foundry_id": "phbsptDwarvenRes",
            "source_slug": "dwarf",
            "provenance": _PROV,
            "review": {},
        }
    )
    assert feat.activities == []
    assert feat.passive_effects == []


def test_grant_ref_defaults():
    ref = GrantRef.model_validate({"ref_type": "feature", "slug": "rage"})
    assert ref.level == 0
    assert ref.optional is False


def test_feature_is_importable_from_package_root():
    import dnd5e_srd_data as lib
    from dnd5e_srd_data.schema import Feature as SchemaFeature
    from dnd5e_srd_data.schema import GrantRef as SchemaGrantRef

    assert lib.Feature is SchemaFeature
    assert lib.GrantRef is SchemaGrantRef


def test_features_is_a_loader_category():
    from dnd5e_srd_data.loader import _CATEGORIES

    assert "features" in _CATEGORIES


def test_class_accepts_granted_features_and_choices():
    from dnd5e_srd_data.schema.class_ import Class

    c = Class.model_validate(
        {
            "slug": "barbarian",
            "name": "Barbarian",
            "description": "...",
            "identifier": "barbarian",
            "hit_die": "d12",
            "primary_ability": {"value": ["str"], "all": False},
            "spellcasting": {"ability": "", "progression": "none"},
            "granted_features": [{"ref_type": "feature", "slug": "rage", "level": 1}],
            "feature_choices": [
                {
                    "restriction_subtype": "",
                    "pool": [{"ref_type": "feat", "slug": "archery"}],
                    "schedule": [{"level": 1, "count": 1, "replacement": False}],
                }
            ],
            "provenance": _PROV,
            "review": {},
        }
    )
    assert c.granted_features[0].slug == "rage"
    assert c.feature_choices[0].pool[0].slug == "archery"
    assert c.feature_choices[0].schedule[0].level == 1
    assert c.feature_choices[0].schedule[0].count == 1


def test_subclass_accepts_granted_features_and_choices():
    from dnd5e_srd_data.schema.class_ import Subclass

    sc = Subclass.model_validate(
        {
            "slug": "berserker",
            "name": "Path of the Berserker",
            "description": "...",
            "identifier": "berserker",
            "class_identifier": "barbarian",
            "spellcasting": {"ability": "", "progression": "none"},
            "granted_features": [{"ref_type": "feature", "slug": "frenzy", "level": 3}],
            "feature_choices": [],
            "provenance": _PROV,
            "review": {},
        }
    )
    assert sc.granted_features[0].slug == "frenzy"
    assert sc.feature_choices == []


def test_species_accepts_granted_features_and_choices():
    from dnd5e_srd_data.schema.species import Species

    sp = Species.model_validate(
        {
            "slug": "dwarf",
            "name": "Dwarf",
            "description": "...",
            "creature_type": {"value": "humanoid"},
            "size": "medium",
            "movement": {"walk": 30},
            "senses": {"darkvision": 120},
            "granted_features": [{"ref_type": "feature", "slug": "dwarven-resilience", "level": 0}],
            "feature_choices": [],
            "provenance": _PROV,
            "review": {},
        }
    )
    assert sp.granted_features[0].slug == "dwarven-resilience"
