"""Pure renderers — engine views/events → plain-dict template contexts.

Everything here is a pure function over public engine/demo types (no I/O,
no mutation). Task 6's Jinja templates and Task 7's endpoint handlers are
the only consumers; keeping this module free of FastAPI/Jinja imports
means it can be unit-tested without either.

Only top-level ``dnd5e_engine`` names are imported here, per the demo's
``__all__``-is-the-contract rule.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from dnd5e_engine import CombatEvent, GridScene, LiveCombatView, PlayerIntent, cell_id, parse_cell

from nat20_demo.replay import IntentCommand, MonsterTurnCommand, ReplayOutcome
from nat20_demo.scenarios import Scenario

__all__ = [
    "actions_context",
    "grid_context",
    "initiative_context",
    "status_context",
    "tape_lines",
]


def _entity_names(scenario: Scenario) -> dict[str, str]:
    """entity_id -> display name, across both party and encounter."""
    names: dict[str, str] = {}
    for p in scenario.party:
        names[p.entity_id] = p.name
    for m in scenario.encounter:
        names[m.entity_id] = m.name
    return names


def _current_actor_id(out: ReplayOutcome) -> str | None:
    view = out.view
    if not view.initiative:
        return None
    index = view.current_turn_index % len(view.initiative)
    return view.initiative[index].entity_id


def _cell_kind(grid: GridScene, blocked: set[str], difficult: set[str], cid: str) -> str:
    if cid in blocked:
        return "blocked"
    if cid in difficult:
        return "difficult"
    cover = grid.cover_cells.get(cid)
    if cover is not None:
        return f"cover_{cover}"
    return "floor"


def _cell_token(
    view: LiveCombatView,
    names: dict[str, str],
    current_actor_id: str | None,
    occupant_id: str | None,
) -> dict[str, Any] | None:
    if occupant_id is None:
        return None
    return {
        "entity_id": occupant_id,
        "name": names.get(occupant_id, occupant_id),
        "side": "pc" if occupant_id in view.party_ids else "foe",
        "dead": occupant_id in view.dead_ids,
        "current": occupant_id == current_actor_id,
    }


def _move_reach(
    scenario: Scenario, out: ReplayOutcome, current_actor_id: str | None
) -> tuple[tuple[int, int], int] | None:
    """The current PC actor's cell + speed, or ``None`` if candidates don't apply.

    Candidates only apply on a living PC's own turn, mid-fight — never on a
    monster's turn or once the fight is over.
    """
    view = out.view
    if out.is_over or current_actor_id is None or current_actor_id not in view.party_ids:
        return None
    actor_zone = view.actor_zone.get(current_actor_id)
    if actor_zone is None:
        return None
    member = next((p for p in scenario.party if p.entity_id == current_actor_id), None)
    return parse_cell(actor_zone), member.base_speed if member is not None else 30


def grid_context(scenario: Scenario, out: ReplayOutcome) -> dict[str, Any]:
    """The grid, its terrain, and the token occupying each cell (if any).

    ``move_candidate`` cells are a geometric HINT for the UI only — a
    Chebyshev-distance-within-speed reachability estimate that ignores
    difficult terrain doubling and line of sight. The engine is the sole
    authority on whether a submitted move is legal; a rejected move
    surfaces through the normal rejection path (see Task 7).

    Wall segments (``scenario.grid.wall_segments``) block line of sight,
    not movement, and are corner-to-corner edges rather than cells — they
    are not folded into any cell's ``kind`` here (the closed kind enum has
    no "wall" value). Task 6's template draws them directly from
    ``scenario.grid.wall_segments``.
    """
    view = out.view
    grid = scenario.grid
    names = _entity_names(scenario)

    blocked = set(grid.blocked_cells)
    difficult = set(grid.difficult_terrain_cells)

    # Last writer wins if multiple combatants share a cell (e.g. the
    # burning-hands scenario stacks four foes on one zone) — the grid
    # renders at most one token per cell by construction.
    occupant_by_cell: dict[str, str] = {}
    for entity_id, zone in view.actor_zone.items():
        occupant_by_cell[zone] = entity_id
    occupied_cells = set(occupant_by_cell.keys())

    current_actor_id = _current_actor_id(out)
    reach = _move_reach(scenario, out, current_actor_id)

    cells: list[dict[str, Any]] = []
    for row in range(grid.height):
        for col in range(grid.width):
            cid = cell_id(col, row)
            move_candidate = False
            if reach is not None:
                (actor_col, actor_row), actor_speed_ft = reach
                distance_ft = max(abs(col - actor_col), abs(row - actor_row)) * grid.cell_size_ft
                move_candidate = (
                    distance_ft <= actor_speed_ft
                    and cid not in blocked
                    and cid not in occupied_cells
                )

            move_command_json = None
            if move_candidate and current_actor_id is not None:
                move_command_json = IntentCommand(
                    actor=current_actor_id,
                    intent=PlayerIntent(intent_type="move", target_zone_id=cid),
                ).model_dump_json()

            cells.append(
                {
                    "col": col,
                    "row": row,
                    "cell_id": cid,
                    "kind": _cell_kind(grid, blocked, difficult, cid),
                    "token": _cell_token(view, names, current_actor_id, occupant_by_cell.get(cid)),
                    "move_candidate": move_candidate,
                    "move_command_json": move_command_json,
                }
            )

    return {"width": grid.width, "height": grid.height, "cells": cells}


def initiative_context(out: ReplayOutcome) -> list[dict[str, Any]]:
    """The initiative order, with side/dead/current flags per combatant."""
    view = out.view
    current_actor_id = _current_actor_id(out)
    return [
        {
            "entity_id": c.entity_id,
            "name": c.name,
            "side": "pc" if c.entity_id in view.party_ids else "foe",
            "dead": c.entity_id in view.dead_ids,
            "current": c.entity_id == current_actor_id,
        }
        for c in view.initiative
    ]


def status_context(scenario: Scenario, out: ReplayOutcome) -> list[dict[str, Any]]:
    """Per-combatant HP/conditions/slots/concentration status cards.

    ``concentrating`` is derived from ``Combatant.concentration_effect_id``
    (carried on each entry of ``LiveCombatView.initiative``) being
    non-``None`` — the public view has no top-level concentration field,
    but this per-combatant field is public and exact (it is the same field
    the orchestrator itself gates the single-concentration rule on), so no
    guessing is involved.
    """
    view = out.view
    names = _entity_names(scenario)
    result: list[dict[str, Any]] = []
    for c in view.initiative:
        result.append(
            {
                "entity_id": c.entity_id,
                "name": names.get(c.entity_id, c.name),
                "hp": view.tracked_hp.get(c.entity_id, c.hp_current),
                "hp_max": c.hp_max,
                "temp_hp": view.tracked_temp_hp.get(c.entity_id, c.temp_hp),
                "conditions": sorted(view.active_conditions.get(c.entity_id, set())),
                "slots": dict(view.spell_slots_by_entity.get(c.entity_id, {})),
                "concentrating": c.concentration_effect_id is not None,
            }
        )
    return result


def actions_context(scenario: Scenario, out: ReplayOutcome) -> dict[str, Any]:
    """The action menu for whoever's turn it is now.

    PC turns expand each ``needs_target`` option into one entry per living
    combatant on that option's ``target_side``: "foe" (the default; attacks,
    offensive AoE) expands over living encounter members (AoE casts target
    via ``target_id`` too — the target's zone becomes the anchor, per
    Task 4's verified targeting semantics); "ally" (heal spells) expands
    over living party members, including the caster themself (self-heal is
    legal). Monster turns offer the single "advance" command; a finished
    fight offers none.
    """
    view = out.view
    names = _entity_names(scenario)

    if out.is_over:
        return {"mode": "over", "actor": None, "options": [], "rejected": out.rejected_reason}

    current_actor_id = _current_actor_id(out)
    if current_actor_id is None:
        return {"mode": "over", "actor": None, "options": [], "rejected": out.rejected_reason}

    actor = {
        "entity_id": current_actor_id,
        "name": names.get(current_actor_id, current_actor_id),
        "side": "pc" if current_actor_id in view.party_ids else "foe",
    }

    if current_actor_id not in view.party_ids:
        options = [
            {
                "label": "Advance monster turn",
                "command_json": MonsterTurnCommand().model_dump_json(),
            }
        ]
        return {
            "mode": "monster_turn",
            "actor": actor,
            "options": options,
            "rejected": out.rejected_reason,
        }

    living_foes = [m.entity_id for m in scenario.encounter if m.entity_id not in view.dead_ids]
    living_allies = [p.entity_id for p in scenario.party if p.entity_id not in view.dead_ids]

    pc_options: list[dict[str, str]] = []
    for opt in scenario.actions.get(current_actor_id, []):
        if opt.needs_target:
            targets = living_allies if opt.target_side == "ally" else living_foes
            for target_id in targets:
                intent = opt.intent.model_copy(update={"target_id": target_id})
                command = IntentCommand(actor=current_actor_id, intent=intent)
                pc_options.append(
                    {
                        "label": f"{opt.label} — {names.get(target_id, target_id)}",
                        "command_json": command.model_dump_json(),
                    }
                )
        else:
            command = IntentCommand(actor=current_actor_id, intent=opt.intent)
            pc_options.append({"label": opt.label, "command_json": command.model_dump_json()})

    return {
        "mode": "pc_turn",
        "actor": actor,
        "options": pc_options,
        "rejected": out.rejected_reason,
    }


def _friendly_attack_rolled(e: Any, names: dict[str, str]) -> str:
    attacker = names.get(e.attacker_id, e.attacker_id)
    target = names.get(e.target_id, e.target_id)
    result = "crit" if e.is_crit and e.is_hit else ("hit" if e.is_hit else "miss")
    return f"{attacker} attacks {target} — {e.roll_total} vs AC: {result}"


def _friendly_save_rolled(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    outcome = "success" if e.succeeded else "failure"
    return f"{target} rolls a {e.ability.upper()} save: {e.roll_total} vs DC {e.dc} — {outcome}"


def _friendly_damage_applied(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    suffix = " (overkill)" if e.is_overkill else ""
    return f"{target} takes {e.amount} {e.damage_type} damage{suffix}"


def _friendly_healing_applied(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} heals {e.amount} HP"


def _friendly_temphp_applied(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} gains {e.amount} temporary HP"


def _friendly_effect_applied(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.effect.target_id, e.effect.target_id)
    return f"{target} gains {e.effect.name}"


def _friendly_condition_applied(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} is now {e.condition}"


def _friendly_concentration_check(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    outcome = "success" if e.succeeded else "failure"
    return f"{target} concentration check vs DC {e.dc}: {outcome}"


def _friendly_concentration_dropped(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} loses concentration on {e.effect_name}"


def _friendly_death_save_rolled(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} death save: {e.roll_total} — {e.outcome}"


def _friendly_unconscious(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} is unconscious"


def _friendly_death(e: Any, names: dict[str, str]) -> str:
    target = names.get(e.target_id, e.target_id)
    return f"{target} dies ({e.reason})"


def _friendly_actor_moved(e: Any, names: dict[str, str]) -> str:
    actor = names.get(e.actor_id, e.actor_id)
    return f"{actor} moves to {e.to_zone}"


def _friendly_dash_taken(e: Any, names: dict[str, str]) -> str:
    actor = names.get(e.actor_id, e.actor_id)
    return f"{actor} dashes"


def _friendly_turn_started(e: Any, names: dict[str, str]) -> str:
    actor = names.get(e.actor_id, e.actor_id)
    return f"{actor}'s turn begins"


def _friendly_round_started(e: Any, names: dict[str, str]) -> str:
    return f"Round {e.round_number} begins"


def _friendly_cast_failed(e: Any, names: dict[str, str]) -> str:
    actor = names.get(e.actor_id, e.actor_id)
    return f"{actor} fails to cast {e.spell_id}: {e.reason}"


def _friendly_attack_failed(e: Any, names: dict[str, str]) -> str:
    actor = names.get(e.actor_id, e.actor_id)
    return f"{actor} fails to attack: {e.reason}"


def _friendly_combat_ended(e: Any, names: dict[str, str]) -> str:
    return f"Combat ends: {e.reason}"


# Covers every event type the brief calls out. Since engine F2c the
# concentration-on-damage check emits ``concentration_check`` ALONGSIDE the
# ``save_rolled(ability="con")`` it has always emitted (the duplicate goes
# away in engine v0.7), so both renderers below are live.
_FRIENDLY: dict[str, Callable[[Any, dict[str, str]], str]] = {
    "attack_rolled": _friendly_attack_rolled,
    "save_rolled": _friendly_save_rolled,
    "damage_applied": _friendly_damage_applied,
    "healing_applied": _friendly_healing_applied,
    "temphp_applied": _friendly_temphp_applied,
    "effect_applied": _friendly_effect_applied,
    "condition_applied": _friendly_condition_applied,
    "concentration_check": _friendly_concentration_check,
    "concentration_dropped": _friendly_concentration_dropped,
    "death_save_rolled": _friendly_death_save_rolled,
    "unconscious": _friendly_unconscious,
    "death": _friendly_death,
    "actor_moved": _friendly_actor_moved,
    "dash_taken": _friendly_dash_taken,
    "turn_started": _friendly_turn_started,
    "round_started": _friendly_round_started,
    "cast_failed": _friendly_cast_failed,
    "attack_failed": _friendly_attack_failed,
    "combat_ended": _friendly_combat_ended,
}


# Structural markers with no narrative content — dropped from the tape rather
# than rendered. ``turn_phase`` (engine F3a) fires 2-3 times per turn boundary
# purely to tell a host WHERE the boundary is; the tape already shows the
# boundary via ``turn_started`` / ``round_started``, so printing the marker's
# raw payload alongside them would be noise, not information.
_SKIPPED_EVENT_TYPES: frozenset[str] = frozenset({"turn_phase"})


def tape_lines(events: list[CombatEvent], names: dict[str, str]) -> list[dict[str, str]]:
    """The combat-log tape: one friendly one-liner + raw JSON per event.

    Every event type renders something — types not in ``_FRIENDLY`` (and
    any future addition to the engine's closed ``CombatEvent`` union) fall
    back to ``"{type}: {payload}"`` rather than raising — except the purely
    structural types in ``_SKIPPED_EVENT_TYPES``, which produce no line at all.
    """
    lines: list[dict[str, str]] = []
    for e in events:
        if e.type in _SKIPPED_EVENT_TYPES:
            continue
        render = _FRIENDLY.get(e.type)
        text = render(e, names) if render is not None else f"{e.type}: {e.model_dump()}"
        lines.append(
            {
                "kind": e.type,
                "text": text,
                "raw": json.dumps(e.model_dump(), default=str),
            }
        )
    return lines
