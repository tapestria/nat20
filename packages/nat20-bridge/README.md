# nat20-bridge

[Nat20](https://github.com/tapestria/nat20) over HTTP: a localhost REST API that puts
the [`dnd5e-engine`](https://pypi.org/project/dnd5e-engine/) D&D 5e SRD 5.2 rules
engine (backed by [`dnd5e-srd-data`](https://pypi.org/project/dnd5e-srd-data/)) behind
a small FastAPI surface. Any client that speaks HTTP can roll dice, resolve checks and
run a full fight with real rules. It is the backend of the
[SillyTavern nat20 extension](https://github.com/tapestria/SillyTavern-nat20).

The bridge binds to `127.0.0.1` by default — it is not intended to be exposed on
the network. CORS is permissive because the SillyTavern browser page fetches it
cross-origin from a loopback address.

## Running

```bash
uvx nat20-bridge      # from PyPI
uv run nat20-bridge   # from a checkout of this repository
```

Options:

- `--host` (default `127.0.0.1`)
- `--port` (default `8020`)
- `--data-dir` (default `~/.nat20-bridge`) — where `homebrew.json` persists.
- `--max-combats` (default `16`) — how many combats stay live at once; starting
  one more ends the least recently used.

## Development

```bash
uv sync --extra dev
make check
```
