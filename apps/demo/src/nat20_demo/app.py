"""The demo's FastAPI app shell — catalog, play, and about pages.

# htmx 2.0.10 (vendored at static/htmx.min.js — https://unpkg.com/htmx.org@2.0.10)

The app holds no server-side state: every ``/play`` request replays a
:class:`~nat20_demo.replay.FightLog` from scratch (Task 3) against a
scenario from the catalog (Task 4), then renders the result through the
pure context builders in :mod:`nat20_demo.render` (Task 5). Task 7 adds
the ``POST /play/{scenario_id}/act`` endpoint this page's buttons target.

Only top-level ``dnd5e_engine`` names are imported here, per the demo's
``__all__``-is-the-contract rule.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nat20_demo.render import (
    actions_context,
    grid_context,
    initiative_context,
    status_context,
    tape_lines,
)
from nat20_demo.replay import FightLog, LogTooLargeError, decode_log, encode_log, replay_fight
from nat20_demo.scenarios import Scenario, all_scenarios, fresh_specs, get_scenario

__all__ = ["app", "create_app"]

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"


def _entity_names(scenario: Scenario) -> dict[str, str]:
    """entity_id -> display name, across both party and encounter."""
    names: dict[str, str] = {}
    for p in scenario.party:
        names[p.entity_id] = p.name
    for m in scenario.encounter:
        names[m.entity_id] = m.name
    return names


def create_app() -> FastAPI:
    app = FastAPI(title="Nat20 demo")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse)
    async def catalog(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "catalog.html", {"scenarios": all_scenarios()})

    @app.get("/play/{scenario_id}", response_class=HTMLResponse)
    async def play(
        request: Request,
        scenario_id: str,
        seed: int | None = None,
        log: str | None = None,
    ) -> HTMLResponse:
        try:
            scenario = get_scenario(scenario_id)
        except KeyError:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "heading": "Unknown scenario",
                    "message": f'No scenario named "{scenario_id}".',
                },
                status_code=404,
            )

        if log is not None:
            try:
                fight_log = decode_log(log)
            except ValueError as exc:
                return templates.TemplateResponse(
                    request,
                    "error.html",
                    {"heading": "Malformed fight log", "message": str(exc)},
                    status_code=400,
                )
        else:
            fight_log = FightLog(scenario_id=scenario_id, seed=seed or scenario.default_seed)

        try:
            out = await replay_fight(fight_log, *fresh_specs(scenario))
        except LogTooLargeError as exc:
            return templates.TemplateResponse(
                request,
                "error.html",
                {"heading": "Fight log too large", "message": str(exc)},
                status_code=400,
            )

        names = _entity_names(scenario)
        context = {
            "scenario": scenario,
            "seed": fight_log.seed,
            "encoded_log": encode_log(fight_log),
            "grid": grid_context(scenario, out),
            "initiative": initiative_context(out),
            "status": status_context(scenario, out),
            "actions": actions_context(scenario, out),
            "tape": tape_lines(out.all_events, names),
            "outcome": out.outcome,
            "names": names,
        }
        return templates.TemplateResponse(request, "play.html", context)

    @app.get("/about", response_class=HTMLResponse)
    async def about(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "about.html", {})

    return app


app = create_app()
