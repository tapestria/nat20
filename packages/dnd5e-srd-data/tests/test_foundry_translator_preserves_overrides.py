from datetime import date
from pathlib import Path

from tools.translators.foundry import translate_weapon_yaml, write_canonical_with_overrides

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_override_preserved_on_regen(tmp_path):
    canonical_dir = tmp_path / "items"
    canonical_dir.mkdir(parents=True)

    # First pass: write fresh canonical
    w = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
    )
    write_canonical_with_overrides(w, canonical_dir)

    # Reviewer edits: corrects weight, sets known_divergence
    on_disk_path = canonical_dir / "longsword.json"
    import json

    blob = json.loads(on_disk_path.read_text())
    blob["weight"] = 4.0  # corrected value
    blob["review"]["known_divergence"] = "Foundry has 3.0; SRD PDF says 4.0"
    on_disk_path.write_text(json.dumps(blob))

    # Second pass: regen with the same Foundry YAML
    w2 = translate_weapon_yaml(
        yaml_path=FIXTURE / "weapons" / "longsword.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
    )
    write_canonical_with_overrides(w2, canonical_dir)

    # Reviewer's corrections must survive
    final = json.loads(on_disk_path.read_text())
    assert final["weight"] == 4.0
    assert final["review"]["known_divergence"] == "Foundry has 3.0; SRD PDF says 4.0"
