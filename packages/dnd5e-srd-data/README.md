# dnd5e-srd-data

Canonical D&D 5e SRD 5.2 asset dataset shipped as a Python package. Consumed by
[dnd5e-engine](../dnd5e-engine/) for combat resolution.

## Usage

```python
from dnd5e_srd_data import BundledAssetLoader

loader = BundledAssetLoader()
aboleth = loader.get_monster("aboleth")
print(aboleth.hp)  # 135
```

## License

Dataset content is CC-BY-4.0. See `NOTICE` for attribution chain.
Schema and tooling code is MIT-aligned and lives in the same package
for distribution convenience.

## Regenerating canonical data

```bash
make refresh-upstream    # pulls vendored Foundry + open5e snapshots
make regen               # translates + audits + writes canonical/*.json
```

The pinned upstream sources are recorded in `raw_sources/PINS.json` and
`raw_sources/README.md`; the raw snapshots are regenerated locally, not distributed.
