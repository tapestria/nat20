from __future__ import annotations

import dataclasses
import random
import re
import secrets
from importlib.metadata import version
from typing import Any, Literal

from dnd5e_engine import (
    CheckSpec,
    HitDicePool,
    make_build_spec,
    resolve_check,
    resolve_long_rest,
    resolve_short_rest,
    roll_dice_str,
)
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

# Short-form -> canonical ability name. `resolve_check`'s underlying skill /
# ability / saving-throw resolvers key `ability_scores` (and match
# `proficient_saves` / the derived-from-skill ability) by the long form, so
# any abbreviated input from a route body is normalized before it reaches
# the engine.
_ABILITY_ALIASES = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


def _slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


def _full_ability(name: str) -> str:
    lowered = name.strip().lower()
    return _ABILITY_ALIASES.get(lowered, lowered)


def _resolve_seed(seed: int | None) -> int:
    return seed if seed is not None else secrets.randbits(32)


def _do_roll(req: _RollRequest) -> dict[str, Any]:
    seed = _resolve_seed(req.seed)
    # `roll_dice_str` is the engine's standalone narrator-time dice seam
    # (rules/effects.py) — it draws from the stdlib global `random` module
    # by design ("Public test seam: callers monkeypatch this symbol (or
    # random.randint) for determinism"), not an injectable `random.Random`.
    # Seeding the global module is the sanctioned way to make this call
    # reproducible.
    random.seed(seed)
    try:
        total = roll_dice_str(req.dice)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid dice expression {req.dice!r}: {exc}"
        ) from exc
    return {"total": total, "dice": req.dice, "seed": seed}


def _check_summary(result: Any) -> str:
    label = result.skill or result.ability
    if result.dc is None:
        return f"{label} check: {result.roll_total}"
    outcome = "success" if result.success else "failure"
    return f"{label} check: {result.roll_total} vs DC {result.dc} -> {outcome}"


def _do_check(req: _CheckRequest) -> dict[str, Any]:
    seed = _resolve_seed(req.seed)
    short_scores = req.ability_scores.model_dump(by_alias=True)
    ability_scores = {full: short_scores[short] for short, full in _ABILITY_ALIASES.items()}
    spec = CheckSpec(
        kind=req.kind,
        ability_scores=ability_scores,
        proficient_skills=req.proficient_skills,
        proficient_saves=tuple(_full_ability(s) for s in req.proficient_saves),
        proficiency_bonus=req.proficiency_bonus,
        skill=req.skill,
        ability=_full_ability(req.ability) if req.ability else None,
        dc=req.dc,
        advantage=req.advantage,
        disadvantage=req.disadvantage,
    )
    random.seed(seed)
    try:
        result = resolve_check(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    body = dataclasses.asdict(result)
    body["seed"] = seed
    body["summary"] = _check_summary(result)
    return body


def _do_rest_short(req: _ShortRestRequest) -> dict[str, Any]:
    seed = _resolve_seed(req.seed)
    pool = HitDicePool(
        hit_die_size=req.hit_die_size,
        dice_remaining=req.dice_remaining,
        dice_total=req.dice_total,
    )
    rng = random.Random(seed)
    try:
        outcome = resolve_short_rest(pool, req.dice_to_spend, req.con_modifier, rng=rng)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    hp_current = min(req.hp_current + outcome.healed, req.hp_max)
    return {
        "healed": outcome.healed,
        "dice_spent": outcome.dice_spent,
        "hp_current": hp_current,
        "dice_remaining": outcome.dice_remaining,
        "seed": seed,
    }


def _do_rest_long(req: _LongRestRequest) -> dict[str, Any]:
    seed = _resolve_seed(req.seed)
    pool = HitDicePool(
        hit_die_size=req.hit_die_size,
        dice_remaining=req.dice_remaining,
        dice_total=req.dice_total,
    )
    outcome = resolve_long_rest(pool, req.hp_current, req.hp_max)
    return {
        "healed": outcome.healed,
        "dice_spent": outcome.dice_spent,
        "hp_current": outcome.hp_current,
        "dice_remaining": outcome.dice_remaining,
        "seed": seed,
    }


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


class _RollRequest(BaseModel):
    dice: str
    seed: int | None = None


class _CheckRequest(BaseModel):
    kind: Literal["skill", "ability", "saving_throw"]
    ability: str | None = None
    skill: str | None = None
    dc: int | None = None
    ability_scores: _AbilityScores = Field(default_factory=lambda: _AbilityScores())
    proficient_skills: tuple[str, ...] = ()
    proficient_saves: tuple[str, ...] = ()
    proficiency_bonus: int = 0
    advantage: bool = False
    disadvantage: bool = False
    seed: int | None = None


class _ShortRestRequest(BaseModel):
    hit_die_size: int
    dice_remaining: int
    dice_total: int
    dice_to_spend: int
    con_modifier: int
    hp_current: int
    hp_max: int
    seed: int | None = None


class _LongRestRequest(BaseModel):
    hit_die_size: int
    dice_remaining: int
    dice_total: int
    hp_current: int
    hp_max: int
    seed: int | None = None


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

    @app.post("/v1/roll")
    def roll(req: _RollRequest) -> dict[str, Any]:
        return _do_roll(req)

    @app.post("/v1/check")
    def check(req: _CheckRequest) -> dict[str, Any]:
        return _do_check(req)

    @app.post("/v1/rest/short")
    def rest_short(req: _ShortRestRequest) -> dict[str, Any]:
        return _do_rest_short(req)

    @app.post("/v1/rest/long")
    def rest_long(req: _LongRestRequest) -> dict[str, Any]:
        return _do_rest_long(req)

    return app
