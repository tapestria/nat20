import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.item import Weapon

from nat20_bridge.forge import ForgeError, forge_item


def test_forge_patches_name_slug_bonus_and_damage() -> None:
    raw = forge_item(
        name="Frost Brand",
        base="longsword",
        loader=BundledAssetLoader(),
        bonus=1,
        extra_damage="1d6:cold",
    )
    weapon = Weapon.model_validate(raw)
    assert weapon.slug == "hb-frost-brand"
    assert weapon.name == "Frost Brand"
    assert weapon.magical_bonus == 1
    assert any(p.dice == "1d6" and p.damage_type == "cold" for p in weapon.damage_parts)
    # base damage kept
    assert any(p.damage_type == "slashing" for p in weapon.damage_parts)


def test_forge_rejects_unknown_base_and_non_weapon() -> None:
    loader = BundledAssetLoader()
    with pytest.raises(ForgeError):
        forge_item(name="X", base="no-such-slug", loader=loader)
    with pytest.raises(ForgeError):
        forge_item(name="X", base="fireball", loader=loader)  # a spell, not an item


def test_forge_rejects_malformed_damage() -> None:
    with pytest.raises(ForgeError):
        forge_item(name="X", base="longsword", loader=BundledAssetLoader(), extra_damage="coldish")


def test_forge_rejects_negative_bonus_below_zero() -> None:
    # A mundane base (magical_bonus == 0) plus a negative bonus would drive
    # magical_bonus below zero, violating the schema's NonNegativeInt
    # constraint — this must surface as ForgeError, not an uncaught
    # pydantic ValidationError.
    with pytest.raises(ForgeError):
        forge_item(name="Cursed Blade", base="longsword", loader=BundledAssetLoader(), bonus=-1)


def test_forge_sanitizes_path_like_names_into_clean_slugs() -> None:
    raw = forge_item(name="../../evil", base="longsword", loader=BundledAssetLoader())
    weapon = Weapon.model_validate(raw)
    assert weapon.slug == "hb-evil"


def test_forge_rejects_names_with_no_usable_characters() -> None:
    with pytest.raises(ForgeError):
        forge_item(name="///", base="longsword", loader=BundledAssetLoader())
