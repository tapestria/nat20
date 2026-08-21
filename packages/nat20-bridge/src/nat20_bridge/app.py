from __future__ import annotations

from importlib.metadata import version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nat20_bridge import __version__
from nat20_bridge.state import BridgeState


def create_app(state: BridgeState) -> FastAPI:
    app = FastAPI(title="nat20-bridge", version=__version__)
    # The ST extension fetches cross-origin from the SillyTavern page; the
    # bridge binds loopback so permissive CORS is acceptable here.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {
            "bridge": __version__,
            "engine": version("dnd5e-engine"),
            "data": version("dnd5e-srd-data"),
        }

    return app
