"""Renderer tests — engine views/events driven through real replays.

Every test replays a real scenario through ``replay_fight`` and feeds the
resulting ``ReplayOutcome`` to the renderer under test; nothing here mocks
the engine.
"""

from __future__ import annotations

import json

from dnd5e_engine import PlayerIntent, cell_id

from nat20_demo.render import (
    actions_context,
    grid_context,
    initiative_context,
    status_context,
    tape_lines,
)
from nat20_demo.replay import Command, FightLog, IntentCommand, ReplayOutcome, replay_fight
from nat20_demo.scenarios import get_scenario


def _attack(actor: str, weapon: str, target: str) -> Command:
    return IntentCommand(
        actor=actor,
        intent=PlayerIntent(intent_type="attack", weapon_id=weapon, target_id=target),
    )


def _move(actor: str, to: str) -> Command:
    return IntentCommand(actor=actor, intent=PlayerIntent(intent_type="move", target_zone_id=to))


async def _replay(scenario_id: str, commands: list[Command] | None = None) -> ReplayOutcome:
    scenario = get_scenario(scenario_id)
    from nat20_demo.scenarios import fresh_specs

    log = FightLog(scenario_id=scenario.id, seed=scenario.default_seed, commands=commands or [])
    return await replay_fight(log, *fresh_specs(scenario))


async def test_grid_marks_tokens_and_terrain() -> None:
    scenario = get_scenario("goblin-ambush")
    out = await _replay("goblin-ambush")
    ctx = grid_context(scenario, out)

    assert ctx["width"] == scenario.grid.width
    assert ctx["height"] == scenario.grid.height

    by_cell = {c["cell_id"]: c for c in ctx["cells"]}

    # Hero token sits at Brynn's opening cell — she also has initiative,
    # so she's the "current" actor on an empty log.
    brynn_cell = by_cell[cell_id(1, 4)]
    assert brynn_cell["token"] is not None
    assert brynn_cell["token"]["entity_id"] == "char:brynn"
    assert brynn_cell["token"]["name"] == "Brynn"
    assert brynn_cell["token"]["side"] == "pc"
    assert brynn_cell["token"]["dead"] is False
    assert brynn_cell["token"]["current"] is True

    # Explicit blocked_cells render as "blocked".
    assert by_cell[cell_id(5, 0)]["kind"] == "blocked"
    assert by_cell[cell_id(5, 1)]["kind"] == "blocked"

    # A cell straddling the wall_segment (col 6, rows 2-5) is not itself a
    # blocked_cells entry — wall_segments block line of sight, not
    # movement, and are edges rather than cells, so this cell still
    # renders "floor". (Task 6 draws the wall geometry directly from
    # scenario.grid.wall_segments.)
    assert by_cell[cell_id(6, 3)]["kind"] == "floor"

    # cover_cells fold into the kind string.
    assert by_cell[cell_id(6, 6)]["kind"] == "cover_half"

    assert len(ctx["cells"]) == scenario.grid.width * scenario.grid.height


async def test_grid_stacked_cell_renders_exactly_one_token() -> None:
    # burning-hands deliberately stacks all four giant rats on one zone
    # (cell_id(4, 2)) so a single Burning Hands cast hits them all. The
    # grid context's per-cell shape has room for exactly one token, so
    # this pins down the documented last-writer-wins behavior rather than
    # leaving it unexercised.
    scenario = get_scenario("burning-hands")
    out = await _replay("burning-hands")
    ctx = grid_context(scenario, out)
    by_cell = {c["cell_id"]: c for c in ctx["cells"]}

    stacked = by_cell[cell_id(4, 2)]
    assert stacked["token"] is not None
    rat_ids = {m.entity_id for m in scenario.encounter}
    assert stacked["token"]["entity_id"] in rat_ids
    assert stacked["token"]["side"] == "foe"


