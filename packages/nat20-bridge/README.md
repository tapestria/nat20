# nat20-bridge

A localhost HTTP sidecar that exposes the [`dnd5e-engine`](../dnd5e-engine) rules
engine (backed by [`dnd5e-srd-data`](../dnd5e-srd-data)) to the SillyTavern nat20
extension over a small FastAPI surface.

The bridge binds to `127.0.0.1` by default — it is not intended to be exposed on
the network. CORS is permissive because the SillyTavern browser page fetches it
cross-origin from a loopback address.

## Running

```bash
uv run nat20-bridge
```

Options:

- `--host` (default `127.0.0.1`)
- `--port` (default `8020`)
- `--data-dir` (default `~/.nat20-bridge`) — where `homebrew.json` persists.

## Development

```bash
uv sync --extra dev
make check
```
