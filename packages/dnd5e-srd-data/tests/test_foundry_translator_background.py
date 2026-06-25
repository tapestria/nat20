from datetime import date
from pathlib import Path

import pytest

from dnd5e_srd_data import Background
from tools.translators.foundry import translate_background_yaml

PACKS = Path("raw_sources/foundry/packs/_source")
pytestmark = pytest.mark.skipif(not PACKS.is_dir(), reason="raw_sources/foundry not populated")

BACKGROUNDS = (
    Path(__file__).resolve().parents[1]
    / "raw_sources"
    / "foundry"
    / "packs"
    / "_source"
    / "origins24"
    / "backgrounds"
)


def _translate(name: str) -> Background:
    return translate_background_yaml(
        yaml_path=BACKGROUNDS / name,
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )


def test_translates_acolyte() -> None:
    bg = _translate("acolyte.yml")
    assert isinstance(bg, Background)
    assert bg.slug == "acolyte"
    assert bg.name == "Acolyte"
    # locked = [str, dex, con] → improvable = {int, wis, cha}
    assert bg.ability_options.options == frozenset({"int", "wis", "cha"})
    assert bg.ability_options.cap == 2
    assert bg.ability_options.points == 3
    assert bg.skill_proficiencies == ["ins", "rel"]
    assert bg.tool_proficiencies == ["art:calligrapher"]
    assert bg.languages == ["common"]
    assert bg.starting_feat_slug == "phbftMagicInitia"
    assert bg.wealth == "50"
    assert bg.starting_equipment  # preserved structurally
    assert bg.provenance.srd_version == frozenset({"5.2"})


def test_translates_criminal_advancement_order_independent() -> None:
    # Criminal orders advancement as [ASI, ItemGrant, Trait(profs), Trait(langs)]
    # — the feat sits BEFORE the proficiency Trait. The translator must not rely
    # on positional order.
    bg = _translate("criminal.yml")
    assert bg.slug == "criminal"
    assert bg.ability_options.options == frozenset({"dex", "con", "int"})
    assert bg.skill_proficiencies == ["slt", "ste"]
    assert bg.tool_proficiencies == ["thief"]
    assert bg.languages == ["common"]
    assert bg.starting_feat_slug == "phbftAlert000000"


def test_translates_soldier_tool_choice_pool() -> None:
    # Soldier's proficiency Trait grants two skills (fixed) plus a tool CHOICE
    # from the gaming-set pool (tool:game:*). The translator surfaces the pool
    # option alongside the fixed grants.
    bg = _translate("soldier.yml")
    assert bg.slug == "soldier"
    assert bg.ability_options.options == frozenset({"str", "dex", "con"})
    assert bg.skill_proficiencies == ["ath", "itm"]
    assert "game:*" in bg.tool_proficiencies
    assert bg.starting_feat_slug == "phbftSavageAttac"