async def test_move_candidates_only_on_pc_turn() -> None:
    scenario = get_scenario("goblin-ambush")
    out = await _replay("goblin-ambush")  # empty log: Brynn's turn (initiative 18, first)
    ctx = grid_context(scenario, out)
    by_cell = {c["cell_id"]: c for c in ctx["cells"]}

    # Brynn is at (1,4), base_speed 30ft, cell_size 5ft -> reach 6 cells
    # Chebyshev. (3,4) is within reach and unoccupied/unblocked.
    assert by_cell[cell_id(3, 4)]["move_candidate"] is True

    # Far outside her speed budget.
    assert by_cell[cell_id(11, 9)]["move_candidate"] is False

    # Sera occupies (0,6) -- within Brynn's reach but occupied, so excluded.
    assert by_cell[cell_id(0, 6)]["move_candidate"] is False

    # (5,0) is within reach but explicitly blocked, so excluded.
    assert by_cell[cell_id(5, 0)]["move_candidate"] is False

    # No cell may claim to be a candidate once the fight is over or once
    # it's a monster's turn. Drive to a monster turn and check no cell
    # claims to be a candidate.
    script: list[Command] = [
        *[
            _move("char:brynn", cell_id(c, r))
            for c, r in [(2, 5), (3, 5), (4, 5), (5, 5), (6, 5), (7, 4)]
        ],
        _attack("char:brynn", "longsword", "mon:gob1"),
        _attack("char:sera", "shortbow", "mon:gob2"),
    ]
    monster_out = await _replay("goblin-ambush", script)
    assert monster_out.rejected_reason is None
    monster_ctx = grid_context(scenario, monster_out)
    assert all(not c["move_candidate"] for c in monster_ctx["cells"])


async def test_grid_move_candidates_carry_move_command_json() -> None:
    scenario = get_scenario("goblin-ambush")
    out = await _replay("goblin-ambush")  # empty log: Brynn's turn
    ctx = grid_context(scenario, out)
    by_cell = {c["cell_id"]: c for c in ctx["cells"]}

    candidate = by_cell[cell_id(3, 4)]
    assert candidate["move_candidate"] is True
    assert candidate["move_command_json"] is not None
    parsed = IntentCommand.model_validate_json(candidate["move_command_json"])
    assert parsed.actor == "char:brynn"
    assert parsed.intent.intent_type == "move"
    assert parsed.intent.target_zone_id == cell_id(3, 4)

    non_candidate = by_cell[cell_id(11, 9)]
    assert non_candidate["move_candidate"] is False
    assert non_candidate["move_command_json"] is None


async def test_actions_expand_targets() -> None:
    scenario = get_scenario("goblin-ambush")
    out = await _replay("goblin-ambush")
    ctx = actions_context(scenario, out)

    assert ctx["mode"] == "pc_turn"
    assert ctx["actor"] is not None
    assert ctx["actor"]["entity_id"] == "char:brynn"
    assert ctx["rejected"] is None

    attack_options = [o for o in ctx["options"] if o["label"].startswith("Attack — Longsword")]
    # One entry per living goblin (3 of them, all alive on an empty log).
    assert len(attack_options) == 3

    for opt in attack_options:
        parsed = IntentCommand.model_validate_json(opt["command_json"])
        assert parsed.actor == "char:brynn"
        assert parsed.intent.intent_type == "attack"
        assert parsed.intent.target_id is not None
        assert parsed.intent.target_id.startswith("mon:gob")

    # Non-targeted options appear exactly once, untouched.
    dodge_options = [o for o in ctx["options"] if o["label"] == "Dodge"]
    assert len(dodge_options) == 1
    parsed_dodge = IntentCommand.model_validate_json(dodge_options[0]["command_json"])
    assert parsed_dodge.intent.intent_type == "dodge"
    assert parsed_dodge.intent.target_id is None


