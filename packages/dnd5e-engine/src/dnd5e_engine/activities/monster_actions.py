"""Typed monster-action selection + multiattack fan-out from ``Monster.actions``.

The lib carries no ``monster_actions_index``: a monster's repertoire lives on
``Monster.actions``/``legendary_actions``/``lair_actions``/``special_abilities``
as typed ``MonsterAction`` instances. This module replaces ``monster_ai``'s
index-based selection with typed selection and resolves multiattack by parsing
its description.

Multiattack carries only a no-op ``UtilityActivity``; its sub-attacks are named
solely in ``MonsterAction.description`` as Foundry ``[[/item .<id>]]`` enricher
tokens plus a leading count word ("two"/"three"). The Foundry id is NOT a typed
field on ``MonsterAction``, so it cannot be joined directly. Resolution:

1. Collect sibling actions whose activities contain an ``AttackActivity`` or
   ``SaveActivity`` (excluding the multiattack itself).
2. Parse the leading count word from the description (default 1, logged).
3. If the description's ``[[/item]]`` tokens carry rendered labels that map 1:1
   onto sibling names (case-insensitive), resolve those in order, each repeated
   ``count`` times ("makes TWO claw attacks" → two claws) — the *precise* path.
4. Otherwise fall back to repeating the first attack sibling's first attack/save
   activity ``count`` times and log ``multiattack_join_unresolved`` at WARNING
   (the loss is visible — never a silent normalization).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from dnd5e_srd_data.schema.common import AttackActivity, SaveActivity

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.common import Activity
    from dnd5e_srd_data.schema.monster import Monster, MonsterAction

_LOGGER = logging.getLogger(__name__)

_MULTIATTACK_SLUG = "multiattack"

# Leading count word in a multiattack description ("makes two attacks…").
_NUMBER_WORD: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

# Foundry item enricher: ``[[/item .<id>]]`` optionally followed by ``{label}``.
# The id alone is not joinable to a typed MonsterAction; only a rendered label is.
_ITEM_TOKEN_RE = re.compile(r"\[\[/item\s+\.[A-Za-z0-9]+\]\](?:\{([^}]*)\})?")


def _activity_is_offensive(activity: Activity) -> bool:
    return isinstance(activity, (AttackActivity, SaveActivity))


def _action_has_offense(action: MonsterAction) -> bool:
    return any(_activity_is_offensive(a) for a in action.activities)


def _attack_siblings(monster: Monster, exclude: MonsterAction) -> list[MonsterAction]:
    """Actions with an attack/save activity, excluding the given action."""
    return [a for a in monster.actions if a.slug != exclude.slug and _action_has_offense(a)]


def _first_offensive_activity(action: MonsterAction) -> Activity | None:
    for activity in action.activities:
        if _activity_is_offensive(activity):
            return activity
    return None


def _parse_multiattack_count(description: str) -> int:
    """Parse the leading count word ("makes two attacks…" → 2).

    Defaults to 1 (logged) when no count word parses, so an unparseable
    multiattack degrades to a single attack rather than guessing arity.
    """
    for word, count in _NUMBER_WORD.items():
        if re.search(rf"\bmakes? {word}\b", description, re.IGNORECASE):
            return count
    _LOGGER.warning("multiattack_count_unparsed default=1 description=%r", description)
    return 1


def _parse_item_labels(description: str) -> list[str]:
    """Rendered ``[[/item .<id>]]{label}`` labels, in order; empty if none carry one."""
    return [m.group(1) for m in _ITEM_TOKEN_RE.finditer(description) if m.group(1)]


def select_typed_monster_action(monster: Monster) -> MonsterAction | None:
    """Pick which action this monster should use this turn.

    Mirrors ``monster_ai.select_monster_action`` mechanical priority:
    multiattack first (the signature "use your full action budget" choice),
    else the first action whose activities contain an attack or save.
    Behaviour/flee gating stays with the caller (it owns the live Combatant).
    """
    for action in monster.actions:
        if action.slug == _MULTIATTACK_SLUG:
            return action
    for action in monster.actions:
        if _action_has_offense(action):
            return action
    return None


def expand_action_to_activities(monster: Monster, action: MonsterAction) -> list[Activity]:
    """Expand a chosen action into the activities to resolve this turn.

    Non-multiattack actions resolve their own activities, but Foundry's 2024
    weapon/monster actions ship the SAME attack as multiple ``AttackActivity``
    variants (e.g. a base attack + an "Attack with Advantage" alternative). These
    are alternative modes the actor chooses between, not sequential attacks —
    resolving all of them would make the monster attack twice. Collapse them to
    the first ``AttackActivity`` while preserving every non-attack activity
    (riders such as on-hit saves). Multiattack fans out per the rule at module
    top.
    """
    if action.slug != _MULTIATTACK_SLUG:
        resolved: list[Activity] = []
        seen_attack = False
        for activity in action.activities:
            if isinstance(activity, AttackActivity):
                if seen_attack:
                    continue  # alternative attack-mode variant — skip duplicates
                seen_attack = True
            resolved.append(activity)
        return resolved

    siblings = _attack_siblings(monster, exclude=action)
    if not siblings:
        _LOGGER.warning(
            "multiattack_join_unresolved monster=%s reason=no_attack_sibling description=%r",
            monster.slug,
            action.description,
        )
        return []

    count = _parse_multiattack_count(action.description)
    labels = _parse_item_labels(action.description)

    # Precise path: every rendered label maps 1:1 onto a sibling by case-
    # insensitive name match. Only reachable when the description carries
    # labels (Foundry id-only tokens cannot identify a typed action).
    if labels:
        by_name = {s.name.casefold(): s for s in siblings}
        matched = [by_name.get(label.casefold()) for label in labels]
        if all(m is not None for m in matched):
            matched_resolved: list[Activity] = []
            for sibling in matched:
                assert sibling is not None  # narrowed by the all(...) guard
                sibling_activity = _first_offensive_activity(sibling)
                if sibling_activity is not None:
                    # The prose count ("makes TWO claw attacks") is the per-
                    # sibling repetition, mirroring the fallback's ``* count``.
                    # Emitting each matched sibling once dropped the count.
                    matched_resolved.extend([sibling_activity] * count)
            if matched_resolved:
                return matched_resolved

    # Fallback: repeat the first attack sibling's first offensive activity.
    # Correctness-preserving for single-attack-type multiattacks (owlbear → Rend)
    # and "any combination" count cases (goblin-boss → 2 attacks).
    first_activity = _first_offensive_activity(siblings[0])
    if first_activity is None:
        _LOGGER.warning(
            "multiattack_join_unresolved monster=%s reason=no_offensive_activity description=%r",
            monster.slug,
            action.description,
        )
        return []
    _LOGGER.warning(
        "multiattack_join_unresolved monster=%s count=%d sibling=%s description=%r",
        monster.slug,
        count,
        siblings[0].slug,
        action.description,
    )
    return [first_activity] * count
