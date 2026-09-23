"""``Monster.legendary_resistance_uses`` / ``legendary_action_uses`` — the
pool sizes Foundry types on ``system.resources.legres.max`` /
``system.resources.legact.max`` (SRD 5.2 "Legendary Resistance (N/Day)" and
"Legendary Action Uses: N"). A 0 (every non-legendary NPC) is ``None``."""

from datetime import date
from pathlib import Path

import yaml

from dnd5e_srd_data import Monster
from dnd5e_srd_data.loader import BundledAssetLoader
from tools.translators.foundry import translate_monster_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def _translate(path: Path) -> Monster:
    return translate_monster_yaml(
        yaml_path=path,
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )


def test_translator_reads_legres_and_legact_max(tmp_path: Path) -> None:
    doc = yaml.safe_load((FIXTURE / "monsters" / "mage-lite.yml").read_text())
    doc["system"]["resources"] = {
        "legact": {"max": 3, "spent": 0},
        "legres": {"max": 4, "spent": 0},
    }
    path = tmp_path / "mage-lite.yml"
    path.write_text(yaml.safe_dump(doc))
    m = _translate(path)
    assert m.legendary_resistance_uses == 4
    assert m.legendary_action_uses == 3


def test_translator_maps_zero_or_absent_pools_to_none(tmp_path: Path) -> None:
    assert _translate(FIXTURE / "monsters" / "goblin.yml").legendary_resistance_uses is None
    doc = yaml.safe_load((FIXTURE / "monsters" / "mage-lite.yml").read_text())
    doc["system"]["resources"] = {"legact": {"max": 0}, "legres": {"max": 0}}
    path = tmp_path / "mage-lite.yml"
    path.write_text(yaml.safe_dump(doc))
    m = _translate(path)
    assert m.legendary_resistance_uses is None
    assert m.legendary_action_uses is None


def test_bundled_corpus_carries_the_typed_pool_sizes() -> None:
    loader = BundledAssetLoader()

    def pools(slug: str) -> tuple[int | None, int | None]:
        m = loader.get_monster(slug)
        assert m is not None
        return m.legendary_resistance_uses, m.legendary_action_uses

    # Verified against raw_sources/foundry/packs/_source/actors24/**:
    # legres.max is 3 for the adult dragons, 4 for the ancient dragons except
    # gold (3), Kraken, Lich, Pit Fiend and Solar, and 6 for the Tarrasque;
    # legact.max is 3 for every legendary-action monster.
    assert pools("adult-red-dragon") == (3, 3)
    assert pools("ancient-red-dragon") == (4, 3)
    assert pools("ancient-gold-dragon") == (3, 3)
    assert pools("lich") == (4, 3)
    assert pools("tarrasque") == (6, 3)
    assert pools("wolf") == (None, None)
