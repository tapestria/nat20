from pathlib import Path

import pytest

from dnd5e_srd_data import BundledAssetLoader, Monster, Weapon

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "canonical"


@pytest.fixture
def loader() -> BundledAssetLoader:
    return BundledAssetLoader(root=FIXTURE_ROOT)


def test_bundled_loader_finds_monster_in_fixture_tree(loader: BundledAssetLoader):
    m = loader.get_monster("test-goblin")
    assert isinstance(m, Monster)
    assert m.name == "Test Goblin"


def test_bundled_loader_returns_none_for_unknown(loader: BundledAssetLoader):
    assert loader.get_monster("nonexistent") is None


def test_bundled_loader_finds_weapon(loader: BundledAssetLoader):
    w = loader.get_weapon("test-longsword")
    assert isinstance(w, Weapon)
    assert w.name == "Test Longsword"


def test_bundled_loader_lists_slugs(loader: BundledAssetLoader):
    assert "test-goblin" in loader.list_slugs("monsters")
    assert "test-longsword" in loader.list_slugs("items")


def test_bundled_get_spell_by_uuid():
    loader = BundledAssetLoader()
    spell = loader.get_spell("lightning-bolt")
    assert spell is not None
    assert spell.foundry_uuid
    assert loader.get_spell_by_uuid(spell.foundry_uuid) is not None
    assert loader.get_spell_by_uuid(spell.foundry_uuid).slug == "lightning-bolt"
    assert loader.get_spell_by_uuid("Compendium.dnd5e.spells24.Item.missing") is None


def test_bundled_mage_and_dragon_carry_their_spellcasting_ability():
    loader = BundledAssetLoader()
    assert loader.get_monster("mage").spellcasting_ability == "int"
    # Verified against raw_sources/foundry/packs/_source/actors24/dragon/
    # adult-red-dragon.yml: the 2024 SRD adult red dragon carries an innate
    # Charisma-based spellcasting ability.
    assert loader.get_monster("adult-red-dragon").spellcasting_ability == "cha"
    # The wolf's raw field is "str" — a placeholder Foundry leaves on non-
    # spellcasting NPCs (SRD 5.2 spellcasting is always int/wis/cha), which
    # the translator normalizes to None.
    assert loader.get_monster("wolf").spellcasting_ability is None


# Known legacy-pack cast reference: rod-of-alertness delegates to the 2014
# "spells" compendium, which the SRD 5.2 corpus does not carry. Tracked as
# upstream data debt — every other cast uuid must resolve.
_KNOWN_UNRESOLVABLE_CAST_UUIDS = {"Compendium.dnd5e.spells.Item.Mzh95utKDPIrjiH8"}


def test_every_item_cast_uuid_resolves_against_spell_corpus():
    loader = BundledAssetLoader()
    unresolved: dict[str, str] = {}
    for slug in loader.list_slugs("items"):
        item = loader.get_item(slug)
        assert item is not None
        for activity in item.activities:
            uuid = getattr(getattr(activity, "spell", None), "uuid", "")
            if not uuid or uuid in _KNOWN_UNRESOLVABLE_CAST_UUIDS:
                continue
            if loader.get_spell_by_uuid(uuid) is None:
                unresolved[slug] = uuid
    assert unresolved == {}


def test_bundled_loader_reads_conditions_category(loader: BundledAssetLoader):
    from dnd5e_srd_data.schema.condition import Condition, ConditionEffectKind

    prone = loader.get_condition("test-prone")
    assert isinstance(prone, Condition)
    assert prone.effects[0].kind is ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST
    assert loader.list_conditions() == ["test-prone"]
    assert loader.get_condition("missing") is None
    assert ("conditions", "test-prone") in loader


def test_conditions_is_a_loader_category():
    from dnd5e_srd_data.loader import _CATEGORIES

    assert "conditions" in _CATEGORIES


def test_traits_is_a_loader_category():
    from dnd5e_srd_data.loader import _CATEGORIES

    assert "traits" in _CATEGORIES
