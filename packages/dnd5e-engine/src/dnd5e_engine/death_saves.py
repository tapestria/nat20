"""Death-save loop helper for the combat orchestrator.

SRD 5.1 §Dying — when a PC drops to 0 HP, at the start of each of their turns
they roll a d20 (no modifiers):
- 10+ → 1 success; <10 → 1 failure
- nat-20 → regain 1 HP (conscious), counters reset
- nat-1  → 2 failures
- 3 successes → stable (no further rolls)
- 3 failures → dead

This module is pure and orchestrator-callable: it takes a ``Combatant`` plus an
injected ``random.Random`` instance and returns the events to emit and the
updated combatant state. Orchestrator wiring (queue push, broadcast, turn skip)
is the caller's responsibility.

Reference: legacy ``session/combat.py:handle_player_death_save``. The state
machine on ``rules/combat_helpers.DeathSaveState`` is the canonical state shape;
this module is the event-producing wrapper above it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from dnd5e_engine.events import (
    CombatEvent,
    Death,
    DeathSaveRolled,
    DeathSaveStarted,
    Stabilized,
)
from dnd5e_engine.rules.combat_helpers import DeathSaveState
from dnd5e_engine.types.combat import Combatant

# Outcome literal returned alongside events/state for the caller to drive
# turn skip / combat-end / consciousness restore.
DeathSaveOutcome = str  # "ongoing" | "stabilized" | "dead" | "critical_success"


@dataclass(frozen=True)
class DeathSaveResult:
    """Output of a single death-save roll.

    - ``events``: ordered ``CombatEvent`` list ready to push onto the
      orchestrator queue. ``DeathSaveStarted`` is emitted only on the first
      roll of a dying spell (prior state had no rolls recorded).
    - ``combatant``: updated copy of the input — ``death_saves`` dict refreshed
      and, on nat-20, ``hp_current=1`` plus ``is_alive=True`` and the
      ``unconscious`` condition cleared.
    - ``outcome``: SRD outcome literal, matching ``DeathSaveState.apply_save``.
    """

    events: list[CombatEvent]
    combatant: Combatant
    outcome: DeathSaveOutcome


def _roll_d20(rng: random.Random) -> int:
    return rng.randint(1, 20)


def roll_death_save(combatant: Combatant, rng: random.Random) -> DeathSaveResult:
    """Roll a single death save for ``combatant`` and return the resulting
    events + updated combatant state.

    Caller-owned preconditions:
    - ``combatant`` is a Character at 0 HP and not yet stable / not yet dead.
      This helper does not re-check; producing a roll for a non-dying PC is a
      caller bug.
    """
    prior_state = (
        DeathSaveState.from_dict(combatant.death_saves)
        if combatant.death_saves
        else DeathSaveState()
    )
    is_first_roll = (
        prior_state.successes == 0 and prior_state.failures == 0 and not prior_state.is_stable
    )

    natural = _roll_d20(rng)
    is_critical = natural in (1, 20)
    success = natural >= 10  # nat-20 satisfies this; nat-1 does not

    # Mutate the state machine (in-place on a fresh copy via from_dict above).
    outcome = prior_state.apply_save(success, is_critical)

    events: list[CombatEvent] = []
    if is_first_roll:
        events.append(DeathSaveStarted(target_id=combatant.entity_id))

    # SRD outcome → event roll-outcome literal
    if success and is_critical:
        roll_outcome: str = "crit_success"
    elif not success and is_critical:
        roll_outcome = "crit_failure"
    elif success:
        roll_outcome = "success"
    else:
        roll_outcome = "failure"

    events.append(
        DeathSaveRolled(
            target_id=combatant.entity_id,
            roll_total=natural,
            outcome=roll_outcome,
            running_successes=prior_state.successes,
            running_failures=prior_state.failures,
        )
    )

    # Build the updated combatant.
    updates: dict[str, object] = {}
    if outcome == "critical_success":
        # Nat-20 — conscious with HP=1. Reset death-save counters; clear
        # the ``unconscious`` ActiveCondition if present so the PC can act
        # next turn.
        prior_state.reset()
        updates["death_saves"] = prior_state.to_dict()
        updates["hp_current"] = 1
        updates["is_alive"] = True
        updates["conditions"] = [c for c in combatant.conditions if c.condition != "unconscious"]
    else:
        updates["death_saves"] = prior_state.to_dict()

    updated = combatant.model_copy(update=updates)

    if outcome == "stabilized":
        events.append(Stabilized(target_id=combatant.entity_id))
    elif outcome == "dead":
        events.append(Death(target_id=combatant.entity_id, reason="death_saves"))
        # SRD: dead combatant is no longer alive. We surface this via the
        # combatant copy so the orchestrator can act on it without a second
        # round trip.
        updated = updated.model_copy(update={"is_alive": False})

    return DeathSaveResult(events=events, combatant=updated, outcome=outcome)


def reset_death_saves(combatant: Combatant) -> Combatant:
    """Return a copy of ``combatant`` with death-save counters cleared.

    Call this when a dying PC is healed above 0 HP — SRD requires the
    accumulated successes / failures to be wiped so the next dying spell
    starts fresh.
    """
    return combatant.model_copy(update={"death_saves": {}})


__all__ = [
    "DeathSaveOutcome",
    "DeathSaveResult",
    "reset_death_saves",
    "roll_death_save",
]
