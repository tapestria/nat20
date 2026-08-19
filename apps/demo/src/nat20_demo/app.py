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

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import TypeAdapter, ValidationError

from nat20_demo.render import (
    actions_context,
    grid_context,
    initiative_context,
    status_context,
    tape_lines,
)
from nat20_demo.replay import (
    Command,
    FightLog,
    LogTooLargeError,
    ReplayOutcome,
    decode_log,
    encode_log,
    replay_fight,
)
from nat20_demo.scenarios import Scenario, all_scenarios, fresh_specs, get_scenario

__all__ = ["app", "create_app"]

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"

_COMMAND_ADAPTER: TypeAdapter[Command] = TypeAdapter(Command)


def _entity_names(scenario: Scenario) -> dict[str, str]:
    """entity_id -> display name, across both party and encounter."""
    names: dict[str, str] = {}
    for p in scenario.party:
        names[p.entity_id] = p.name
    for m in scenario.encounter:
        names[m.entity_id] = m.name
    return names


def _state_context(
    scenario: Scenario, out: ReplayOutcome, names: dict[str, str]
) -> dict[str, object]:
    """The grid/initiative/status/actions/outcome context shared by ``/play``
    and ``/act`` — every field a partial that renders one of those regions
    needs, computed from one replay's :class:`ReplayOutcome`.
    """
    return {
        "grid": grid_context(scenario, out),
        "initiative": initiative_context(out),
        "status": status_context(scenario, out),
        "actions": actions_context(scenario, out),
        "outcome": out.outcome,
        "names": names,
    }


def _error_fragment(message: str) -> str:
    """A minimal standalone HTML snippet for the ``/act`` error paths.

    Unlike ``error.html`` (a full page extending ``shell.html``), ``/act``
    responses are htmx fragments swapped into an existing page — they must
    never carry a nested ``<html>``/``<head>``/``<body>``.
    """
    return f'<p class="error-fragment">{message}</p>'


async def _play_response(
    templates: Jinja2Templates,
    request: Request,
    scenario_id: str,
    seed: int | None,
    log: str | None,
) -> HTMLResponse:
    try:
        scenario = get_scenario(scenario_id)
    except KeyError:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"heading": "Unknown scenario", "message": f'No scenario named "{scenario_id}".'},
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
        "tape": tape_lines(out.all_events, names),
        **_state_context(scenario, out, names),
    }
    return templates.TemplateResponse(request, "play.html", context)


def _act_repro_message(scenario_id: str, seed: int, log: str) -> str:
    return (
        "Something went wrong replaying this fight. Copy this block into "
        "a GitHub issue — it reproduces the bug exactly: "
        f"scenario={scenario_id} seed={seed} log={log}"
    )


async def _act_rejected_response(
    templates: Jinja2Templates,
    request: Request,
    scenario: Scenario,
    names: dict[str, str],
    original_log: FightLog,
    new_log: FightLog,
    accepted: int,
    rejected_reason: str,
) -> HTMLResponse:
    """Controller Ruling 2: ANY rejection during this replay — whether it came
    from a command already in the log or the one just submitted — means the
    response must show only the true accepted prefix (``accepted`` commands
    from the start of ``new_log``, which is also the start of
    ``original_log``) and must return the original log completely unchanged.
    Never persist a log that includes a command that failed replay.
    """
    prefix_log = new_log.model_copy(update={"commands": new_log.commands[:accepted]})
    prefix_out = await replay_fight(prefix_log, *fresh_specs(scenario))
    context = {
        "request": request,
        "scenario": scenario,
        "seed": original_log.seed,
        "tape": [],
        "rejected_reason": rejected_reason,
        "encoded_log": encode_log(original_log),
        **_state_context(scenario, prefix_out, names),
    }
    return templates.TemplateResponse(request, "_act_response.html", context)


async def _act_response(
    templates: Jinja2Templates,
    request: Request,
    scenario_id: str,
    seed: int,
    log: str,
    command: str,
) -> HTMLResponse:
    try:
        scenario = get_scenario(scenario_id)
    except KeyError:
        return HTMLResponse(_error_fragment(f'Unknown scenario "{scenario_id}".'), status_code=404)

    try:
        original_log = decode_log(log)
    except ValueError as exc:
        return HTMLResponse(_error_fragment(f"Malformed fight log: {exc}"), status_code=400)

    try:
        new_command = _COMMAND_ADAPTER.validate_json(command)
    except ValidationError as exc:
        return HTMLResponse(_error_fragment(f"Malformed command: {exc}"), status_code=400)

    new_log = original_log.model_copy(update={"commands": [*original_log.commands, new_command]})
    names = _entity_names(scenario)

    try:
        out = await replay_fight(new_log, *fresh_specs(scenario))
    except LogTooLargeError as exc:
        return HTMLResponse(_error_fragment(f"Fight log too large: {exc}"), status_code=400)
    except Exception:  # noqa: BLE001  # unexpected engine error -> 500 repro fragment
        # Never leak a stack trace to the player; hand back exactly what
        # reproduces the bug instead.
        return HTMLResponse(
            _error_fragment(_act_repro_message(scenario_id, seed, log)), status_code=500
        )

    if out.rejected_reason is not None:
        return await _act_rejected_response(
            templates,
            request,
            scenario,
            names,
            original_log,
            new_log,
            out.accepted,
            out.rejected_reason,
        )

    context = {
        "request": request,
        "scenario": scenario,
        "seed": new_log.seed,
        "tape": tape_lines(out.delta_events, names),
        "rejected_reason": None,
        "encoded_log": encode_log(new_log),
        **_state_context(scenario, out, names),
    }
    return templates.TemplateResponse(request, "_act_response.html", context)


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
        return await _play_response(templates, request, scenario_id, seed, log)

    @app.get("/about", response_class=HTMLResponse)
    async def about(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "about.html", {})

    @app.post("/play/{scenario_id}/act", response_class=HTMLResponse)
    async def act(
        request: Request,
        scenario_id: str,
        seed: int = Form(...),
        log: str = Form(...),
        command: str = Form(...),
    ) -> HTMLResponse:
        return await _act_response(templates, request, scenario_id, seed, log, command)

    return app


app = create_app()
