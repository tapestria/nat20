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