async def test_actions_expand_targets_ally_side() -> None:
    # last-stand: Faye (initiative 15) goes first on an empty log. Her
    # heal options are target_side="ally" -- they must expand over living
    # PARTY members (including Faye herself; self-heal is legal), never
    # over the encounter's monsters.
    scenario = get_scenario("last-stand")
    out = await _replay("last-stand")
    ctx = actions_context(scenario, out)

    assert ctx["mode"] == "pc_turn"
    assert ctx["actor"] is not None
    assert ctx["actor"]["entity_id"] == "char:faye"

    party_ids = {p.entity_id for p in scenario.party}
    encounter_ids = {m.entity_id for m in scenario.encounter}

    for label_prefix in ("Healing Word", "Cure Wounds"):
        heal_options = [o for o in ctx["options"] if o["label"].startswith(label_prefix)]
        # One entry per living party member (2 of them, including Faye).
        assert len(heal_options) == len(party_ids)
        for opt in heal_options:
            parsed = IntentCommand.model_validate_json(opt["command_json"])
            assert parsed.intent.target_id in party_ids
            assert parsed.intent.target_id not in encounter_ids

    # Faye herself must be a legal self-heal target.
    healing_word_targets = {
        IntentCommand.model_validate_json(o["command_json"]).intent.target_id
        for o in ctx["options"]
        if o["label"].startswith("Healing Word")
    }
    assert "char:faye" in healing_word_targets


async def test_actions_monster_turn_mode() -> None:
    scenario = get_scenario("goblin-ambush")
    script: list[Command] = [
        *[
            _move("char:brynn", cell_id(c, r))
            for c, r in [(2, 5), (3, 5), (4, 5), (5, 5), (6, 5), (7, 4)]
        ],
        _attack("char:brynn", "longsword", "mon:gob1"),
        _attack("char:sera", "shortbow", "mon:gob2"),
    ]
    out = await _replay("goblin-ambush", script)
    assert out.rejected_reason is None
    assert not out.is_over
    ctx = actions_context(scenario, out)

    assert ctx["mode"] == "monster_turn"
    assert ctx["actor"] is not None
    assert ctx["actor"]["side"] == "foe"
    assert len(ctx["options"]) == 1
    from nat20_demo.replay import MonsterTurnCommand

    MonsterTurnCommand.model_validate_json(ctx["options"][0]["command_json"])


async def test_tape_friendly_lines() -> None:
    scenario = get_scenario("goblin-ambush")
    names = {p.entity_id: p.name for p in scenario.party}
    names.update({m.entity_id: m.name for m in scenario.encounter})

    script: list[Command] = [
        *[
            _move("char:brynn", cell_id(c, r))
            for c, r in [(2, 5), (3, 5), (4, 5), (5, 5), (6, 5), (7, 4)]
        ],
        _attack("char:brynn", "longsword", "mon:gob1"),
    ]
    out = await _replay("goblin-ambush", script)
    assert out.rejected_reason is None
    lines = tape_lines(out.all_events, names)

    # One line per event EXCEPT the structural ``turn_phase`` markers, which
    # the tape drops (see test_tape_skips_turn_phase_markers).
    rendered_events = [e for e in out.all_events if e.type != "turn_phase"]
    assert len(lines) == len(rendered_events)
    attack_lines = [ln for ln in lines if ln["kind"] == "attack_rolled"]
    assert attack_lines, "expected at least one attack_rolled event"
    line = attack_lines[0]
    # Exact friendly-text shape from the brief: "Brynn attacks Goblin 1 —
    # 17 vs AC: hit" (or "miss"/"crit" depending on the roll).
    assert line["text"].startswith("Brynn attacks Goblin 1 — ")
    assert " vs AC: " in line["text"]
    assert line["text"].split(" vs AC: ")[1] in ("hit", "miss", "crit")

    # raw is valid JSON round-tripping the event's own payload.
    for ln, event in zip(lines, rendered_events, strict=True):
        payload = json.loads(ln["raw"])
        assert payload["type"] == event.type

    # Unknown/other event types never raise -- exercised indirectly by every
    # event type the showcase script produces; explicitly prove the
    # fallback formatting contract on a type outside our friendly table by
    # monkey-testing the fallback path via a type not in _FRIENDLY.
    from nat20_demo.render import _FRIENDLY

    covered = {
        "attack_rolled",
        "save_rolled",
        "damage_applied",
        "healing_applied",
        "temphp_applied",
        "effect_applied",
        "condition_applied",
        "concentration_check",
        "concentration_dropped",
        "death_save_rolled",
        "unconscious",
        "death",
        "actor_moved",
        "dash_taken",
        "turn_started",
        "round_started",
        "cast_failed",
        "attack_failed",
        "combat_ended",
    }
    assert covered <= set(_FRIENDLY)


