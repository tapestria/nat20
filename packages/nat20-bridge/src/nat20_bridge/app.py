from __future__ import annotations

import re
from importlib.metadata import version
from typing import Any

from dnd5e_engine import make_build_spec
from dnd5e_srd_data.loader import BundledAssetLoader
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nat20_bridge import __version__
from nat20_bridge.sheet import derive_sheet
from nat20_bridge.state import BridgeState

# Module-level loader: production canonical-only data. A later task swaps in
# the homebrew-overlaying loader for routes that need it.
_LOADER = BundledAssetLoader()

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


class _AbilityScores(BaseModel):
    str_: int = Field(default=10, alias="str")
    dex: int = 10
    con: int = 10
    int_: int = Field(default=10, alias="int")
    wis: int = 10
    cha: int = 10

    model_config = {"populate_by_name": True}


class _BuildRequest(BaseModel):
    species_slug: str
    class_slug: str
    subclass_slug: str | None = None
    level: int = 1
    ability_scores: _AbilityScores = Field(default_factory=lambda: _AbilityScores())
    equipment: tuple[str, ...] = ()


class _PartyValidateRequest(BaseModel):
    name: str
    entity_id: str | None = None
    build: _BuildRequest
    spells_known: list[str] | None = None
    hp_current: int | None = None


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

    @app.post("/v1/party/validate")
    def party_validate(req: _PartyValidateRequest) -> dict[str, Any]:
        entity_id = req.entity_id or f"char:{_slugify(req.name)}"
        try:
            build_spec = make_build_spec(
                species_slug=req.build.species_slug,
                class_slug=req.build.class_slug,
                level=req.build.level,
                subclass_slug=req.build.subclass_slug,
                ability_scores=req.build.ability_scores.model_dump(by_alias=True),
                equipment=req.build.equipment,
            )
            member = derive_sheet(
                build_spec,
                name=req.name,
                entity_id=entity_id,
                loader=_LOADER,
                hp_current=req.hp_current,
                spells_known=req.spells_known,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        slots = ",".join(f"{lvl}:{count}" for lvl, count in member.spell_slots.items())
        summary = (
            f"{member.name} — lvl {member.character_level} {member.species_slug} "
            f"{member.class_slug}, HP {member.hp_current}/{member.hp_max}, "
            f"AC {member.ac}, slots {{{slots}}}"
        )
        return {"member": member.model_dump(), "summary": summary}

    return app
