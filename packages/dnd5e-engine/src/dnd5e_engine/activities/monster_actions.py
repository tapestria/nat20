"""Typed monster-action selection + multiattack fan-out from ``Monster.actions``.

A monster's repertoire lives on ``Monster.actions`` as typed ``MonsterAction``
instances. Only ``actions`` drives the turn today — ``legendary_actions``,
``lair_actions`` and ``special_abilities`` are carried by the schema but have no
action economy in the engine yet (see ``BACKLOG.md``).

Multiattack is the hard case. It carries only a no-op ``UtilityActivity``; the
sub-attacks it fans out into are named *in prose*, via Foundry ``[[/item …]]``
enricher tokens, in two shapes the corpus mixes freely::

    makes three [[/item Rend]] attacks              # name form  — joinable
    makes two [[/item .mmClaw000000]]{Claw} attacks # id + label — joinable
    makes two [[/item .mmBite000000]] attacks       # bare id    — NOT joinable

The bare Foundry id is not a field on ``MonsterAction``, so it cannot be joined
to a typed sibling. Resolution, in order:

1. Collect sibling actions carrying an ``AttackActivity`` or ``SaveActivity``
   (excluding the multiattack itself).
2. Parse the *first sentence* of the description into ``(name, count)`` pairs,
   reading the count immediately preceding each token ("makes two Claw attacks
   and uses Roar" → ``[(Claw, 2), (Roar, 1)]``). Later sentences are riders
   ("It can replace one attack with …") and are deliberately ignored — they
   describe a substitution the engine does not model, not an extra attack.
3. If every parsed name joins to a sibling, emit each sibling's first offensive
   activity, repeated its own count — the *precise* path.
4. Otherwise repeat one chosen sibling ``count`` times and log
   ``multiattack_join_unresolved`` at WARNING (the loss is visible — never a
   silent normalization). This is correctness-preserving for the homogeneous
   ("three Rend attacks") and free-choice ("two attacks, using Slam or Force
   Bolt in any combination") shapes, and lossy only for a heterogeneous
   multiattack whose tokens are bare ids.
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

# Count words in a multiattack description ("makes two attacks…"). The corpus
# also writes counts as digits ("makes 2 Pincer attacks"), so both parse.
_NUMBER_WORD: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

# Foundry item enricher, in the two joinable shapes the corpus ships:
#   ``[[/item .<id>]]{Label}``  -> group "label"
#   ``[[/item Name]]``          -> group "name"
# A bare ``[[/item .<id>]]`` with no label matches but yields neither, which is
# what makes it unjoinable — the id is not a field on ``MonsterAction``.
_ITEM_TOKEN_RE = re.compile(
    r"\[\[/item\s+(?:\.(?P<id>[A-Za-z0-9.]+)\]\](?:\{(?P<label>[^}]*)\})?"
    r"|(?P<name>[^\].{}][^\]]*)\]\])"
)

# A count immediately preceding an item token: "makes two [[/item Claw]]",
# "uses [[/item Reel]]", "makes 2 [[/item Pincer]]". Captured lazily so the
# scan stays anchored to the token that follows it.
_COUNT_BEFORE_TOKEN_RE = re.compile(
    r"(?:\b(?P<word>" + "|".join(_NUMBER_WORD) + r")\b|\b(?P<digits>\d{1,2})\b)"
    r"(?:\s+\w+){0,3}?\s*$",
    re.IGNORECASE,
)


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


# Foundry's monster-manual action ids are mnemonic: ``mmRottingFist000`` is
# "Rotting Fist", ``mmBite0000000000`` is "Bite". The id is zero-padded to a
# fixed width and camel-cased. Ids that do NOT follow this convention (a random
# document key like ``w3cX0piuU875Hc2M``) yield nothing and stay unjoinable.
_FOUNDRY_MM_ID_RE = re.compile(r"^mm([A-Za-z][A-Za-z]*?)0*$")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")

# Sentence break. The corpus is not consistently spaced ("attacks.It can
# replace…"), so a period followed by whitespace OR a capital letter ends it.
_SENTENCE_BREAK_RE = re.compile(r"\.(?:\s+|(?=[A-Z]))")


def _multiattack_clause(description: str) -> str:
    """The first sentence — the multiattack proper, minus any rider clause.

    Later sentences describe substitutions the engine does not model ("It can
    replace one attack with a use of Spellcasting"). Counting their tokens as
    extra attacks would inflate every dragon's action economy, so they are cut.
    """
    return _SENTENCE_BREAK_RE.split(description, maxsplit=1)[0]


def _name_from_foundry_id(foundry_id: str) -> str | None:
    """Recover an action name from a mnemonic Foundry id, or ``None``.

    ``mmDreadfulGlare0`` -> ``"Dreadful Glare"``. Purely a *hint*: the caller
    only uses it when the recovered name joins to exactly one typed sibling, so
    a bad guess degrades to the existing fallback rather than mis-resolving.
    """
    match = _FOUNDRY_MM_ID_RE.match(foundry_id)
    if match is None:
        return None
    words = _CAMEL_BOUNDARY_RE.split(match.group(1))
    return " ".join(words) if words else None


def _parse_multiattack_count(description: str) -> int:
    """Parse the leading count ("makes two attacks…" → 2, "makes 2 …" → 2).

    Defaults to 1 (logged) when nothing parses, so an unparseable multiattack
    degrades to a single attack rather than guessing arity.
    """
    for word, count in _NUMBER_WORD.items():
        if re.search(rf"\bmakes? {word}\b", description, re.IGNORECASE):
            return count
    digits = re.search(r"\bmakes? (\d{1,2})\b", description, re.IGNORECASE)
    if digits:
        return max(1, int(digits.group(1)))
    _LOGGER.warning("multiattack_count_unparsed default=1 description=%r", description)
    return 1


def _parse_item_counts(description: str) -> list[tuple[str, int]] | None:
    """Parse the multiattack clause into ordered ``(sibling name, count)`` pairs.

    Returns ``None`` when the clause cannot be read precisely — any token that
    is a bare Foundry id (unjoinable), or a free-choice clause ("Slam or Force
    Bolt in any combination", "three Radiant Sword attacks or uses Holy Burst
    twice") where the prose describes alternatives rather than a fixed sequence.
    The caller falls back to the repeat-one-sibling path in both cases.
    """
    clause = _multiattack_clause(description)
    matches = list(_ITEM_TOKEN_RE.finditer(clause))
    if not matches:
        return None
    if re.search(r"\bor\b", clause, re.IGNORECASE):
        return None  # alternatives, not a sequence — the fallback handles it

    pairs: list[tuple[str, int]] = []
    for match in matches:
        name = match.group("label") or match.group("name")
        if not name or not name.strip():
            # Bare id — recoverable only when Foundry's mnemonic id convention
            # yields a name; otherwise the token cannot identify a sibling.
            name = _name_from_foundry_id(match.group("id") or "") or ""
        if not name.strip():
            return None
        preceding = clause[: match.start()]
        count_match = _COUNT_BEFORE_TOKEN_RE.search(preceding)
        if count_match is None:
            count = 1
        elif count_match.group("word"):
            count = _NUMBER_WORD[count_match.group("word").lower()]
        else:
            count = max(1, int(count_match.group("digits")))
        pairs.append((name.strip(), count))
    return pairs


def _activity_range_ft(activity: Activity, melee_reach_ft: int) -> int | None:
    """The effective reach, in feet, of an attack/save activity for sibling choice.

    Mirrors ``orchestrator._monster_attack_range_ft``'s per-activity reading so
    the fallback selection and the movement gate agree on each sibling's range:

      * an ``AttackActivity`` with an explicit ``units == "ft"`` positive
        value uses it verbatim (the Scout longbow's ``"150"``); a Foundry melee
        attack (``units == "self"`` / empty value) falls back to ``melee_reach_ft``;
      * a ranged single-target ``SaveActivity`` (``units == "ft"``, positive
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

    Range/profile-aware when the live distance to the chosen target
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
    labelless-multiattack fallback's sibling choice when the live
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

    count = _parse_multiattack_count(_multiattack_clause(action.description))
    parsed = _parse_item_counts(action.description)

    # Precise path: every named token joins 1:1 to a sibling (case-insensitive),
    # and each is repeated its OWN parsed count — "makes two Claw attacks and
    # uses Roar" is 2 claws + 1 roar, not 2 of each.
    if parsed:
        by_name = {sibling.name.casefold(): sibling for sibling in siblings}
        matched = [(by_name.get(name.casefold()), name_count) for name, name_count in parsed]
        if all(sibling is not None for sibling, _ in matched):
            matched_resolved: list[Activity] = []
            for sibling, name_count in matched:
                assert sibling is not None  # narrowed by the all(...) guard
                sibling_activity = _first_offensive_activity(sibling)
                if sibling_activity is not None:
                    matched_resolved.extend([sibling_activity] * name_count)
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