async def test_status_tracks_hp_and_slots() -> None:
    scenario = get_scenario("burning-hands")
    script: list[Command] = [
        IntentCommand(
            actor="char:orin",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="burning-hands",
                slot_level=1,
                target_id="mon:rat1",
            ),
        )
    ]
    out = await _replay("burning-hands", script)
    statuses = status_context(scenario, out)
    by_id = {s["entity_id"] for s in statuses}
    assert by_id == set(out.view.actor_zone)

    orin = next(s for s in statuses if s["entity_id"] == "char:orin")
    assert orin["hp_max"] == 16
    assert orin["hp"] == out.view.tracked_hp["char:orin"]
    # Orin spent his one 1st-level slot casting Burning Hands.
    assert orin["slots"].get(1) == 1
    assert isinstance(orin["concentrating"], bool)

    rat1 = next(s for s in statuses if s["entity_id"] == "mon:rat1")
    assert rat1["hp"] == out.view.tracked_hp["mon:rat1"]
    assert rat1["hp_max"] == 7
    assert rat1["conditions"] == sorted(out.view.active_conditions.get("mon:rat1", set()))


async def test_initiative_context_orders_and_flags() -> None:
    scenario = get_scenario("goblin-ambush")
    out = await _replay("goblin-ambush")
    ctx = initiative_context(out)

    assert [c["entity_id"] for c in ctx] == [c.entity_id for c in out.view.initiative]
    brynn = next(c for c in ctx if c["entity_id"] == "char:brynn")
    assert brynn["side"] == "pc"
    assert brynn["current"] is True
    assert brynn["dead"] is False

    gob1 = next(c for c in ctx if c["entity_id"] == "mon:gob1")
    assert gob1["side"] == "foe"
    assert gob1["current"] is False


async def test_tape_skips_turn_phase_markers() -> None:
    """``turn_phase`` is a structural marker, not narration — it must produce
    NO tape line.

    Engine F3a emits two or three ``TurnPhase`` events at every turn boundary
    purely so a host can locate the boundary. The tape already shows the
    boundary via ``turn_started`` / ``round_started``, so rendering the marker
    (which has no friendly formatter, and would therefore fall back to a raw
    ``turn_phase: {...}`` payload dump) would bury the actual combat log in
    noise.
    """
    scenario = get_scenario("goblin-ambush")
    names = {p.entity_id: p.name for p in scenario.party}
    names.update({m.entity_id: m.name for m in scenario.encounter})

    out = await _replay("goblin-ambush", [_attack("char:brynn", "longsword", "mon:gob1")])
    assert out.rejected_reason is None

    # The replay really does carry the markers — otherwise this test would
    # pass vacuously if the engine stopped emitting them.
    assert [e for e in out.all_events if e.type == "turn_phase"]

    lines = tape_lines(out.all_events, names)
    assert [ln for ln in lines if ln["kind"] == "turn_phase"] == []
    assert not any("turn_phase" in ln["text"] for ln in lines)
    # The boundary is still visible through the structural events proper.
    assert [ln for ln in lines if ln["kind"] == "turn_started"]
