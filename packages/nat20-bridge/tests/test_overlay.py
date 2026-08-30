from datetime import date

from dnd5e_srd_data.loader import BundledAssetLoader, MemoryAssetLoader
from dnd5e_srd_data.schema.common import Provenance, ReviewState
from dnd5e_srd_data.schema.condition import Condition, ConditionEffect, ConditionEffectKind
from dnd5e_srd_data.schema.item import Weapon

from nat20_bridge.overlay import OverlayAssetLoader


def _hb_weapon(slug: str = "hb-frost-brand") -> Weapon:
    base = BundledAssetLoader().get_weapon("longsword")
    assert base is not None
    return base.model_copy(update={"slug": slug, "name": "Frost Brand"})


def _condition(slug: str) -> Condition:
    return Condition(
        slug=slug,
        name=slug,
        description="",
        effects=[ConditionEffect(kind=ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST, value=5)],
        implies=[],
        provenance=Provenance(
            source="foundry",
            source_url="x",
            ingest_date=date(2026, 8, 27),
            ingest_version="v1",
            srd_version=frozenset({"5.2"}),
        ),
        review=ReviewState(),
    )


def test_overlay_serves_homebrew_and_falls_through() -> None:
    loader = OverlayAssetLoader(
        base=BundledAssetLoader(),
        overlay=MemoryAssetLoader(items=[_hb_weapon()]),
    )
    assert loader.get_weapon("hb-frost-brand") is not None  # overlay hit
    assert loader.get_weapon("longsword") is not None  # base fallthrough
    assert loader.get_monster("goblin-warrior") is not None  # untouched category
    assert "hb-frost-brand" in loader.list_slugs("items")
    assert "longsword" in loader.list_slugs("items")
    assert ("items", "hb-frost-brand") in loader
    assert loader.get_weapon("hb-nope") is None


def test_canonical_is_never_shadowed() -> None:
    # An overlay entry that reuses a canonical slug must NOT win.
    rogue = MemoryAssetLoader(items=[_hb_weapon(slug="longsword")])
    loader = OverlayAssetLoader(base=BundledAssetLoader(), overlay=rogue)
    got = loader.get_weapon("longsword")
    assert got is not None and got.name != "Frost Brand"


def test_overlay_covers_every_category() -> None:
    base = BundledAssetLoader()

    armor = base.get_armor("shield")
    assert armor is not None
    armor = armor.model_copy(update={"slug": "hb-shield"})

    monster = base.get_monster("goblin-warrior")
    assert monster is not None
    monster = monster.model_copy(update={"slug": "hb-goblin"})

    spell = base.get_spell("acid-arrow")
    assert spell is not None
    spell = spell.model_copy(update={"slug": "hb-acid-arrow", "foundry_uuid": "hb-uuid-123"})

    species = base.get_species("dwarf")
    assert species is not None
    species = species.model_copy(update={"slug": "hb-dwarf"})

    klass = base.get_class("bard")
    assert klass is not None
    klass = klass.model_copy(update={"slug": "hb-bard"})

    subclass = base.get_subclass("champion")
    assert subclass is not None
    subclass = subclass.model_copy(update={"slug": "hb-champion"})

    background = base.get_background("sage")
    assert background is not None
    background = background.model_copy(update={"slug": "hb-sage"})

    feat = base.get_feat("alert")
    assert feat is not None
    feat = feat.model_copy(update={"slug": "hb-alert"})

    feature = base.get_feature("action-surge")
    assert feature is not None
    feature = feature.model_copy(update={"slug": "hb-action-surge"})

    overlay = MemoryAssetLoader(
        items=[_hb_weapon(), armor],
        monsters=[monster],
        spells=[spell],
        species=[species],
        classes=[klass],
        subclasses=[subclass],
        backgrounds=[background],
        feats=[feat],
        features=[feature],
    )
    loader = OverlayAssetLoader(base=base, overlay=overlay)

    assert loader.get_item("hb-frost-brand") is not None
    assert loader.get_item("nope") is None
    assert loader.get_armor("hb-shield") is not None
    assert loader.get_armor("hb-nope") is None
    assert loader.get_monster("hb-goblin") is not None
    assert loader.get_monster("hb-nope") is None
    assert loader.get_spell("hb-acid-arrow") is not None
    assert loader.get_spell("hb-nope") is None
    assert loader.get_spell_by_uuid("hb-uuid-123") is not None
    assert loader.get_spell_by_uuid("nope") is None
    assert loader.get_species("hb-dwarf") is not None
    assert loader.get_species("hb-nope") is None
    assert loader.get_class("hb-bard") is not None
    assert loader.get_class("hb-nope") is None
    assert loader.get_subclass("hb-champion") is not None
    assert loader.get_subclass("hb-nope") is None
    assert loader.get_background("hb-sage") is not None
    assert loader.get_background("hb-nope") is None
    assert loader.get_feat("hb-alert") is not None
    assert loader.get_feat("hb-nope") is None
    assert loader.get_feature("hb-action-surge") is not None
    assert loader.get_feature("hb-nope") is None
    assert ("monsters", "hb-goblin") in loader
    assert ("monsters", "hb-nope") not in loader


def test_overlay_covers_conditions_get_and_fallthrough() -> None:
    base_prone = _condition("prone")
    overlay_hb = _condition("hb-blinded")
    loader = OverlayAssetLoader(
        base=MemoryAssetLoader(conditions=[base_prone]),
        overlay=MemoryAssetLoader(conditions=[overlay_hb]),
    )
    assert loader.get_condition("prone") is base_prone  # base hit
    assert loader.get_condition("hb-blinded") is overlay_hb  # base miss -> overlay fallthrough
    assert loader.get_condition("nope") is None  # unknown slug
    assert ("conditions", "prone") in loader
    assert ("conditions", "hb-blinded") in loader
    assert ("conditions", "nope") not in loader


def test_overlay_list_conditions_merges_base_first_no_duplicates() -> None:
    shared = _condition("prone")
    overlay_shadow = _condition("prone")  # same slug — must not duplicate, base wins on get
    overlay_extra = _condition("hb-blinded")
    loader = OverlayAssetLoader(
        base=MemoryAssetLoader(conditions=[shared, _condition("unconscious")]),
        overlay=MemoryAssetLoader(conditions=[overlay_shadow, overlay_extra]),
    )
    assert loader.list_conditions() == ["prone", "unconscious", "hb-blinded"]
    assert loader.get_condition("prone") is shared
