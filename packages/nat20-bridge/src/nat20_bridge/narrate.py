"""Render a sequence of ``dnd5e_engine`` ``CombatEvent``s as human-readable text.

One line per event, joined by ``\\n``. High-traffic event types get a
per-type formatter tuned for readability; every other event type — including
any future addition to the ``CombatEvent`` union — falls through to a
generic ``[type] k=v ...`` dump so this function never raises regardless of
which event it is handed. Purely structural markers (``_SKIPPED_EVENT_TYPES``)
contribute no line at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from dnd5e_engine.events import CombatEvent

# Dispatch table keyed by the event's discriminator (`type`). Formatters are
# typed loosely (`Any`) on purpose: each closes over one concrete event
# subclass's fields, but the shared registry has to hold them uniformly.
_Formatter = Callable[[Any, dict[str, str]], str]

_FORMATTERS: dict[str, _Formatter] = {}


def _register(event_type: str) -> Callable[[_Formatter], _Formatter]:
    def decorator(fn: _Formatter) -> _Formatter:
        _FORMATTERS[event_type] = fn
        return fn

    return decorator


def _who(entity_id: str, names: dict[str, str]) -> str:
    return names.get(entity_id, entity_id)


@_register("round_started")
def _fmt_round_started(e: Any, names: dict[str, str]) -> str:
    return f"-- Round {e.round_number} --"


@_register("round_ended")
def _fmt_round_ended(e: Any, names: dict[str, str]) -> str:
    return f"-- End of Round {e.round_number} --"


@_register("turn_started")
def _fmt_turn_started(e: Any, names: dict[str, str]) -> str:
    return f"{_who(e.actor_id, names)}'s turn begins."


@_register("turn_ended")
def _fmt_turn_ended(e: Any, names: dict[str, str]) -> str:
    return f"{_who(e.actor_id, names)}'s turn ends."


@_register("intent_submitted")
def _fmt_intent_submitted(e: Any, names: dict[str, str]) -> str:
    who = _who(e.actor_id, names)
    return f"{who} attempts {e.intent_type}."


@_register("attack_rolled")
def _fmt_attack_rolled(e: Any, names: dict[str, str]) -> str:
    attacker = _who(e.attacker_id, names)
    target = _who(e.target_id, names)
    if e.is_crit:
        outcome = "CRITS"
    elif e.is_hit:
        outcome = "hits"
    else:
        outcome = "misses"
    return f"{attacker} attacks {target}: rolls {e.roll_total} — {outcome}."


@_register("save_rolled")
def _fmt_save_rolled(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    outcome = "succeeds" if e.succeeded else "fails"
    return f"{who} rolls a {e.ability} save: {e.roll_total} vs DC {e.dc} — {outcome}."


@_register("check_rolled")
def _fmt_check_rolled(e: Any, names: dict[str, str]) -> str:
    who = _who(e.actor_id, names)
    skill = f" ({e.skill})" if e.skill else ""
    if e.succeeded is None:
        outcome = f"rolls {e.roll_total}"
    else:
        outcome = f"rolls {e.roll_total} — {'succeeds' if e.succeeded else 'fails'}"
    return f"{who} makes a {e.ability}{skill} check: {outcome}."


@_register("damage_applied")
def _fmt_damage_applied(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    overkill = " (overkill)" if e.is_overkill else ""
    return f"{who} takes {e.amount} {e.damage_type} damage{overkill}."


@_register("healing_applied")
def _fmt_healing_applied(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    return f"{who} heals {e.amount} HP."


@_register("condition_applied")
def _fmt_condition_applied(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    return f"{who} is now {e.condition}."


@_register("condition_removed")
def _fmt_condition_removed(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    return f"{who} is no longer {e.condition}."


@_register("cast_failed")
def _fmt_cast_failed(e: Any, names: dict[str, str]) -> str:
    who = _who(e.actor_id, names)
    return f"{who} fails to cast {e.spell_id} ({e.reason})."


@_register("attack_failed")
def _fmt_attack_failed(e: Any, names: dict[str, str]) -> str:
    who = _who(e.actor_id, names)
    return f"{who}'s attack fails ({e.reason})."


@_register("unconscious")
def _fmt_unconscious(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    return f"{who} falls unconscious."


@_register("death")
def _fmt_death(e: Any, names: dict[str, str]) -> str:
    who = _who(e.target_id, names)
    return f"{who} dies."


@_register("combat_ended")
def _fmt_combat_ended(e: Any, names: dict[str, str]) -> str:
    return f"-- Combat ends ({e.reason}) --"


def _fallback(event: Any, names: dict[str, str]) -> str:
    dump = " ".join(f"{k}={v}" for k, v in event.model_dump().items() if k != "type")
    return f"[{event.type}] {dump}"


def _render_one(event: Any, names: dict[str, str]) -> str:
    formatter = _FORMATTERS.get(event.type)
    if formatter is None:
        return _fallback(event, names)
    try:
        return formatter(event, names)
    except Exception:  # noqa: BLE001 - never let a formatter bug crash narration
        return _fallback(event, names)


# Structural markers with no narrative content — dropped rather than rendered.
# ``turn_phase`` (engine F3a) fires 2-3 times per turn boundary purely to tell a
# host WHERE the boundary is; the narration already marks it with the
# ``-- Round N --`` / ``It is X's turn.`` lines, and this text is fed to an LLM,
# so a raw ``[turn_phase] actor_id=... phase=...`` dump would be pure token noise.
# ``concentration_check`` is the transitional twin of the ``SaveRolled`` the
# engine still emits for the same roll; narrating both would describe one
# concentration save twice. Skip the newer shape and keep the ``save_rolled``
# line -- remove when the SaveRolled twin is dropped in 0.7.
_SKIPPED_EVENT_TYPES: frozenset[str] = frozenset({"turn_phase", "concentration_check"})


def narrate(events: Sequence[CombatEvent], names: dict[str, str]) -> str:
    """Render ``events`` as one narration line per event, joined by newlines.

    ``names`` maps entity id -> display name; ids missing from the map are
    rendered as-is. Event types without a dedicated formatter — including any
    type added to the ``CombatEvent`` union after this module was written —
    render via a generic ``[type] key=value ...`` fallback, except the purely
    structural types in ``_SKIPPED_EVENT_TYPES``, which contribute no line at
    all. This function never raises.
    """
    return "\n".join(
        _render_one(event, names) for event in events if event.type not in _SKIPPED_EVENT_TYPES
    )
