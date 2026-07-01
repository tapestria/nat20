import json
from pathlib import Path

import pytest

from dnd5e_srd_data import BundledAssetLoader

CANONICAL = Path(__file__).resolve().parent.parent / "src" / "dnd5e_srd_data" / "canonical"


@pytest.mark.parametrize("category", ["items", "monsters"])
def test_every_canonical_entry_round_trips(category: str):
    loader = BundledAssetLoader()
    for slug in loader.list_slugs(category):  # type: ignore[arg-type]
        entry = loader.get_item(slug) if category == "items" else loader.get_monster(slug)
        assert entry is not None, f"loader couldn't read {category}/{slug}"

        path = CANONICAL / category / f"{slug}.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        from_model = entry.model_dump(mode="json")

        # JSON sort_keys + indent=2 written by translator; same shape from model_dump.
        assert json.dumps(on_disk, sort_keys=True) == json.dumps(from_model, sort_keys=True), (
            f"{category}/{slug} doesn't round-trip"
        )
