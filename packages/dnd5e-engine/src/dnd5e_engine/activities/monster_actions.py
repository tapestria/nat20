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


def _activity_range_ft(activity: Activity, melee_reach_ft: int) -> int | None:
    """The effective reach, in feet, of an attack/save activity for sibling choice.

    Mirrors ``orchestrator._monster_attack_range_ft``'s per-activity reading so
    the fallback selection and the movement gate agree on each sibling's range:

      * an :class:`AttackActivity` with an explicit ``units == "ft"`` positive
        value uses it verbatim (the Scout longbow's ``"150"``); a Foundry melee
        attack (``units == "self"`` / empty value) falls back to ``melee_reach_ft``;
      * a ranged single-target :class:`SaveActivity` (``units == "ft"``, positive
        value) uses that value; a self/template save carries no positional reach.

    Returns ``None`` when no finite reach is resolvable — the caller treats an
    unknown-range sibling as unable to disqualify itself (never over-filters).
    """
    rng = activity.range
    if rng.units == "ft" and rng.value:
        try:
            parsed = int(rng.value)
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed
    if isinstance(activity, AttackActivity):
        # units == "self" / empty ft value ⇒ melee reach (mirrors the gate).
        return melee_reach_ft if melee_reach_ft > 0 else None
    return None


def _select_fallback_sibling(
    siblings: list[MonsterAction],
    target_distance_ft: int | None,
    behavior_profile: str | None,
    melee_reach_ft: int,
) -> MonsterAction:
    """Pick which attack sibling the labelless-multiattack fallback repeats.

    Default (``target_distance_ft is None``): the first sibling in
    ``Monster.actions`` order — the historical dict-order behaviour, preserved
    for callers that pass no live distance.

    Range/profile-aware (C10-S02): when the live distance to the chosen target
    is known, prefer a sibling whose OWN range already covers it over one that
    does not (the Scout at 100 ft: its 150 ft longbow covers, its 5 ft shortsword
    does not — so fire the longbow rather than the first-listed melee weapon).
    When several in-range siblings tie and the monster is ``RANGED``, break toward
    the longest-reach (ranged) sibling; otherwise keep list order. When NO sibling
    covers the distance, fall back to the first — the movement gate then closes
    the gap exactly as before.
    """
    if not siblings:  # pragma: no cover — callers guard for a non-empty list
        raise ValueError("_select_fallback_sibling requires at least one sibling")
    if target_distance_ft is None:
        return siblings[0]

    def _reach(sibling: MonsterAction) -> int | None:
        activity = _first_offensive_activity(sibling)
        return _activity_range_ft(activity, melee_reach_ft) if activity is not None else None

    def _covers(sibling: MonsterAction) -> bool:
        reach = _reach(sibling)
        # An unresolvable reach can't disqualify a sibling (never over-filter).
        return reach is None or reach >= target_distance_ft

    in_range = [s for s in siblings if _covers(s)]
    if not in_range:
        return siblings[0]
    if len(in_range) == 1:
        return in_range[0]
    if behavior_profile == "RANGED":
        # Tiebreak toward the ranged sibling — the one with the longest reach.
        return max(in_range, key=lambda s: _reach(s) or 0)
    return in_range[0]


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


def expand_action_to_activities(
    monster: Monster,
    action: MonsterAction,
    *,
    target_distance_ft: int | None = None,
    behavior_profile: str | None = None,
    melee_reach_ft: int = 5,
) -> list[Activity]:
    """Expand a chosen action into the activities to resolve this turn.

    Non-multiattack actions resolve their own activities, but Foundry's 2024
    weapon/monster actions ship the SAME attack as multiple ``AttackActivity``
    variants (e.g. a base attack + an "Attack with Advantage" alternative). These
    are alternative modes the actor chooses between, not sequential attacks —
    resolving all of them would make the monster attack twice. Collapse them to
    the first ``AttackActivity`` while preserving every non-attack activity
    (riders such as on-hit saves). Multiattack fans out per the rule at module
    top.

    ``target_distance_ft`` / ``behavior_profile`` / ``melee_reach_ft`` steer the
    labelless-multiattack fallback's sibling choice (C10-S02): when the live
    distance to the chosen target is supplied, the fallback prefers a sibling
    whose own range covers it (``RANGED`` tie-breaks toward the ranged sibling).
    Omitting them preserves the historical first-in-list-order fallback.
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

    # Fallback: repeat the chosen attack sibling's first offensive activity.
    # Correctness-preserving for single-attack-type multiattacks (owlbear → Rend)
    # and "any combination" count cases (goblin-boss → 2 attacks); range/profile-
    # aware for mixed melee+ranged repertoires (scout → longbow at 100 ft).
    chosen_sibling = _select_fallback_sibling(
        siblings, target_distance_ft, behavior_profile, melee_reach_ft
    )
    first_activity = _first_offensive_activity(chosen_sibling)
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
        chosen_sibling.slug,
        action.description,
    )
    return [first_activity] * count
