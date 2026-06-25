from datetime import date

from dnd5e_srd_data import (
    AbilityScores,
    AssetLoader,
    Background,
    BackgroundAbilityChoice,
    CreatureSize,
    CreatureType,
    Feat,
    FeatCategory,
    MemoryAssetLoader,
    Monster,
    Movement,
    Provenance,
    ReviewState,
    SavingThrowProficiencies,
    Senses,
    SkillProficiencies,
)


def _goblin() -> Monster:
    return Monster(
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
        provenance=Provenance(
            source="foundry",
            source_url="x",
            ingest_date=date(2026, 5, 30),
            ingest_version="v1",
            srd_version=frozenset({"5.1"}),
        ),
        review=ReviewState(),
    )


def test_memory_loader_serves_constructed_monsters():
    loader = MemoryAssetLoader(monsters=[_goblin()])
    assert isinstance(loader, AssetLoader)  # structural conformance
    m = loader.get_monster("goblin")
    assert m is not None
    assert m.name == "Goblin"


def test_memory_loader_returns_none_for_unknown_slug():
    loader = MemoryAssetLoader(monsters=[_goblin()])
    assert loader.get_monster("aboleth") is None


def test_memory_loader_lists_slugs():
    loader = MemoryAssetLoader(monsters=[_goblin()])
    assert loader.list_slugs("monsters") == ["goblin"]
    assert loader.list_slugs("items") == []


def test_memory_loader_contains():
    loader = MemoryAssetLoader(monsters=[_goblin()])
    assert ("monsters", "goblin") in loader
    assert ("monsters", "aboleth") not in loader
    assert ("items", "longsword") not in loader


def _acolyte() -> Background:
    return Background(
        slug="acolyte",
        name="Acolyte",
        description="A devout servant.",
        ability_options=BackgroundAbilityChoice(options=frozenset({"int", "wis", "cha"})),
        provenance=Provenance(
            source="foundry",
            source_url="x",
            ingest_date=date(2026, 5, 30),
            ingest_version="v1",
            srd_version=frozenset({"5.2"}),
        ),
        review=ReviewState(),
    )


def test_memory_loader_serves_backgrounds():
    loader = MemoryAssetLoader(backgrounds=[_acolyte()])
    bg = loader.get_background("acolyte")
    assert bg is not None
    assert bg.name == "Acolyte"
    assert loader.get_background("sage") is None
    assert loader.list_slugs("backgrounds") == ["acolyte"]
    assert ("backgrounds", "acolyte") in loader
    assert ("backgrounds", "sage") not in loader


def _alert() -> Feat:
    return Feat(
        slug="alert",
        name="Alert",
        description="You gain the following benefits.",
        category=FeatCategory.ORIGIN,
        provenance=Provenance(
            source="foundry",
            source_url="x",
            ingest_date=date(2026, 5, 30),
            ingest_version="v1",
            srd_version=frozenset({"5.2"}),
        ),
        review=ReviewState(),
    )


def test_memory_loader_serves_feats():
    loader = MemoryAssetLoader(feats=[_alert()])
    feat = loader.get_feat("alert")
    assert feat is not None
    assert feat.name == "Alert"
    assert feat.category is FeatCategory.ORIGIN
    assert loader.get_feat("grappler") is None
    assert loader.list_slugs("feats") == ["alert"]
    assert ("feats", "alert") in loader
    assert ("feats", "grappler") not in loader
