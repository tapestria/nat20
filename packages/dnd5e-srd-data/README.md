# dnd5e-srd-data

The dataset of [Nat20](https://github.com/tapestria/nat20): the D&D 5e SRD 5.2
(CC-BY-4.0) as typed Python models, shipped inside the package. No network, no database.
The [dnd5e-engine](https://pypi.org/project/dnd5e-engine/) rules engine resolves combat
against it, and it works on its own as a typed SRD lookup.

```bash
pip install dnd5e-srd-data
```

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
