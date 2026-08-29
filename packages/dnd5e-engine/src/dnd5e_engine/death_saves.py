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
from typing import Any

from dnd5e_engine.activities.d20 import AdvantageSources, D20Result, roll_d20_test
from dnd5e_engine.events import (
    CombatEvent,
    Death,
    DeathSaveRolled,
    DeathSaveStarted,
    Stabilized,
)
from dnd5e_engine.rules.conditions import d20_test_penalty
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition


@dataclass
class DeathSaveState:
    """Mutable state machine for D&D 5e death saving throws.

    Designed for host persistence via to_dict / from_dict.
    """

    successes: int = 0
    failures: int = 0
    is_stable: bool = False

    # ------------------------------------------------------------------
    # Core state transitions
    # ------------------------------------------------------------------

    def apply_save(self, success: bool, is_critical: bool) -> str:
        """Apply a death saving throw result.

        Returns one of: "critical_success" | "stabilized" | "dead" | "ongoing".

        Rules:
        - Nat 20 (success=True, is_critical=True): regain 1 HP -> "critical_success"
        - Nat 1  (success=False, is_critical=True): 2 failures
        - Normal success: 1 success; 3 successes -> "stabilized"
        - Normal failure: 1 failure; 3 failures  -> "dead"
        """
        # Nat 20 takes priority — regain 1 HP, no counter update needed
        if success and is_critical:
            return "critical_success"

        if success:
            self.successes += 1
        elif is_critical:
            # Nat 1 counts as 2 failures
            self.failures += 2
        else:
            self.failures += 1

        return self._check_outcome()

    def apply_damage_while_unconscious(self, is_critical: bool) -> str:
        """Apply death save failures from damage while unconscious.

        SRD 5.2 "Damage at 0 Hit Points": taking any damage while at 0 HP is
        one Death Saving Throw failure; a Critical Hit is two. (The parameter
        was historically named ``is_melee_within_5ft`` — melee within 5 ft of
        an Unconscious target is an automatic Critical Hit, so the meaning is
        unchanged; the positional shape is preserved.)

        Returns "dead" if 3+ failures reached, else "ongoing".
        """
        self.failures += 2 if is_critical else 1
        return self._check_outcome()

    def reset(self) -> None:
        """Reset all counters (called when character regains HP via nat 20)."""
        self.successes = 0
        self.failures = 0
        self.is_stable = False

    # ------------------------------------------------------------------
    # Serialization (plain dicts for host persistence)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "failures": self.failures,
            "is_stable": self.is_stable,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeathSaveState:
        return cls(
            successes=d.get("successes", 0),
            failures=d.get("failures", 0),
            is_stable=d.get("is_stable", False),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_outcome(self) -> str:
        if self.failures >= 3:
            return "dead"
        if self.successes >= 3:
            self.is_stable = True
            return "stabilized"
        return "ongoing"


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


def _roll_d20(rng: random.Random, modifier: int = 0) -> D20Result:
    """The death save's D20 Test through the shared primitive (F2c).

    SRD §Dying — a death saving throw draws one d20 with no advantage source
    the engine models today, so ``activities/d20.py::roll_d20_test`` is called
    with an empty ``AdvantageSources``: exactly one ``rng.randint(1, 20)``
    draw, identical to the pre-F2c stream. ``modifier`` is the SRD 5.2
    Exhaustion penalty (a death save is a saving throw, hence a D20 Test); a
    flat modifier never adds a draw, so an unexhausted PC's stream is unmoved.
    """
    return roll_d20_test(rng, modifier, AdvantageSources())


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

    # The Exhaustion penalty reduces the TOTAL; the nat-1 / nat-20 special
    # outcomes still read the KEPT die (SRD 5.2 Exhaustion + §Dying).
    roll = _roll_d20(rng, d20_test_penalty(combatant.conditions))
    natural = roll.kept
    is_critical = natural in (1, 20)
    success = natural == 20 or (natural != 1 and roll.total >= 10)

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
            roll_total=roll.total,
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
        # SRD 5.2 Unconscious: "When this condition ends, you remain Prone."
        kept = [c for c in combatant.conditions if c.condition != "unconscious"]
        if not any(c.condition == "prone" for c in kept):
            kept.append(
                ActiveCondition(
                    condition="prone",
                    source_entity_id="implied:revive",
                    scope="combat",
                )
            )
        updates["conditions"] = kept
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
    "DeathSaveState",
    "reset_death_saves",
    "roll_death_save",
]
