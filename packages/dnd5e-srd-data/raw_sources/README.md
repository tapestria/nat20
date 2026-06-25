# raw_sources/

Pinned upstream snapshots consumed by translators. Gitignored — refresh with:

```bash
make refresh-upstream
```

Pins live in `PINS.json`. Bump deliberately (commit the PINS.json change),
then re-run `make regen`.

## Sources

- **Foundry VTT dnd5e** (`foundry/`) — https://github.com/foundryvtt/dnd5e
  License: CC-BY-4.0.
- **open5e** (`open5e/`) — https://github.com/open5e/open5e-api
  License: CC-BY-4.0 for SRD content; non-SRD content excluded by the SRD gate.
- **5e-bits/5e-database** (`five_e_bits/`) — https://github.com/5e-bits/5e-database
  License: MIT. Used for SRD-flag cross-check.
