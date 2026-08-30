"""The combat seam — open a combat, drive it turn by turn, close it.

This module owns the engine's stateful combat loop and every piece of runtime
state behind it. Four coroutines are the whole public contract:

- ``start_combat`` — roll initiative, materialize runtime state, return a
  ``CombatHandle`` you thread through every later call.
- ``submit_player_intent`` — validate and resolve one PC intent.
- ``advance_monster_turn`` — run the built-in monster AI for one turn.
- ``end_combat`` — close the encounter and project a ``CombatOutcome``.

Each call emits typed ``CombatEvent`` objects, which
you read with ``narration_events`` (streaming) or ``drain_pending_events``
(pull). Live state is readable only through ``get_live``, which returns an
immutable ``LiveCombatView`` snapshot — the private
``_LiveCombat`` dataclass is never handed out.

How an intent resolves
----------------------
``submit_player_intent`` reads the intent's ``intent_type`` to pick an asset
reference (``weapon_id`` / ``spell_id`` / ``item_id`` / ``feature_id``), fetches
that typed entity through ``get_lib_loader``, and
walks its activities via the per-kind resolvers in
``activities``. Before resolving, it projects the actor's
current active effects and conditions into the resolution context, so passive
attack/damage/save modifiers land uniformly regardless of which game object
triggered the activity.

Scope and constraints worth knowing up front
--------------------------------------------
- **Determinism.** Every in-combat die is drawn from the ``random.Random``
  seeded by ``start_combat(rng_seed=...)``. Same seed + same intent sequence
  reproduces the same combat exactly, independent of global ``random`` state.
- **Movement is one step per intent.** A ``"move"`` intent must name an
  *adjacent* cell/zone; it does not path-find. Cross a room by submitting
  several moves.
- **Reactions are pre-armed.** The engine never pauses mid-resolution to ask a
  host "do you want to react?". A reactor arms a reaction on its own turn with
  a ``"ready"`` intent, and the engine fires it automatically when the trigger
  occurs.
- **Effects are combat-scoped.** They live in memory for the encounter and are
  discarded at ``end_combat``; persisting anything across combats is the host's
  job.

See ``docs/capabilities.md`` for the per-mechanic matrix of what is and is not
resolved today.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import random
import re
import warnings
from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from dnd5e_srd_data.schema.common import ActivationBlock, AttackActivity, SaveActivity
from dnd5e_srd_data.schema.item import Weapon, WeaponProperty
from dnd5e_srd_data.schema.spell import CastingTimeUnit, Spell, SpellRangeUnits
from pydantic import BaseModel, ConfigDict, Field, field_validator

from dnd5e_engine.activities.actor_stats import (
    ABILITY_CODES,
    check_modifier,
    save_modifier,
    skill_ability,
)
from dnd5e_engine.activities.attack import (
    attacker_advantage_flags,
    sneak_attack_dice,
    sneak_attack_triggers,
)
from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.d20 import AdvantageSources, roll_d20_test
from dnd5e_engine.activities.forced_movement import FORCED_MOVEMENT_RIDERS
from dnd5e_engine.activities.monster_actions import (
    expand_action_to_activities,
    select_typed_monster_action,
)
from dnd5e_engine.activities.passive_stats import CombatantSenses, interpret_passive_stats
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.activities.scale import build_scale_values
from dnd5e_engine.build_party import granted_feature_slugs
from dnd5e_engine.death_saves import DeathSaveState, roll_death_save
from dnd5e_engine.events import (
    ActorMoved,
    AdvantageMode,
    AdvantageSource,
    AttackFailed,
    AttackRolled,
    CastFailed,
    CombatantMoved,
    CombatEnded,
    CombatEvent,
    ConcentrationCheck,
    ConcentrationDropped,
    ConditionApplied,
    ConditionRemoved,
    DamageApplied,
    DashTaken,
    Death,
    EffectApplied,
    EffectExpired,
    HealingApplied,
    IntentSubmitted,
    IntentType,
    MoveFailed,
    ReactionTriggered,
    RoundStarted,
    SaveRolled,
    TempHpApplied,
    TurnEnded,
    TurnPhase,
    TurnStarted,
    Unconscious,
)
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.outcome import (
    CombatOutcome,
    DeathRecord,
    LootDrop,
)
from dnd5e_engine.rest import FEATURE_USE_COUNTER_PREFIX, ITEM_USE_COUNTER_PREFIX
from dnd5e_engine.rules.conditions import (
    Condition,
    active_condition_names,
    conditions_block_actions,
    d20_test_penalty,
    exhaustion_level_of,
    is_condition_active,
    project_passive_check_modifiers,
    project_passive_damage_modifiers,
    project_passive_save_modifiers,
    project_speed,
)
from dnd5e_engine.spatial import GridTopology, SpatialTopology, parse_cell
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)
from dnd5e_engine.turn_lifecycle import (
    TurnLifecycle,
    run_round_start,
    run_turn_end,
    run_turn_start,
)
from dnd5e_engine.types.combat import BehaviorProfile, Combatant
from dnd5e_engine.types.conditions import ActiveCondition
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange, ActiveEffectDuration
from dnd5e_engine.views import LiveCombatView

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dnd5e_srd_data.schema.class_ import Class, Subclass
    from dnd5e_srd_data.schema.species import Species


# ── Typed boundary-input models ─────────────────────────────────────────────
#
# PartyMemberSpec, EncounterMemberSpec, ZoneEdge, SceneTopology live in
# ``dnd5e_engine.specs`` (imported above). They are pure value-typed payloads
# the host passes into ``start_combat`` and have no app.* dependencies.

# SRD §Reactions — the closed set of trigger conditions the pre-armed reaction
# queue recognizes. Typed-semantics rule (CLAUDE.md): a field over
# a closed set is a Literal, never bare str. These three are the exact values
# ``PlayerIntent.reaction_trigger``'s own docstring already named as its
# intended examples.
ReactionTrigger = Literal["cast_spell", "hit_by_attack", "targeted_by_magic_missile"]


class PlayerIntent(BaseModel):
    """A PC's submitted intent for the current turn.

    The seam carries the union of optional asset references the intent-
    to-IR resolver consumes. The orchestrator chooses the right slot by
    ``intent_type`` (e.g. ``"attack"`` consumes ``weapon_id``;
    ``"cast_spell"`` consumes ``spell_id``; ``"use_item"`` consumes
    ``item_id``); ``feature_id`` rides alongside for class-feature
    activations the cutover prompt extends the IntentType enum to
    surface.
    """

    model_config = ConfigDict(extra="forbid")

    intent_type: IntentType
    spell_id: str | None = None
    target_id: str | None = None
    item_id: str | None = None
    weapon_id: str | None = None
    feature_id: str | None = None
    # SRD §Channel Divinity — the specific activity to resolve when a
    # USE_FEATURE names a multi-activity feature that is a repertoire of
    # ALTERNATIVES (Channel Divinity: Divine Spark Heal vs Save vs Turn Undead;
    # Cunning Strike's four options). Names one of the feature's activity ids.
    # ``None`` (the common case) leaves single-activity features unchanged and
    # keeps the safe no-op reject for a multi-activity feature (never guess).
    activity_id: str | None = None
    slot_level: int | None = None
    # Charges to spend on a variable-cost item invocation (wand upcast).
    # Validated by the use_item charge gate against consumption.scaling.
    charges_to_spend: int | None = Field(default=None, ge=1)
    # SRD §Reactions — the trigger condition a ``"ready"`` intent pre-arms
    # 's pending-reaction queue). Consumed by
    # ``_pop_pending_reaction`` / ``_drain_targeted_reactions`` when a
    # matching triggering intent is later submitted by any combatant.
    reaction_trigger: ReactionTrigger | None = None
    # SRD §Movement — destination zone id for ``intent_type == "move"``.
    # Resolved by the parser from player free-text ("move to the back of
    # the room") and projected through ``parsed_intent_to_player_intent``
    # from ``ParsedIntent.target_zone_id``.
    target_zone_id: str | None = None
    # C16 — SRD 5.2 §Areas of Effect: a Cone / Line / Cube "extends … in a
    # direction its creator chooses". Grid offset vector ``(dcol, drow)``; only
    # the sign of each component matters (one of the 8 grid directions). When
    # omitted for a directional template the orchestrator aims from the caster
    # through ``target_id``. Ignored for sphere / cylinder and non-AoE intents.
    direction: tuple[int, int] | None = None
    # SRD §Combat — Dash budget choice. False → Action (default). True → Bonus
    # Action (Rogue Cunning Action). The orchestrator rejects the bonus-action
    # path when the actor is not a Rogue. Carried from
    # ``ParsedIntent.use_bonus_action``.
    use_bonus_action: bool = False

    @field_validator("direction")
    @classmethod
    def _direction_nonzero(cls, value: tuple[int, int] | None) -> tuple[int, int] | None:
        if value is not None and value == (0, 0):
            raise ValueError("direction must be a nonzero grid vector")
        return value


# ── Public handle ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CombatHandle:
    """Opaque handle to a running combat (registry key)."""

    handle_id: str


# ── Typed seam exceptions ───────────────────────────────────────────────────


class CombatSeamError(Exception):
    """Base class for typed errors raised by the public combat seam."""


class UnknownHandleError(CombatSeamError):
    """Raised when a seam call references a handle not in the registry."""


class IntentRejectedError(CombatSeamError):
    """Raised when ``submit_player_intent`` rejects an intent.

    Carries a typed ``reason`` so callers can branch on the rejection
    cause without re-parsing the error message.
    """

    RejectionReason = Literal[
        "actor_not_in_initiative",
        "not_actor_turn",
        "combat_ended",
        "no_action_economy",
        "actor_incapacitated",
    ]

    def __init__(self, reason: RejectionReason, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# ── Internal scene topology (concretizes the scaffold's Protocol) ───────────


class _ZoneGraph:
    """Shortest-path ``within_range`` over an undirected zone graph.

    Satisfies the scaffold's ``ZoneTopology`` Protocol (``runtime.py``)
    via a structural ``within_range`` method. Implementation is a
    Dijkstra-style BFS bounded by ``range_ft`` — handler call sites
    that need positional reasoning hit this through the Protocol.
    """

    def __init__(self, topology: SceneTopology) -> None:
        self._zones: set[str] = set(topology.zones)
        self._adj: dict[str, list[tuple[str, int]]] = {z: [] for z in topology.zones}
        for edge in topology.edges:
            if edge.a not in self._zones or edge.b not in self._zones:
                raise ValueError(f"ZoneEdge references unknown zone: {edge.a!r}, {edge.b!r}")
            self._adj[edge.a].append((edge.b, edge.distance_ft))
            self._adj[edge.b].append((edge.a, edge.distance_ft))

    def is_adjacent(self, a: str, b: str) -> bool:
        """Return True iff ``a`` and ``b`` are directly connected by an edge.

        Adjacency is the gating predicate for phase-2 movement: a MOVE
        intent traverses exactly one edge per submission. Multi-edge
        pathing belongs to a future Dash/path-planning piece.
        """
        if a == b or a not in self._zones or b not in self._zones:
            return False
        return any(neighbour == b for neighbour, _ in self._adj[a])

    def edge_distance(self, a: str, b: str) -> int | None:
        """Return the distance_ft of the direct edge between ``a`` and ``b``, or None.

        ``None`` signals the zones are not adjacent (caller should reject
        the move). Multi-edge paths are not summed here — single-edge
        distance is what the per-turn movement budget consumes.
        """
        if a == b or a not in self._zones or b not in self._zones:
            return None
        for neighbour, distance in self._adj[a]:
            if neighbour == b:
                return distance
        return None

    def within_range(self, caster_zone: str, target_zone: str, range_ft: int) -> bool:
        if caster_zone == target_zone:
            return True
        if caster_zone not in self._zones or target_zone not in self._zones:
            return False
        # Dijkstra with early termination once we've passed range_ft.
        best: dict[str, int] = {caster_zone: 0}
        frontier: list[tuple[int, str]] = [(0, caster_zone)]
        while frontier:
            frontier.sort()
            dist, node = frontier.pop(0)
            if dist > range_ft:
                return False
            if node == target_zone:
                return True
            for neighbour, edge_w in self._adj[node]:
                new_dist = dist + edge_w
                if new_dist > range_ft:
                    continue
                if new_dist < best.get(neighbour, range_ft + 1):
                    best[neighbour] = new_dist
                    frontier.append((new_dist, neighbour))
        return False

    def distance_ft(self, a: str, b: str) -> int | None:
        """Shortest-path distance in feet over the zone graph; ``None`` when
        unreachable or unknown. (Zone graph is deprecated in 0.6 — parity only.)"""
        if a == b and a in self._zones:
            return 0
        path = self.shortest_path(a, b)
        if not path:
            return None
        return _path_total_distance(self, path)

    def shortest_path(self, a: str, b: str, *, avoid: Collection[str] = ()) -> list[str]:
        """Return the sequence of zones from ``a`` to ``b`` (inclusive), or ``[]``.

        Dijkstra over the undirected weighted zone graph. Returned list
        starts with ``a`` and ends with ``b`` when a path exists; the
        intermediate elements are the zones to traverse in order. Returns
        ``[]`` when either endpoint is unknown or no path connects them.
        For ``a == b`` returns ``[a]`` (degenerate "you're already there").

        Phase-5 monster gambits use this to plan "MOVE toward the target"
        — they walk the returned path step-by-step, paying each edge's
        distance_ft out of the per-turn movement budget.

        ``avoid``: zone graph — occupancy is not modelled; parameter accepted
        for Protocol parity, removed with the backend in 0.7.
        """
        if a not in self._zones or b not in self._zones:
            return []
        if a == b:
            return [a]
        # Standard Dijkstra with predecessor map.
        dist: dict[str, int] = {a: 0}
        prev: dict[str, str] = {}
        frontier: list[tuple[int, str]] = [(0, a)]
        while frontier:
            frontier.sort()
            d, node = frontier.pop(0)
            if node == b:
                # Reconstruct path.
                path = [b]
                while path[-1] != a:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            if d > dist.get(node, d):
                continue
            for neighbour, edge_w in self._adj[node]:
                new_dist = d + edge_w
                if new_dist < dist.get(neighbour, new_dist + 1):
                    dist[neighbour] = new_dist
                    prev[neighbour] = node
                    frontier.append((new_dist, neighbour))
        return []

    def has_line_of_sight(self, a: str, b: str) -> bool:
        # Zone graph has no occultation model; sight follows reachability of
        # the graph itself. Both endpoints known ⇒ line of sight. (Wall
        # geometry is a grid-only capability — see docs/dev/spatial-geometry.md.)
        return a in self._zones and b in self._zones

    def cover_between(
        self, a: str, b: str, occupied_cells: Collection[str] = ()
    ) -> Literal["none", "half", "three_quarters", "total"]:
        # Zone graph has no positional cover model — an abstract graph of
        # named locations has no coordinate system to hang obstruction
        # geometry off of. Always "none" preserves current zone-combat
        # behavior; documented, permanent backend split (not a gap) — see
        # docs/dev/spatial-geometry.md "Zone-backend decision".
        return "none"

    def cover_on_cell(self, cell: str) -> Literal["none", "half", "three_quarters", "total"]:
        # Same permanent no-cover-model split as ``cover_between`` above.
        return "none"

    def can_see(self, a: str, b: str, senses: CombatantSenses | None = None) -> bool:
        # Zone graph has no lighting model — everything in a known zone is
        # visible. Legacy backend, removed in 0.7.
        return a in self._zones and b in self._zones


def _weapon_attack_range_ft(weapon: Weapon | None) -> int | None:
    """Resolve the effective attack range for a typed weapon, in feet.

    Reads the typed ``Weapon.range`` block (lib loader):

      * melee weapons (``range.kind == "melee"``) reach 5ft, or 10ft when they
        carry the ``reach`` property (glaive/halberd/pike). ``range.value`` is
        NOT the melee reach — Foundry leaves it ``None`` for standard melee and
        reuses it for the THROWN range on thrown weapons (dagger=20, handaxe=20),
        so deriving reach from the ``reach`` property reproduces the old wrapper's
        ``reach_ft`` (5/10) faithfully and avoids treating a dagger's 20ft throw
        as its melee reach;
      * ranged weapons carry ``range.value`` as the in-range (normal) band;
        long-range disadvantage is a follow-up, not modeled here.

    Returns ``None`` when the weapon is missing or carries no usable
    range — the orchestrator skips the gate in that case.
    """
    if weapon is None:
        return None
    rng = weapon.range
    if rng.kind == "melee":
        return 10 if WeaponProperty.REACH in weapon.properties else 5
    normal = rng.value
    return normal if isinstance(normal, int) and normal > 0 else None


def _monster_attack_range_ft(activities: Sequence[Any], melee_reach_ft: int) -> int | None:
    """Resolve a monster turn's effective attack range from typed activities.

    The range gate keys off the FIRST offensive activity the turn will resolve
    (multiattack fans out to homogeneous sub-attacks, so the first activity's
    range governs the whole turn — matching the legacy single ``range_ft`` the
    loader wrapper carried). Only an explicit ``AttackActivity`` yields a
    finite reach the movement gate should honor:

      * an explicit numeric ``units == "ft"`` range (e.g. a ``"80"`` shortbow
        band) is used verbatim;
      * Foundry melee attacks ship ``units == "self"`` / no value (reach is
        implied), so they fall back to the monster's ``Combatant.melee_reach_ft``
        (5 by default, 10 for reach creatures) — reproducing the old
        ``range_ft == 5`` melee wrappers.

    A non-``AttackActivity`` offensive activity (a ``SaveActivity``)
    splits two ways:

      * a self-centered AoE (breath weapon: ``range.units == "self"`` OR a
        populated ``target.template.type``) carries NO movement reach — the
        monster resolves the save/effect from its current position, so we
        return ``None`` and the caller skips the gate (treating a self/template
        AoE as melee reach was the regression that forced dragons to close to
        5ft);
      * a ranged single-target save (giant-spider web ~60ft, mummy
        dreadful-glare ~30ft: ``range.units == "ft"`` with a real positive
        value and no measured template) is a genuine ranged gate — the monster
        must be within that range and closes the distance if it is not.

    Returns ``None`` when no offensive activity carries a usable finite reach —
    the caller then skips the movement gate (the legacy ``range_ft`` absence
    did the same).
    """
    for activity in activities:
        if not isinstance(activity, (AttackActivity, SaveActivity)):
            continue
        if not isinstance(activity, AttackActivity):
            # A non-attack offensive activity (SaveActivity). Two shapes:
            #   * self-centered AoE (breath weapon): ``range.units == "self"``
            #     OR a measured ``target.template.type`` — resolves from
            #     position, NO movement gate (return None);
            #   * ranged single-target save (giant-spider web ~60ft, mummy
            #     dreadful-glare ~30ft): ``range.units == "ft"`` with a real
            #     positive value and no measured template — a real ranged gate
            #     the monster must close to satisfy.
            rng = activity.range
            template_type = activity.target.template.type
            if rng.units == "self" or template_type:
                return None
            if rng.units == "ft" and rng.value is not None:
                try:
                    parsed = int(rng.value)
                except ValueError:
                    parsed = 0
                if parsed > 0:
                    return parsed
            return None
        rng = activity.range
        if rng.units == "ft":
            value = rng.value
            if value is not None:
                try:
                    parsed = int(value)
                except ValueError:
                    parsed = 0
                if parsed > 0:
                    return parsed
            # ``units == "ft"`` with an empty/zero value is an explicit "no
            # range" datum, not a melee attack — fall through to reach.
        # Foundry melee (``units == "self"``) or an unusable ft value: the
        # monster's reach governs.
        return melee_reach_ft if melee_reach_ft > 0 else None
    return None


def _monster_is_fleeing(monster: Combatant) -> bool:
    """Replicate the legacy behavior-based flee / low-HP gate.

    Faithful port of ``monster_ai.select_monster_action`` (monster_ai.py:163-171):
    an AGGRESSIVE monster passes below 10% HP, a RANGED one below 25%; DEFENSIVE
    monsters never flee. The typed selector (``select_typed_monster_action``)
    takes only the static ``Monster`` and so lost access to live HP — this gate
    re-applies it against the runtime ``Combatant`` before selection.
    """
    try:
        profile = BehaviorProfile(monster.behavior_profile)
    except ValueError:
        profile = BehaviorProfile.AGGRESSIVE
    hp_ratio = monster.hp_current / monster.hp_max if monster.hp_max > 0 else 0.0
    flee_threshold = 0.25 if profile == BehaviorProfile.RANGED else 0.10
    return profile != BehaviorProfile.DEFENSIVE and hp_ratio < flee_threshold


def _in_range_with_los(topology: SpatialTopology, a: str, b: str, range_ft: int) -> bool:
    """True iff ``b`` is within ``range_ft`` of ``a``, ``a`` has line of sight to
    ``b``, AND ``b`` does not have total cover from ``a``.

    The single range+LoS+cover predicate every attack/cast gate routes
    through. SRD 5.2 §Cover: a target with total cover "can't be targeted
    directly" — reuses the same rejection surface (``AttackFailed(reason=
    "out_of_range")``) every other range/LoS rejection already uses. On a
    backend/scene with no wall or cover geometry, ``has_line_of_sight`` is
    always True and ``cover_between`` is always ``"none"``, so this is
    behaviour-identical to a bare ``within_range`` (byte-for-byte preserved).
    """
    return (
        topology.within_range(a, b, range_ft)
        and topology.has_line_of_sight(a, b)
        and topology.cover_between(a, b) != "total"
    )


def _occupied_cells(live: _LiveCombat, *, exclude: Collection[str]) -> set[str]:
    """Cells/zones currently occupied by alive combatants other than ``exclude``
    (entity ids). SRD 5.2 §Cover — "another creature" is a half-cover source;
    §Moving Around Other Creatures — an enemy's space blocks movement."""
    excluded = set(exclude)
    return {
        zone
        for c in live.initiative
        if c.is_alive
        and c.entity_id not in live.dead_ids
        and c.entity_id not in excluded
        and (zone := live.actor_zone.get(c.entity_id)) is not None
    }


def _target_cover_map(
    live: _LiveCombat,
    caster_id: str,
    targets: Sequence[Combatant],
    *,
    origin_cell: str | None = None,
) -> dict[str, str]:
    """SRD 5.2 §Cover — per-target cover degree between the point of origin and
    each target, from scene geometry AND creature occupancy (every other alive
    combatant's cell grants half cover when it lies on the line; ally or enemy
    makes no difference).

    The origin is ``caster_id``'s own cell for an attack or a single-target
    cast. For an AREA of effect the SRD measures cover from the area's point of
    origin instead — a Fireball centred forty feet away shields its victims
    from the BURST POINT, not from the wizard — so the AoE cast path passes the
    resolved template origin as ``origin_cell`` (see ``_aoe_cover_origin``).
    When ``origin_cell`` is given the caster is no longer assumed to stand on
    the origin, so it is no longer excluded from the occupancy sweep: a caster
    standing between the burst point and a victim grants that victim half cover
    like any other creature. ``cover_between`` skips the origin cell itself, so
    a self-origin template (cone, Thunderwave's cube) is unaffected.

    DEGENERATE CASE — the burst point coincides with the one creature it
    affects (a small sphere centred on a lone target, e.g. Acid Splash cast
    at a single foe): ``origin == target_zone``, so ``cover_between``'s line
    walk (which always excludes its own ``a`` endpoint) would see nothing at
    all and silently drop a cover tag sitting on that shared cell. SRD 5.2
    §Cover ("an object that covers at least half of the target") still
    shields a creature standing in or behind an obstruction in its own
    space, so this case reads the tag directly off that cell
    (``cover_on_cell``) instead of walking a line to itself. A genuine
    multi-target burst (the origin differs from at least one victim's cell)
    is unaffected — each OTHER target still measures cover from the true
    burst point via the ordinary line walk.

    Threaded into ``ActivityResolutionContext.target_cover`` so
    ``activities/attack.py`` (AC) and ``activities/save_primitive.py``
    (Dexterity saves) can fold the SRD +2/+5 bonus without either resolver
    importing the spatial seam directly. Absent zone tracking for the caster or
    a target (e.g. a zone-graph combat with no positional data at all)
    contributes ``"none"`` — mirrors ``_ZoneGraph.cover_between``'s permanent
    no-cover behavior.
    """
    origin = origin_cell if origin_cell is not None else live.actor_zone.get(caster_id)
    if origin is None:
        return {}
    out: dict[str, str] = {}
    for target in targets:
        target_zone = live.actor_zone.get(target.entity_id)
        if target_zone is None:
            continue
        if origin_cell is not None and origin == target_zone:
            out[target.entity_id] = live.topology.cover_on_cell(target_zone)
            continue
        exclude = (target.entity_id,) if origin_cell is not None else (caster_id, target.entity_id)
        occupied = _occupied_cells(live, exclude=exclude)
        out[target.entity_id] = live.topology.cover_between(origin, target_zone, occupied)
    return out


def _target_visibility_maps(
    live: _LiveCombat, caster: Combatant, targets: Sequence[Combatant]
) -> tuple[dict[str, bool], dict[str, bool]]:
    """SRD 5.2 "Unseen Attackers and Targets" — per target, (attacker cannot
    see target, target cannot see attacker), from ``SpatialTopology.can_see``
    with each viewer's own ``Combatant.senses``. Untracked positions ⇒ seen.

    Threaded into ``ActivityResolutionContext.target_unseen`` /
    ``.attacker_unseen_by`` so ``activities/attack.py`` can add the ``"unseen"``
    disadvantage / advantage source without importing the spatial seam. A
    zone-graph combat (``_ZoneGraph.can_see`` ⇒ True for any two known zones)
    and a scene with no lighting data both yield all-False maps ⇒ ``normal``.
    """
    caster_zone = live.actor_zone.get(caster.entity_id)
    target_unseen: dict[str, bool] = {}
    attacker_unseen_by: dict[str, bool] = {}
    if caster_zone is None:
        return target_unseen, attacker_unseen_by
    for target in targets:
        target_zone = live.actor_zone.get(target.entity_id)
        if target_zone is None:
            continue
        target_unseen[target.entity_id] = not live.topology.can_see(
            caster_zone, target_zone, caster.senses
        )
        attacker_unseen_by[target.entity_id] = not live.topology.can_see(
            target_zone, caster_zone, target.senses
        )
    return target_unseen, attacker_unseen_by


def _target_distance_map(
    live: _LiveCombat, caster_id: str, targets: Sequence[Combatant]
) -> dict[str, int]:
    """Per-target attacker→target distance in feet (``SpatialTopology.distance_ft``),
    threaded into ``ActivityResolutionContext.target_distance_ft`` for the
    distance-aware condition rows (SRD 5.2 Prone). A participant without a
    tracked position, or an unreachable pair, is simply absent (the rows stay
    inert) — mirrors ``_target_cover_map``.
    """
    caster_zone = live.actor_zone.get(caster_id)
    if caster_zone is None:
        return {}
    out: dict[str, int] = {}
    for target in targets:
        target_zone = live.actor_zone.get(target.entity_id)
        if target_zone is None:
            continue
        distance = live.topology.distance_ft(caster_zone, target_zone)
        if distance is not None:
            out[target.entity_id] = distance
    return out


#: ``ActiveEffect.origin`` prefixes whose THIRD ``:``-segment is the entity that
#: created the effect (``cast:<slug>:<caster_id>`` is the shipped convention;
#: ``grapple:<slug>:<grappler_id>`` is reserved for C14's grapple contest).
_ENTITY_ORIGIN_PREFIXES: frozenset[str] = frozenset({"cast", "grapple"})


def _condition_source_entity(live: _LiveCombat, combatant: Combatant, condition: str) -> str | None:
    """Who imposed ``condition`` on ``combatant`` (the grappler, the charmer)?

    Resolution order: an ``ActiveCondition.source_entity_id`` that is a real
    entity id (not an ``implied:*`` marker); else the imposing ``ActiveEffect``
    (via ``source_effect_id``) whose ``origin`` encodes its creator. ``None``
    when unknown — every consumer treats unknown as "no restriction".
    """
    for ac in combatant.conditions:
        if ac.condition != condition:
            continue
        if not ac.source_entity_id.startswith("implied:"):
            return ac.source_entity_id
        if ac.source_effect_id is None:
            continue
        for eff in live.active_effects.get(combatant.entity_id, []):
            if eff.id != ac.source_effect_id:
                continue
            parts = (eff.origin or "").split(":", 2)
            if len(parts) == 3 and parts[0] in _ENTITY_ORIGIN_PREFIXES and parts[2]:
                return parts[2]
    return None


def _sneak_ally_adjacent_map(
    live: _LiveCombat, caster: Combatant, targets: Sequence[Combatant]
) -> dict[str, bool]:
    """SRD §Sneak Attack (Rogue), ally-adjacent alternative — per target, is at
    least one of the caster's allies within 5 ft of that target and NOT
    Incapacitated?

    A new CONSUMER of the ``spatial.py`` distance seam (``within_range`` at 5
    ft), NOT a new spatial primitive. "Ally" = a living combatant on the
    caster's own side (party vs encounter) other than the caster. The
    Incapacitated read uses the SRD condition-implication chain (Paralyzed /
    Stunned / Petrified / Unconscious all imply Incapacitated). Threaded into
    ``ActivityResolutionContext.sneak_attack_ally_adjacent`` so the pure
    resolver never touches the spatial seam. Absent zone data for the caster's
    side, a target, or every ally contributes no entry (⇒ no adjacent ally).
    """
    if caster.entity_id in live.party_ids:
        side = live.party_ids
    elif caster.entity_id in live.encounter_ids:
        side = live.encounter_ids
    else:
        return {}
    allies = [
        c
        for c in live.initiative
        if c.entity_id in side
        and c.entity_id != caster.entity_id
        and c.is_alive
        and not is_condition_active(Condition.INCAPACITATED, active_condition_names(c.conditions))
    ]
    if not allies:
        return {}
    out: dict[str, bool] = {}
    for target in targets:
        target_zone = live.actor_zone.get(target.entity_id)
        if target_zone is None:
            continue
        for ally in allies:
            ally_zone = live.actor_zone.get(ally.entity_id)
            if ally_zone is not None and live.topology.within_range(ally_zone, target_zone, 5):
                out[target.entity_id] = True
                break
    return out


def push_combatant(live: _LiveCombat, target_id: str, origin_cell: str, distance_ft: int) -> None:
    """Forced movement primitive — move ``target_id`` up to ``distance_ft``
    straight away from ``origin_cell`` and emit ``CombatantMoved(forced=True)``
    for the distance actually covered. Consumes no movement budget and
    provokes no opportunity attack (SRD 5.2 §Opportunity Attacks). Grid-only:
    the zone graph has no direction to push along (legacy backend, removed in
    0.7) — a no-op there. A dead or untracked target is never moved, and a
    target sharing ``origin_cell`` with the pusher has no direction to be
    pushed along: no move and no event."""
    topology = live.topology
    target_cell = live.actor_zone.get(target_id)
    if not isinstance(topology, GridTopology) or target_cell is None or target_id in live.dead_ids:
        return  # zone graph: legacy behaviour until removal in 0.7
    occupied = _occupied_cells(live, exclude=(target_id,))
    path = topology.push_path(origin_cell, target_cell, distance_ft, occupied_cells=occupied)
    if not path:
        return
    live.actor_zone[target_id] = path[-1]
    _emit(
        live,
        CombatantMoved(
            actor_id=target_id,
            from_zone=target_cell,
            to_zone=path[-1],
            distance_ft=len(path) * topology.cell_size_ft,
            forced=True,
        ),
    )


def _apply_forced_movement_riders(
    live: _LiveCombat, caster: Combatant, intent: PlayerIntent, pre_event_count: int
) -> None:
    """After a cast resolves, apply the spell's typed forced-movement rider to
    every target whose save against the SPELL failed (trigger ``failed_save``).

    Only the FIRST ``SaveRolled`` per target in this resolution's event slice
    is the spell's own save: damage application emits a second, transitional
    ``SaveRolled(ability="con")`` alongside every ``ConcentrationCheck``
    (removed in v0.7), and a concentrating creature that SAVED against the
    spell must not be shoved because it later dropped concentration. The save
    resolver always emits before ``DamageApplied``, so "first per target" is
    well defined; keying on it also caps each target at one push.

    Pushes happen after all saves/damage so the rider never perturbs the
    seeded roll order."""
    rider = FORCED_MOVEMENT_RIDERS.get(intent.spell_id or "")
    if rider is None or rider.trigger != "failed_save" or rider.direction != "away_from_caster":
        return
    origin_cell = live.actor_zone.get(caster.entity_id)
    if origin_cell is None:
        return
    seen: set[str] = set()
    for ev in list(live.event_log[pre_event_count:]):
        if not isinstance(ev, SaveRolled) or ev.target_id in seen:
            continue
        seen.add(ev.target_id)
        if not ev.succeeded:
            push_combatant(live, ev.target_id, origin_cell, rider.distance_ft)


def _record_sneak_attack_spent(
    live: _LiveCombat,
    caster: Combatant,
    intent: PlayerIntent,
    weapon: Weapon | None,
    targets: Sequence[Combatant],
    actx: ActivityResolutionContext,
    pre_event_count: int,
) -> None:
    """SRD §Sneak Attack, "Once per turn" — flip the caster's per-turn
    ``sneak_attack_spent_this_turn`` flag once a rider has actually fired.

    The rider folds inside the pure resolver; recording the actor-state is the
    orchestrator's job. A rider fired iff this was a weapon attack, the caster
    has Sneak Attack dice, was not already spent, and at least one damaged
    target satisfied the trigger (``sneak_attack_triggers`` — the SAME predicate
    the resolver gated the fold on, reused here so the two never diverge).

    Today no PC multi-attack-per-turn intent path exists, so the flag it sets is
    never re-read within the same turn (the cap is exercised only at the resolver
    seam, . Recording it anyway keeps the actor-state honest for the day
    a second-attack path lands.
    """
    if intent.intent_type != "attack" or weapon is None:
        return
    if caster.sneak_attack_spent_this_turn or sneak_attack_dice(actx) is None:
        return
    has_advantage, has_disadvantage = attacker_advantage_flags(actx)
    damaged_ids = {
        e.target_id for e in live.event_log[pre_event_count:] if isinstance(e, DamageApplied)
    }
    fired = any(
        target.entity_id in damaged_ids
        and sneak_attack_triggers(
            actx,
            weapon,
            target,
            attacker_has_advantage=has_advantage,
            attacker_has_disadvantage=has_disadvantage,
        )
        for target in targets
    )
    if not fired:
        return
    for idx, c in enumerate(live.initiative):
        if c.entity_id == caster.entity_id:
            live.initiative[idx] = c.model_copy(update={"sneak_attack_spent_this_turn": True})
            break


def _path_total_distance(topology: SpatialTopology, path: Sequence[str]) -> int | None:
    """Sum a shortest-path's edge distances; ``None`` if any step is missing.

    ``path`` is the zone/cell sequence ``shortest_path`` returns (``path[0]``
    is the start). A one-element or empty path costs ``0``.
    """
    if len(path) < 2:
        return 0
    total = 0
    for a, b in itertools.pairwise(path):
        step = topology.edge_distance(a, b)
        if step is None:
            return None
        total += step
    return total


def _monster_dash_movement_budget(
    total_path_distance: int | None,
    movement_remaining: int,
    base_speed: int,
) -> int | None:
    """SRD §Actions in Combat, Dash — decide whether a monster gambit should
    Dash to close a gap it cannot otherwise cross this turn.

    Returns the doubled movement budget (``movement_remaining + base_speed``,
    mirroring ``_handle_dash``'s additive convention) when the path to the
    target exceeds the current budget but fits within a single Dash; ``None``
    when no Dash is needed (already in reach) or a Dash still wouldn't be
    enough (the monster gives up on closing the gap, same as today).
    """
    if total_path_distance is None or base_speed <= 0:
        return None
    if total_path_distance <= movement_remaining:
        return None  # already affordable — no Dash needed
    dashed_budget = movement_remaining + base_speed
    if total_path_distance > dashed_budget:
        return None  # even a Dash can't close this gap
    return dashed_budget


def _plan_flee_destination(
    topology: SpatialTopology,
    start_zone: str,
    threat_zone: str,
    movement_remaining: int,
) -> str | None:
    """Pick the reachable zone that MAXIMIZES topology distance from a threat.

    The inverse of ``advance_monster_turn``'s greedy CLOSING walk: rather than
    stepping along ``shortest_path`` *toward* the target, enumerate every zone
    reachable within ``movement_remaining`` and choose the one whose distance to
    ``threat_zone`` is greatest (ties broken toward the cheapest to reach, then
    zone id for determinism). Returns ``None`` when no reachable zone strictly
    increases the distance to the threat — the monster then holds its ground.

    Zone-graph only: a grid backend exposes no finite named-zone set to rank, so
    a fleeing monster on a grid stays put (not a pinned behaviour — grid retreat
    pathing is a surviving BACKLOG item). Composed entirely from the existing
    ``shortest_path`` / ``edge_distance`` primitives (via ``_path_total_distance``);
    no new ``SpatialTopology`` capability is introduced.
    """
    if not isinstance(topology, _ZoneGraph):
        return None
    baseline = _path_total_distance(topology, topology.shortest_path(start_zone, threat_zone))
    if baseline is None:
        return None
    # (dist_to_threat, cost_to_reach, zone) for each zone that (a) is reachable
    # within budget and (b) strictly increases distance from the threat.
    candidates: list[tuple[int, int, str]] = []
    for zone in sorted(topology._zones):
        if zone == start_zone:
            continue
        cost = _path_total_distance(topology, topology.shortest_path(start_zone, zone))
        if cost is None or cost > movement_remaining:
            continue
        dist = _path_total_distance(topology, topology.shortest_path(zone, threat_zone))
        if dist is None or dist <= baseline:
            continue
        candidates.append((dist, cost, zone))
    if not candidates:
        return None
    # Farthest from the threat wins; ties → cheapest to reach → stable zone id.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    return candidates[0][2]


def _walk_zone_path(live: _LiveCombat, mover_id: str, path: Sequence[str]) -> None:
    """Step ``mover_id`` along ``path`` (a ``shortest_path`` result), paying each
    edge out of ``movement_remaining`` and emitting one ``ActorMoved`` per step.

    The fleeing-retreat counterpart to ``advance_monster_turn``'s inline CLOSING
    walk (kept separate: the closing loop early-outs once the target is in attack
    range, which a retreat has no analogue for). Fires PC opportunity attacks
    before the mover leaves each zone and stops if an AoO drops the mover, or once
    the next edge no longer fits the remaining budget.
    """
    for next_zone in path[1:]:
        snapshot = next(c for c in live.initiative if c.entity_id == mover_id)
        from_zone = live.actor_zone[mover_id]
        step_distance = live.topology.edge_distance(from_zone, next_zone)
        if step_distance is None or snapshot.movement_remaining < step_distance:
            break
        if _fire_pc_opportunity_attacks_on_move(
            live, mover_id=mover_id, from_zone=from_zone, to_zone=next_zone
        ):
            break
        for idx, c in enumerate(live.initiative):
            if c.entity_id == mover_id:
                live.initiative[idx] = c.model_copy(
                    update={"movement_remaining": c.movement_remaining - step_distance}
                )
                break
        live.actor_zone[mover_id] = next_zone
        _emit(
            live,
            ActorMoved(
                actor_id=mover_id,
                from_zone=from_zone,
                to_zone=next_zone,
                distance_ft=step_distance,
            ),
        )


def _execute_flee_retreat(
    live: _LiveCombat, monster: Combatant, alive_pcs: Sequence[Combatant]
) -> None:
    """A fleeing monster spends movement increasing distance from its threat.

    Monster-AI plumbing (DM-adjudicated, not codified SRD text): the flee gate
    ``_monster_is_fleeing`` decides the monster *wants* to disengage; this gives
    that decision teeth. The threat is the nearest alive PC by topology distance;
    the destination is ``_plan_flee_destination``'s farthest-reachable zone. When
    no such zone exists (already cornered, no budget, or grid backend) the monster
    simply holds — the same no-move it did before, now via a real evaluation.
    """
    start_zone = live.actor_zone.get(monster.entity_id)
    if start_zone is None or not alive_pcs:
        return
    threats: list[tuple[int, str, str]] = []
    for pc in alive_pcs:
        pc_zone = live.actor_zone.get(pc.entity_id)
        if pc_zone is None:
            continue
        dist = _path_total_distance(live.topology, live.topology.shortest_path(start_zone, pc_zone))
        if dist is not None:
            threats.append((dist, pc.entity_id, pc_zone))
    if not threats:
        return
    threats.sort(key=lambda t: (t[0], t[1]))
    _, _, threat_zone = threats[0]
    destination = _plan_flee_destination(
        live.topology, start_zone, threat_zone, monster.movement_remaining
    )
    if destination is None:
        return
    _walk_zone_path(live, monster.entity_id, live.topology.shortest_path(start_zone, destination))


def _monster_target_distance_ft(
    live: _LiveCombat, monster_id: str, target: Combatant | None
) -> int | None:
    """Zone-path distance (ft) from a monster to its chosen target, or ``None``.

    The same shortest-path cost the movement gate reads — handed to
    ``expand_action_to_activities`` so its range-aware multiattack fallback and
    the gate agree on the live distance . ``None`` when either actor
    has no known zone or no path connects them.
    """
    if target is None:
        return None
    monster_zone = live.actor_zone.get(monster_id)
    target_zone = live.actor_zone.get(target.entity_id)
    if monster_zone is None or target_zone is None:
        return None
    path = live.topology.shortest_path(monster_zone, target_zone)
    return _path_total_distance(live.topology, path)


def _pc_attack_out_of_range(live: _LiveCombat, actor_id: str, intent: PlayerIntent) -> bool:
    """True iff the PC attack would be rejected by the weapon-reach gate.

    Returns ``False`` when the gate doesn't apply (no target, no weapon
    id, unknown weapon, no extractable reach/range, or zone not tracked
    for one of the participants) — those cases fall through to the
    resolver, which then either synthesizes IR or returns empty.
    """
    if intent.target_id is None or not intent.weapon_id:
        return False
    weapon = get_lib_loader().get_weapon(intent.weapon_id)
    weapon_reach = _weapon_attack_range_ft(weapon)
    if weapon_reach is None:
        return False
    attacker_zone = live.actor_zone.get(actor_id)
    target_zone = live.actor_zone.get(intent.target_id)
    if attacker_zone is None or target_zone is None:
        return False
    return not _in_range_with_los(live.topology, attacker_zone, target_zone, weapon_reach)


def _attack_out_of_range_failure(
    live: _LiveCombat, actor_id: str, intent: PlayerIntent
) -> CombatEvent | None:
    """``AttackFailed(reason="out_of_range")`` when ``intent`` is a
    weapon-reach-gated attack; ``None`` otherwise. One of the
    ``pre_resolution_gates`` failure-builders consumed by
    ``submit_player_intent``."""
    if intent.intent_type != "attack" or not _pc_attack_out_of_range(live, actor_id, intent):
        return None
    return AttackFailed(actor_id=actor_id, target_id=intent.target_id, reason="out_of_range")


_HARMFUL_ACTIVITY_KINDS: frozenset[str] = frozenset({"attack", "damage", "save"})


def _spell_is_harmful(spell: Spell) -> bool:
    """SRD 5.2 Charmed's "damaging abilities or magical effects" — a spell with
    any attack / damage / save activity. Heal- and utility-only spells are
    not restricted."""
    return any(a.kind in _HARMFUL_ACTIVITY_KINDS for a in spell.activities)


def _charmed_target_violation(
    live: _LiveCombat, current: Combatant, intent: PlayerIntent
) -> str | None:
    """The charmer's id when ``intent`` would attack / harmfully target the
    creature that charmed ``current``; ``None`` otherwise (not charmed, unknown
    charmer, other target, beneficial spell, non-targeting intent)."""
    if intent.target_id is None or not is_condition_active(
        Condition.CHARMED, _condition_names(current)
    ):
        return None
    charmer = _condition_source_entity(live, current, "charmed")
    if charmer is None or charmer != intent.target_id:
        return None
    if intent.intent_type == "attack":
        return charmer
    if intent.intent_type == "cast_spell" and intent.spell_id:
        spell = get_lib_loader().get_spell(intent.spell_id)
        if spell is not None and _spell_is_harmful(spell):
            return charmer
    return None


def _charmed_target_failure(
    live: _LiveCombat, actor_id: str, current: Combatant, intent: PlayerIntent
) -> CombatEvent | None:
    """The typed Charmed-target rejection (``AttackFailed`` / ``CastFailed``,
    reason ``target_is_charmer``) when ``intent`` would attack or harmfully
    target the charmer; ``None`` when the gate doesn't apply. One of the
    ``pre_resolution_gates`` failure-builders consumed by
    ``submit_player_intent``."""
    charmer = _charmed_target_violation(live, current, intent)
    if charmer is None:
        return None
    if intent.intent_type == "attack":
        return AttackFailed(actor_id=actor_id, target_id=charmer, reason="target_is_charmer")
    return CastFailed(actor_id=actor_id, spell_id=intent.spell_id or "", reason="target_is_charmer")


def _synthesize_attack_from_weapon(weapon: Weapon) -> AttackActivity:
    """Build a base-weapon ``AttackActivity`` for a weapon with no
    activities of its own.

    A handful of magic weapons (frost-brand, flame-tongue, …) ship empty
    ``activities`` because their attack rides the base mundane weapon they
    enchant. A bare ``AttackActivity`` (empty ``attack.ability`` ⇒ the
    resolver picks the weapon's SRD default ability; empty ``damage.parts``
    with ``include_base=True`` ⇒ the handler rolls ``weapon.damage_parts``)
    reproduces the OLD ``_synthesize_weapon_attack`` behavior: one melee/ranged
    swing dealing the weapon's own dice plus the governing-ability mod.
    """
    return AttackActivity(
        id=f"synth:{weapon.slug}",
        activation=ActivationBlock(type="action", value=1),
    )


# ── Internal live-combat state ──────────────────────────────────────────────


@dataclass
class _LiveCombat:
    """Per-combat state held by the orchestrator.

    Additive scope (per 01-boundary-api.md): in-memory only. The cutover
    prompt swaps this for the existing host storage-backed combat state in
    ``app/session/manager.py``. Keeping it in-memory here lets the
    boundary surface be exercised standalone without coupling to
    session/host storage fixtures.
    """

    handle_id: str
    session_id: str
    initiative: list[Combatant]
    party_ids: set[str]
    encounter_ids: set[str]
    topology: SpatialTopology
    rng: random.Random
    event_queue: asyncio.Queue[CombatEvent | None]
    scene_location_id: str
    current_turn_index: int = 0
    round_number: int = 1
    ended: bool = False
    final_outcome: CombatOutcome | None = None
    # zone occupancy, per entity_id (read by handlers via the ZoneTopology)
    actor_zone: dict[str, str] = field(default_factory=dict)
    # monster-template slug, per entity_id (drives gambit lookup in
    # ``advance_monster_turn``). Absent for PCs and slug-less NPCs.
    monster_slug_by_entity: dict[str, str] = field(default_factory=dict)
    # SRD §Encounter XP — monster.xp_value per encounter member, indexed by
    # entity_id. Used by ``end_combat`` to compute total XP awarded.
    xp_value_by_entity: dict[str, int] = field(default_factory=dict)
    # Outcome-population running state (Agent 03). The event listener wired in
    # ``_emit`` mutates these as each ``CombatEvent`` flows through, so
    # ``end_combat`` can project a populated outcome from a single source of
    # truth. Per-effect handlers do NOT mutate ``Combatant.hp_current`` /
    # ``temp_hp`` / ``is_alive`` directly — the orchestrator owns end-state
    # derivation from the event stream.
    event_log: list[CombatEvent] = field(default_factory=list)
    tracked_hp: dict[str, int] = field(default_factory=dict)
    tracked_temp_hp: dict[str, int] = field(default_factory=dict)
    # active condition set per target_id; final outcome lifts permanent ones.
    active_conditions: dict[str, set[str]] = field(default_factory=dict)
    # active effect: target_id → list of full ActiveEffect documents.
    # Foundry-shaped: identity is (target_id, effect.id, effect.origin),
    # so two PCs both casting Bless on the same target produce two
    # entries (distinct origins) rather than collapsing into one record.
    active_effects: dict[str, list[ActiveEffect]] = field(default_factory=dict)
    # dead encounter members, in death order (drives loot + XP projection).
    deaths_recorded: list[DeathRecord] = field(default_factory=list)
    dead_ids: set[str] = field(default_factory=set)
    # pc_id → {slot_or_feature_label: count_used} (from EffectApplied with
    # concentration / known feature names — projected onto expended_resources).
    expended_resources: dict[str, dict[str, int]] = field(default_factory=dict)
    # current actor (set at TurnStarted) — credited as killer when a non-PC
    # drops to ≤0 HP and the orchestrator synthesizes a Death event.
    current_actor_id: str | None = None
    # SRD §Spellcasting + class features — caster resource pools, indexed by
    # entity_id. Populated at ``start_combat`` from ``PartyMemberSpec``;
    # consumed by ``_build_hydration_payload`` to project the per-caster
    # sidecar payload before each evaluator invocation. Non-PCs are absent
    # from these maps (treated as "no spells / no counters" by the handlers).
    spell_slots_by_entity: dict[str, dict[int, int]] = field(default_factory=dict)
    spells_known_by_entity: dict[str, list[str]] = field(default_factory=dict)
    custom_counters_by_entity: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    # SRD §Concentration — persistent IEffect parent/child lifecycle graph.
    # ``concentration_chain[caster_id] = [(target_id, effect.id, effect.origin), …]``
    # — full Foundry-shaped identity tuple per emitted effect so two PCs
    # both casting Bless never collapse into a single record. Survives
    # across turns; the transient ``ctx.parent_chain`` on RuntimeContext
    # is per-evaluation only and cannot be relied on for cross-turn
    # cascade walks. Written by ``_record_effect_lifecycle_links`` after
    # each evaluator run; read by ``_drop_concentration`` when a
    # concentration drop must cascade EffectExpired + ConditionRemoved.
    concentration_chain: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    # SRD §Conditions — per-effect condition lineage. Keyed by the
    # Foundry-shaped identity tuple ``(target_id, effect.id, effect.origin)``;
    # value is the list of ConditionType values that the named
    # effect-instance applied to that target. Walked on EffectExpired
    # (concentration_drop) to synthesize the matching ConditionRemoved
    # cascade. The session-side ``ActiveCondition.source_effect_id`` is
    # the long-term home; the orchestrator's in-memory equivalent lives
    # here until the cutover lands.
    conditions_by_effect: dict[tuple[str, str, str], list[str]] = field(default_factory=dict)
    # SRD §Hold Person — end-of-turn repeat-save specs. Keyed by the
    # Foundry-shaped identity tuple ``(target_id, effect.id, effect.origin)``;
    # value is the list of pending saves the target rolls at the end
    # of each of their turns. Each spec carries the ability, DC, the
    # condition the spell applied, the source ``effect_name`` (for
    # ``ConcentrationDropped`` projection), and the caster_id (used to
    # clear ``concentration_chain`` on success). Populated by
    # ``_record_effect_lifecycle_links``; consumed by ``_run_end_of_turn_saves``.
    repeat_save_on_turn_end: dict[tuple[str, str, str], list[dict[str, Any]]] = field(
        default_factory=dict
    )
    # Per-call event subscribers — ``start_combat`` and ``end_combat`` push a
    # local list's ``append`` here to capture events emitted during their
    # body, then pop it on return. This is how those entry points surface
    # an ``events`` list on the result envelope without changing the
    # canonical queue-based delivery for ``narration_events``.
    event_listeners: list[Any] = field(default_factory=list)
    # SRD §Reactions — 's pre-armed reaction queue (see
    # docs/dev/reaction-queue.md). Populated by a ``"ready"`` intent; drained
    # (popped + resolved) by ``_pop_pending_reaction`` when a matching trigger
    # is observed from another combatant's intent.
    pending_reactions: list[_PendingReaction] = field(default_factory=list)
    # SRD §Reactions / one-round buffs — a reaction-applied effect (Shield)
    # fires DURING another actor's turn, so the generic caster-turn-end
    # duration tick (``_tick_durations_at_turn_end``) won't recur until the
    # reactor's own NEXT turn ends — one full turn too late for a "until the
    # start of your next turn" effect. Keyed by the effect owner/caster's
    # entity_id -> list of (target_id, effect.id, effect.origin) identities to
    # expire the moment that owner's OWN next TurnStarted fires (see
    # ``_emit_apply_turn_started``). Populated by ``_resolve_readied_spell_cast``.
    reaction_effects_pending_expiry: dict[str, list[tuple[str, str, str]]] = field(
        default_factory=dict
    )
    # Turn-boundary hook registry (``dnd5e_engine.turn_lifecycle``). Populated
    # by ``_register_default_turn_hooks`` in ``start_combat``; run by
    # ``_end_turn_and_advance`` / ``_begin_turn``. Every rule that fires "at the
    # start/end of a turn" registers here rather than being open-coded into the
    # advance path.
    lifecycle: TurnLifecycle = field(default_factory=TurnLifecycle)


@dataclass(frozen=True)
class _PendingReaction:
    """One armed-but-not-yet-fired reaction — 's queue entry.

    Registered by a ``"ready"`` intent (``owner_id`` spends their Action to
    arm it); popped + resolved by ``_pop_pending_reaction`` the moment a
    matching ``trigger`` is next observed from any OTHER combatant's
    intent. See ``docs/dev/reaction-queue.md``.
    """

    owner_id: str
    trigger: ReactionTrigger
    spell_id: str | None
    slot_level: int | None


_REGISTRY: dict[str, _LiveCombat] = {}


def _get_live(handle: CombatHandle) -> _LiveCombat:
    live = _REGISTRY.get(handle.handle_id)
    if live is None:
        raise UnknownHandleError(f"No live combat for handle {handle.handle_id!r}")
    return live


# Public read-only live-combat accessor. Host-side resolvers that run alongside
# the engine's dispatch consume this snapshot view of the live state the engine
# owns. Engine-internal callers use _get_live (the private _LiveCombat).
def get_live(handle: CombatHandle) -> LiveCombatView:
    return LiveCombatView.from_live(_get_live(handle))


def get_actor_active_effects(handle: CombatHandle, entity_id: str) -> tuple[ActiveEffect, ...]:
    """Read-only snapshot of one combatant's active effects.

    Public API for host-side resolvers (e.g. a host's FLEE dispatch path,
    `_handle_consult_codex_dispatch`) that run alongside the engine's own
    dispatch and need to see the same active_effects the engine resolvers
    consume internally. The engine is the single source of truth for in-
    combat effect state; this accessor lets the host fold it into a
    `DispatchContext` without re-implementing the registry.

    Returns an empty tuple if the handle has no live combat (caller
    should treat as out-of-combat — per spec, no effects apply).
    """
    live = _REGISTRY.get(handle.handle_id)
    if live is None:
        return ()
    return tuple(live.active_effects.get(entity_id, []))


def _current_actor(live: _LiveCombat) -> Combatant:
    return live.initiative[live.current_turn_index]


def _condition_names(c: Combatant) -> list[str]:
    """The combatant's active condition slugs (``is_condition_active`` resolves
    ``CONDITION_IMPLIES`` from the names, so implied conditions need not be
    materialised on ``Combatant.conditions``)."""
    return active_condition_names(c.conditions)


def _effective_speed(c: Combatant) -> int:
    """SRD 5.2 walking Speed under the combatant's conditions
    (``rules.conditions.project_speed``): 0 under a Speed-0 condition, else
    ``base_speed - 5 x exhaustion level``."""
    return project_speed(c.base_speed, _condition_names(c), exhaustion_level_of(c.conditions))


def _clamp_movement_budget(live: _LiveCombat, entity_id: str) -> None:
    """Re-project one combatant's ``movement_remaining`` after its conditions
    changed mid-turn: never above the effective Speed (a creature grappled
    mid-move loses the rest of its budget; the budget is never RAISED here —
    only the turn-start reset and Dash add movement)."""
    for idx, c in enumerate(live.initiative):
        if c.entity_id != entity_id:
            continue
        cap = _effective_speed(c)
        if c.movement_remaining > cap:
            live.initiative[idx] = c.model_copy(update={"movement_remaining": cap})
        break


#: SRD 5.2 Incapacitated — intents that spend NO action, Bonus Action or
#: Reaction and therefore stay legal: ending the turn, and plain movement
#: (Speed is governed separately — see ``_handle_move``'s speed gate).
_INCAPACITATED_ALLOWED_INTENTS: frozenset[str] = frozenset({"pass", "move"})


def _find_combatant(live: _LiveCombat, entity_id: str) -> Combatant | None:
    """Locate a combatant in the live initiative by entity id."""
    for c in live.initiative:
        if c.entity_id == entity_id:
            return c
    return None


def _fold_condition_onto_combatant(live: _LiveCombat, entity_id: str, condition: str) -> None:
    """Materialise a condition on **both** condition stores: the coarse
    ``live.active_conditions`` name set (what ``views.py`` shows the host and
    what the bridge rebuilds host storage from) and ``Combatant.conditions``,
    the typed list every projection reads (speed, incapacitated gate, save
    auto-fail, attack rows).

    Writing both here — rather than leaving ``active_conditions`` to each
    caller — is what makes this helper safe to call from OUTSIDE the
    ``ConditionApplied`` fold (``start_combat``'s 0-HP hydration is one such
    caller). A caller that set only one store would leave the two views
    disagreeing, which is exactly the class of bug the condition-immunity gates
    exist to prevent. The ``active_conditions`` write is deliberately BEFORE the
    idempotence guard, so it still lands for a combatant that is unknown or
    already carries the typed entry — preserving the pre-existing
    unconditional-write semantics of the ``ConditionApplied`` branch of
    ``_emit``.

    Idempotent per condition name; implied conditions are NOT materialised —
    ``is_condition_active`` resolves ``CONDITION_IMPLIES`` from the names.
    """
    live.active_conditions.setdefault(entity_id, set()).add(condition)
    c = _find_combatant(live, entity_id)
    if c is None or any(ac.condition == condition for ac in c.conditions):
        return
    new = [
        *c.conditions,
        ActiveCondition(
            condition=condition,
            source_entity_id="implied:event",
            scope="combat",
            applied_round=live.round_number,
        ),
    ]
    for idx, slot in enumerate(live.initiative):
        if slot.entity_id == entity_id:
            live.initiative[idx] = slot.model_copy(update={"conditions": new})
            break
    _clamp_movement_budget(live, entity_id)


def _strip_condition_from_combatant(live: _LiveCombat, entity_id: str, condition: str) -> None:
    """Drop the ``Combatant.conditions`` entries named ``condition`` after a
    ``ConditionRemoved``.

    Multi-source stacking guard (same rule ``_emit_apply_effect_expired``
    honours): an entry bridged from an effect that is STILL active is kept —
    ``_drop_concentration`` emits one ``ConditionRemoved`` per condition its
    dropped effect installed, and that must not clear a condition another live
    effect keeps imposing. When such an entry survives, the coarse
    ``live.active_conditions`` name (discarded by the ``_emit`` fold before we
    are called) is restored so both views agree.
    """
    c = _find_combatant(live, entity_id)
    if c is None or not any(ac.condition == condition for ac in c.conditions):
        return
    live_effect_ids = {eff.id for eff in live.active_effects.get(entity_id, [])}
    new = [
        ac
        for ac in c.conditions
        if ac.condition != condition
        or (ac.source_effect_id is not None and ac.source_effect_id in live_effect_ids)
    ]
    if len(new) == len(c.conditions):
        return
    for idx, slot in enumerate(live.initiative):
        if slot.entity_id == entity_id:
            live.initiative[idx] = slot.model_copy(update={"conditions": new})
            break
    if any(ac.condition == condition for ac in new):
        live.active_conditions.setdefault(entity_id, set()).add(condition)


def _drop_concentration(live: _LiveCombat, caster_id: str) -> None:
    """Cascade a concentration drop: ``ConcentrationDropped`` + per-target
    ``EffectExpired(reason=concentration_drop)`` + ``ConditionRemoved`` for
    every condition the dropped effect installed.

    Reads the persistent ``live.concentration_chain[caster_id]`` (the
    caster's owned-effects-by-name map) and
    ``live.conditions_by_effect[(target_id, effect_name)]`` (the
    persistent effect→condition bijection the orchestrator maintains in
    lieu of the transient ``ctx.parent_chain``). Clears both on
    completion + removes any matching ``repeat_save_on_turn_end`` specs
    so a paralyzed target whose source effect is gone stops rolling
    end-of-turn saves on the next turn.

    Idempotent against an empty chain — calling on a non-concentrating
    caster is a no-op.
    """
    entries = list(live.concentration_chain.get(caster_id) or ())
    if not entries:
        return
    for target_id, effect_id, origin in entries:
        # ``ConcentrationDropped.effect_name`` carries the effect *id*
        # (``effect:<slug>``) — the single representation the rest of the
        # lifecycle uses: ``concentration_chain`` / ``conditions_by_effect`` key
        # on ``effect.id`` and ``_build_hydration_payload`` projects
        # ``existing_concentration[caster]["effect_name"] = concentration_effect_id``
        # (the id). Resolving the human-readable ``ActiveEffect.name`` here only
        # when the effect was still in ``active_effects`` produced two divergent
        # representations from one emit site; the id is canonical.
        _emit(
            live,
            ConcentrationDropped(target_id=caster_id, effect_name=effect_id),
        )
        _emit(
            live,
            EffectExpired(
                target_id=target_id,
                effect_id=effect_id,
                origin=origin,
                reason="concentration_drop",
            ),
        )
        identity = (target_id, effect_id, origin)
        conditions = live.conditions_by_effect.pop(identity, [])
        for cond in conditions:
            # Cast back to the literal type expected by ConditionRemoved.
            _emit(
                live,
                ConditionRemoved(
                    target_id=target_id,
                    condition=cond,
                ),
            )
        # Drop any pending repeat-save spec keyed off this expired effect.
        live.repeat_save_on_turn_end.pop(identity, None)
    live.concentration_chain.pop(caster_id, None)
    # Clear ``Combatant.concentration_effect_id`` so subsequent hydration
    # payloads project an empty ``existing_concentration`` for this
    # caster. The ``_writeback_concentration`` path only fires when the
    # caster is the active turn-actor, but damage-driven drops happen on
    # arbitrary turns — clear inline so the canonical session-state field
    # stays consistent with the lifecycle event stream.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == caster_id and c.concentration_effect_id is not None:
            live.initiative[idx] = c.model_copy(update={"concentration_effect_id": None})
            break


def _handle_dash(live: _LiveCombat, current: Combatant, intent: PlayerIntent) -> None:
    """SRD §Combat — Dash: double the actor's movement budget for this turn.

    Adds ``base_speed`` to ``movement_remaining`` and consumes either the
    Action (default) or the Bonus Action (Rogue Cunning Action when
    ``intent.use_bonus_action`` is True). Dash does NOT advance the turn.

    Rejections raise ``IntentRejectedError("no_action_economy")``:
      * ``use_bonus_action=True`` while ``class_slug != "rogue"``
      * the chosen budget slot is already spent
    """
    actor_id = current.entity_id
    budget_consumed: Literal["action", "bonus_action"]
    if intent.use_bonus_action:
        if current.class_slug != "rogue":
            raise IntentRejectedError(
                "no_action_economy",
                f"actor_id={actor_id!r} cannot Dash as a Bonus Action "
                f"(class_slug={current.class_slug!r}, requires 'rogue')",
            )
        if not current.bonus_action_available:
            raise IntentRejectedError(
                "no_action_economy",
                f"actor_id={actor_id!r} has no Bonus Action remaining for Cunning Action Dash",
            )
        budget_consumed = "bonus_action"
    elif not current.action_available:
        raise IntentRejectedError(
            "no_action_economy",
            f"actor_id={actor_id!r} has no Action remaining for Dash",
        )
    else:
        budget_consumed = "action"

    # SRD 5.2 Dash adds the creature's (current) Speed; a Speed of 0 "can't increase".
    new_movement = current.movement_remaining + _effective_speed(current)
    budget_field = (
        "bonus_action_available" if budget_consumed == "bonus_action" else "action_available"
    )
    for idx, c in enumerate(live.initiative):
        if c.entity_id == actor_id:
            live.initiative[idx] = c.model_copy(
                update={budget_field: False, "movement_remaining": new_movement}
            )
            break
    _emit(
        live,
        DashTaken(
            actor_id=actor_id,
            doubled_movement_remaining=new_movement,
            budget_consumed=budget_consumed,
        ),
    )


def _handle_disengage(live: _LiveCombat, current: Combatant, intent: PlayerIntent) -> None:
    """SRD §Actions in Combat, Disengage — *"Your movement doesn't provoke
    Opportunity Attacks for the rest of the turn."*

    Consumes the Action (Disengage IS the Action — distinct from Dash's
    Action/Bonus-Action dual economy) and sets ``disengaging_this_turn`` so
    the monster-reactor opportunity-attack scan
    (``_fire_monster_opportunity_attacks_on_move``) suppresses AoOs for the
    rest of the turn. Does NOT advance the turn (mirrors Dash) so a
    same-turn Disengage→Move sequence works. Rejects with
    ``IntentRejectedError("no_action_economy")`` when the Action is already
    spent.
    """
    actor_id = current.entity_id
    if not current.action_available:
        raise IntentRejectedError(
            "no_action_economy",
            f"actor_id={actor_id!r} has no Action remaining for Disengage",
        )
    for idx, c in enumerate(live.initiative):
        if c.entity_id == actor_id:
            live.initiative[idx] = c.model_copy(
                update={"action_available": False, "disengaging_this_turn": True}
            )
            break
    _emit(live, IntentSubmitted(actor_id=actor_id, intent_type="disengage"))


# The move_mark seam must align with the effect the typed cast emits. The typed
# Hunter's Mark PassiveEffect is named "Hunter's Mark", so the resolver
# synthesizes ``ActiveEffect.id = effect:hunter's_mark`` (via
# ``_effect_id_from_name``). The concentration-chain lookup matches on this id, so
# move_mark's identity tuples must use the SAME id/name the original cast records.
_MOVE_MARK_EFFECT_NAME = "Hunter's Mark"
_MOVE_MARK_EFFECT_ID = "effect:hunter's_mark"
# The slug used only for the (now-empty) legacy loader range lookup below.
_MOVE_MARK_SPELL_SLUG = "hunters-mark"


async def _handle_move_mark(live: _LiveCombat, caster: Combatant, intent: PlayerIntent) -> None:
    """Retarget the caster's live Hunter's Mark to a new combatant.

    SRD §Hunter's Mark — bonus action affordance triggered when the
    currently-marked target drops to 0 HP. Does not consume a fresh
    spell slot; concentration is unbroken.

    Emits ``CastFailed(reason=target_invalid)`` on any of:
      - caster not concentrating on hunters-mark
      - no live mark on any previously-marked target
      - the previously-marked target is still alive
      - the new target is missing / dead / out of range
      - no bonus action available
    """
    if not caster.bonus_action_available:
        _emit(
            live,
            CastFailed(
                actor_id=caster.entity_id,
                spell_id=_MOVE_MARK_EFFECT_NAME,
                reason="no_action_economy",
            ),
        )
        return

    chain = live.concentration_chain.get(caster.entity_id) or []
    # Pull every prior-marked target carrying a hunters-mark identity
    # tuple from this caster's concentration chain.
    old_mark_entries = [
        (target_id, effect_id, origin)
        for target_id, effect_id, origin in chain
        if effect_id == _MOVE_MARK_EFFECT_ID
    ]
    old_targets = [target_id for target_id, _eid, _o in old_mark_entries]
    if not old_targets:
        _emit(
            live,
            CastFailed(
                actor_id=caster.entity_id,
                spell_id=_MOVE_MARK_EFFECT_NAME,
                reason="target_invalid",
            ),
        )
        return

    new_target_id = intent.target_id
    new_target = next(
        (c for c in live.initiative if c.entity_id == new_target_id),
        None,
    )
    if new_target_id is None or new_target is None or not new_target.is_alive:
        _emit(
            live,
            CastFailed(
                actor_id=caster.entity_id,
                spell_id=_MOVE_MARK_EFFECT_NAME,
                reason="target_invalid",
            ),
        )
        return

    # The SRD affordance is gated on the *previously*-marked target
    # being at 0 HP. Reject if all the prior targets are still alive
    # (rare-but-possible edge: multiple historical re-targets where the
    # current mark is still up; we require at least one prior to be
    # dead, since the SRD trigger is "drops to 0").
    prior_alive = [
        tid
        for tid in old_targets
        if any(c.entity_id == tid and c.is_alive for c in live.initiative)
    ]
    if prior_alive:
        _emit(
            live,
            CastFailed(
                actor_id=caster.entity_id,
                spell_id=_MOVE_MARK_EFFECT_NAME,
                reason="target_invalid",
            ),
        )
        return

    # SRD §Hunter's Mark range 90ft — same gate as the original cast. The
    # typed ``Spell.range`` carries the band; only feet-valued ranges gate over
    # the zone graph (self/touch/special are not a metric distance). A missing
    # spell or non-feet range disables the gate exactly as the old
    # ``.get("range_ft")`` None did. Mirrors the casting-time/range gating
    # pattern in submit_player_intent.
    move_mark_spell = get_lib_loader().get_spell(_MOVE_MARK_SPELL_SLUG)
    range_ft = (
        move_mark_spell.range.value
        if move_mark_spell is not None and move_mark_spell.range.units == SpellRangeUnits.FEET
        else None
    )
    if isinstance(range_ft, int) and range_ft > 0:
        caster_zone = live.actor_zone.get(caster.entity_id)
        target_zone = live.actor_zone.get(new_target_id)
        if (
            caster_zone is not None
            and target_zone is not None
            and not live.topology.within_range(caster_zone, target_zone, range_ft)
        ):
            _emit(
                live,
                CastFailed(
                    actor_id=caster.entity_id,
                    spell_id=_MOVE_MARK_EFFECT_NAME,
                    reason="out_of_range",
                ),
            )
            return

    # Consume the bonus action.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == caster.entity_id:
            live.initiative[idx] = c.model_copy(update={"bonus_action_available": False})
            break

    _emit(
        live,
        IntentSubmitted(
            actor_id=caster.entity_id,
            intent_type="move_mark",
            spell_id=_MOVE_MARK_EFFECT_NAME,
            target_id=new_target_id,
        ),
    )

    # Expire the old mark(s) on every prior target. Effect-lifecycle
    # discipline: state mutations flow through EffectExpired /
    # EffectApplied via _emit (the ws_projection picks these up and
    # forwards through effect_lifecycle to the host effect store).
    for old_target_id, old_effect_id, old_origin in old_mark_entries:
        _emit(
            live,
            EffectExpired(
                target_id=old_target_id,
                effect_id=old_effect_id,
                origin=old_origin,
                reason="moved",
            ),
        )

    # Re-target the persistent concentration chain so the rider-damage
    # projection finds the new marked target. Hunters-mark is the only
    # concentration effect this caster carries after move_mark; replace
    # any prior hunters-mark identity tuples wholesale.
    new_origin = f"cast:{_MOVE_MARK_EFFECT_NAME}:{caster.entity_id}"
    new_identity = (new_target_id, _MOVE_MARK_EFFECT_ID, new_origin)
    surviving_chain = [
        entry
        for entry in (live.concentration_chain.get(caster.entity_id) or [])
        if entry[1] != _MOVE_MARK_EFFECT_ID
    ]
    surviving_chain.append(new_identity)
    live.concentration_chain[caster.entity_id] = surviving_chain

    new_effect = ActiveEffect(
        id=_MOVE_MARK_EFFECT_ID,
        name=_MOVE_MARK_EFFECT_NAME,
        origin=new_origin,
        target_id=new_target_id,
        duration=ActiveEffectDuration(seconds=600),
        flags={"concentration": True},
    )
    _emit(
        live,
        EffectApplied(effect=new_effect),
    )

    # Bonus action — caster keeps the turn (SRD §Action Economy).


def _emit(live: _LiveCombat, event: CombatEvent) -> None:
    """Append to the event log, update outcome-tracking running state, then enqueue.

    Per Agent 03 (outcome-population): the orchestrator is the single source
    of truth for end-state derivation. Per-effect handlers emit canonical
    ``CombatEvent`` instances; this listener folds them into running totals
    so ``end_combat`` can project a populated ``CombatOutcome`` without
    re-reading per-effect state.

    Side-effect: when a non-PC combatant's running HP drops to ≤0 from a
    ``DamageApplied`` (and we have not already recorded its death), the
    orchestrator synthesizes a ``Death(reason="damage")`` event. This mirrors
    legacy combat semantics — monsters die immediately at 0 HP (SRD §Damage
    at 0 Hit Points); only PCs route through death saves.
    """
    live.event_log.append(event)
    live.event_queue.put_nowait(event)
    for listener in live.event_listeners:
        listener(event)

    if isinstance(event, TurnStarted):
        _emit_apply_turn_started(live, event)
        return

    if isinstance(event, DamageApplied):
        _emit_apply_damage(live, event)
        return

    if isinstance(event, HealingApplied):
        _emit_apply_healing(live, event)
        return

    if isinstance(event, TempHpApplied):
        _emit_apply_temp_hp(live, event)
        return

    if isinstance(event, ConditionApplied):
        # Both stores are written by the helper — see its docstring.
        _fold_condition_onto_combatant(live, event.target_id, event.condition)
        return

    if isinstance(event, ConditionRemoved):
        live.active_conditions.get(event.target_id, set()).discard(event.condition)
        _strip_condition_from_combatant(live, event.target_id, event.condition)
        return

    if isinstance(event, EffectApplied):
        _emit_apply_effect_applied(live, event)
        return

    if isinstance(event, EffectExpired):
        _emit_apply_effect_expired(live, event)
        return

    if isinstance(event, Death):
        if event.target_id in live.dead_ids:
            return
        _record_death(live, event, killer_id=live.current_actor_id)


def _emit_apply_turn_started(live: _LiveCombat, event: TurnStarted) -> None:
    """Fold a ``TurnStarted`` into running state: set the current actor and
    refresh that actor's per-turn Action / Bonus Action / Reaction / movement
    budgets on the initiative slot."""
    live.current_actor_id = event.actor_id
    # SRD §Action Economy — refresh the actor's per-turn budgets on the
    # start of their own turn. The reaction line ("You regain your
    # reaction at the start of your turn") and the Action/Bonus Action
    # budgets all reset here; consumption sites in submit_player_intent
    # (and, for reactions, future off-turn intent paths) are the only
    # writers that flip these False.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.actor_id:
            live.initiative[idx] = c.model_copy(
                update={
                    "action_available": True,
                    "bonus_action_available": True,
                    "reaction_available": True,
                    # SRD §Movement — the budget refreshes to the actor's
                    # EFFECTIVE Speed (Speed-0 conditions, Exhaustion) at the
                    # start of their turn. Per-MOVE-intent decrement is the
                    # only other writer; this is the only reset.
                    "movement_remaining": _effective_speed(c),
                    # SRD §Disengage — "for the rest of the turn"; this is
                    # the start of a NEW turn, so the suppression lapses.
                    "disengaging_this_turn": False,
                    # SRD §Sneak Attack, "Once per turn" — the per-turn cap
                    # clears at the start of the actor's own turn (symmetric
                    # with the action-economy resets above).
                    "sneak_attack_spent_this_turn": False,
                }
            )
            break


def _hook_expire_reaction_effects(live: _LiveCombat, actor_id: str | None) -> None:
    """``turn_start`` hook — SRD Shield / one-round reaction buffs.

    An effect this actor cast off-turn (via the reaction queue) with a
    round-scoped duration expires at the OWNER's own next turn start, rather
    than waiting for a ``TurnEnded`` that may be a full round later (see
    ``docs/dev/reaction-queue.md``, "Duration-fix semantics"). Before F3a this
    ran inline inside ``_emit_apply_turn_started``; it is now a registered
    lifecycle hook and therefore fires just after the ``TurnPhase(turn_start)``
    marker instead of during the ``TurnStarted`` fold — the relative order of
    the ``EffectExpired`` events against every pre-existing event is unchanged.
    """
    if actor_id is None:
        return
    pending_expiry = live.reaction_effects_pending_expiry.pop(actor_id, None)
    if not pending_expiry:
        return
    for target_id, effect_id, origin in pending_expiry:
        still_present = any(
            eff.id == effect_id and eff.origin == origin
            for eff in live.active_effects.get(target_id, [])
        )
        if still_present:
            _emit(
                live,
                EffectExpired(
                    effect_id=effect_id,
                    target_id=target_id,
                    origin=origin,
                    reason="duration",
                ),
            )


def _emit_apply_damage(live: _LiveCombat, event: DamageApplied) -> None:
    """Fold a ``DamageApplied`` into running state: temp-HP absorption, HP
    tracking + initiative sync, ``last_damaged_by`` attribution, the
    concentration CON save cascade, and non-PC death synthesis."""
    tracked = live.tracked_hp.get(event.target_id)
    if tracked is None:
        return
    # Temp HP absorbs first (SRD §Temporary Hit Points).
    temp = live.tracked_temp_hp.get(event.target_id, 0)
    remaining = event.amount
    if temp > 0:
        absorbed = min(temp, remaining)
        live.tracked_temp_hp[event.target_id] = temp - absorbed
        remaining -= absorbed
    new_hp = max(0, tracked - remaining)
    live.tracked_hp[event.target_id] = new_hp
    # Sync hp_current / temp_hp on the initiative slot so downstream
    # readers (monster gambit targeting, OA HP checks, hydration
    # passive projection) observe the post-damage state instead of the
    # opening snapshot. Combined into the same model_copy as the
    # ``last_damaged_by`` update below.
    new_temp_hp = live.tracked_temp_hp.get(event.target_id, 0)
    damager = live.current_actor_id
    update_payload: dict[str, Any] = {
        "hp_current": new_hp,
        "temp_hp": new_temp_hp,
    }
    # SRD §Hellish Rebuke — track the *creature that damaged you* on the
    # target combatant. ``current_actor_id`` is the canonical "who is
    # acting" (same source used for kill attribution below). Self-damage
    # (e.g. reaction damage back at the actor) is excluded so HR's
    # validation can't ping-pong.
    if damager and damager != event.target_id:
        update_payload["last_damaged_by"] = damager
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.target_id:
            live.initiative[idx] = c.model_copy(update=update_payload)
            break
    # SRD §Concentration on Damage — *"You must make a Constitution
    # saving throw … DC = 10 or half the damage taken, whichever is
    # higher. On a failed save, the spell ends."* If the damaged
    # combatant is concentrating on an effect (tracked in
    # ``concentration_chain``), roll the CON save and cascade on
    # failure. The save applies the concentrating creature's real CON
    # modifier + proficiency bonus (F1c, via ``actor_stats``) and goes
    # through the shared ``roll_d20_test`` primitive (F2c) with no
    # advantage source, so it is still a single draw.
    # Done BEFORE death synthesis so a dropped-conc + slain caster
    # still surface the cascade before the Death event.
    caster_chain = live.concentration_chain.get(event.target_id)
    if caster_chain:
        dc = max(10, event.amount // 2)
        concentrator = _find_combatant(live, event.target_id)
        # The ``else 0`` cannot fire in practice: ``concentration_chain`` is
        # only ever keyed by an entity that is in ``live.initiative``, and the
        # damage that got us here was applied to that same combatant. It stays
        # because ``_emit_apply_damage`` is contractually non-throwing — a
        # missing combatant degrades to an unmodified save rather than
        # aborting damage application mid-flight.
        # SRD 5.2 Exhaustion — the concentration CON save is a D20 Test.
        modifier = (
            save_modifier(concentrator, "con").total + d20_test_penalty(concentrator.conditions)
            if concentrator
            else 0
        )
        roll = roll_d20_test(live.rng, modifier, AdvantageSources())
        roll_total = roll.total
        succeeded = roll_total >= dc
        # TRANSITIONAL (F2c): the concentration check emits BOTH the
        # generic ``SaveRolled(ability="con")`` it has always emitted and
        # the specific ``ConcentrationCheck``. Hosts should migrate to the
        # latter; the duplicate ``SaveRolled`` is removed in v0.7.
        _emit(
            live,
            SaveRolled(
                target_id=event.target_id,
                ability="con",
                dc=dc,
                roll_total=roll_total,
                succeeded=succeeded,
                advantage=roll.mode,
                natural=roll.kept,
                modifier=roll.modifier,
                sources=list(roll.sources),
            ),
        )
        _emit(
            live,
            ConcentrationCheck(
                target_id=event.target_id,
                dc=dc,
                roll_total=roll_total,
                succeeded=succeeded,
                advantage=roll.mode,
                natural=roll.kept,
                modifier=roll.modifier,
                sources=list(roll.sources),
            ),
        )
        if not succeeded:
            _drop_concentration(live, event.target_id)
    if new_hp <= 0 and event.target_id not in live.dead_ids:
        if event.target_id in live.party_ids:
            _apply_zero_hp_to_character(live, event, hp_before=tracked, damage_after_temp=remaining)
        else:
            # SRD 5.2 "Monster Death" — a monster dies the instant it drops to
            # 0 HP. Recursion guard: _emit re-enters here for the Death, but
            # the dead_ids set blocks double-recording, and Death's only
            # running-state effect is to record the death.
            killer = live.current_actor_id
            death_event = Death(target_id=event.target_id, reason="damage")
            _record_death(live, death_event, killer_id=killer)
            live.event_log.append(death_event)
            live.event_queue.put_nowait(death_event)


def _apply_zero_hp_to_character(
    live: _LiveCombat, event: DamageApplied, *, hp_before: int, damage_after_temp: int
) -> None:
    """SRD 5.2 "Dropping to 0 Hit Points" for a Character.

    * Massive Damage: "When damage reduces a character to 0 Hit Points and
      damage remains, the character dies if the remainder equals or exceeds
      their Hit Point maximum." -> ``Death(reason="instant_kill")``.
    * Falling Unconscious: otherwise the character gains the Unconscious
      condition (``ConditionApplied``; the legacy ``Unconscious`` marker is
      emitted first for hosts that narrate it) and death saves begin on their
      next turn (``_maybe_roll_death_save``).
    * Damage at 0 Hit Points: "If you take any damage while you have 0 Hit
      Points, you suffer a Death Saving Throw failure. ... If the damage
      equals or exceeds your Hit Point maximum, you die." (The Critical-Hit
      two-failure clause needs a crit flag on ``DamageApplied`` — C15 seam.)
    """
    target = _find_combatant(live, event.target_id)
    if target is None:
        return
    hp_max = _hp_max_for(live, event.target_id)
    remainder = damage_after_temp - hp_before if hp_before > 0 else damage_after_temp
    if remainder >= hp_max:
        death_event = Death(target_id=event.target_id, reason="instant_kill")
        _record_death(live, death_event, killer_id=live.current_actor_id)
        live.event_log.append(death_event)
        live.event_queue.put_nowait(death_event)
        for idx, c in enumerate(live.initiative):
            if c.entity_id == event.target_id:
                live.initiative[idx] = c.model_copy(update={"is_alive": False})
                break
        return
    if hp_before > 0:
        if "unconscious" not in _condition_names(target):
            _emit(live, Unconscious(target_id=event.target_id))
            _emit(live, ConditionApplied(target_id=event.target_id, condition="unconscious"))
        return
    # SRD 5.2 charges a failure for damage TAKEN: an immune damage type (or a
    # hit fully absorbed by temp HP) reaches this fold with nothing left, and
    # ``activities/apply.py`` emits ``DamageApplied`` unconditionally.
    if damage_after_temp <= 0:
        return
    state = DeathSaveState.from_dict(target.death_saves) if target.death_saves else DeathSaveState()
    outcome = state.apply_damage_while_unconscious(False)
    update: dict[str, Any] = {"death_saves": state.to_dict()}
    if outcome == "dead":
        update["is_alive"] = False
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.target_id:
            live.initiative[idx] = c.model_copy(update=update)
            break
    if outcome == "dead":
        death_event = Death(target_id=event.target_id, reason="death_saves")
        _record_death(live, death_event, killer_id=live.current_actor_id)
        live.event_log.append(death_event)
        live.event_queue.put_nowait(death_event)


def _emit_apply_healing(live: _LiveCombat, event: HealingApplied) -> None:
    """Fold a ``HealingApplied`` into running state: HP tracking (capped at
    max), initiative sync, and the 0→positive revive (clear death saves +
    unconscious condition)."""
    tracked = live.tracked_hp.get(event.target_id)
    if tracked is None:
        return
    cap = _hp_max_for(live, event.target_id)
    new_hp = min(cap, tracked + event.amount)
    live.tracked_hp[event.target_id] = new_hp
    # SRD §Death Saves — "If a creature with 0 hit points regains any
    # hit points, it becomes conscious again." When tracked HP
    # transitions 0 → positive, flip ``is_alive`` back True, clear the
    # death-save counters, and drop the ``unconscious`` ActiveCondition
    # bridged by the dying state. HP sync runs unconditionally so
    # downstream readers (monster gambit targeting, hydration) observe
    # the post-heal state even when the heal didn't cross the 0->1
    # revive boundary.
    revived = tracked == 0 and new_hp > 0
    revived_ids: list[str] = []
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.target_id:
            heal_update: dict[str, Any] = {"hp_current": new_hp}
            if revived:
                heal_update["is_alive"] = True
                heal_update["death_saves"] = {}
                # SRD 5.2 Unconscious: "When this condition ends, you remain Prone."
                kept = [cond for cond in c.conditions if cond.condition != "unconscious"]
                if not any(cond.condition == "prone" for cond in kept):
                    kept.append(
                        ActiveCondition(
                            condition="prone",
                            source_entity_id="implied:revive",
                            scope="combat",
                            applied_round=live.round_number,
                        )
                    )
                heal_update["conditions"] = kept
                revived_ids.append(c.entity_id)
            live.initiative[idx] = c.model_copy(update=heal_update)
            break
    for entity_id in revived_ids:
        _emit(live, ConditionRemoved(target_id=entity_id, condition="unconscious"))
        _emit(live, ConditionApplied(target_id=entity_id, condition="prone"))


def _emit_apply_temp_hp(live: _LiveCombat, event: TempHpApplied) -> None:
    """Fold a ``TempHpApplied`` into running state: max-not-additive temp-HP
    tracking + initiative slot sync."""
    # SRD §Temporary Hit Points — new amount replaces existing if higher,
    # not additive (the legacy evaluator/Open5e canonical behavior).
    current = live.tracked_temp_hp.get(event.target_id, 0)
    new_temp = max(current, event.amount)
    live.tracked_temp_hp[event.target_id] = new_temp
    # Sync the initiative slot's temp_hp so downstream readers
    # (hydration, passive projection) observe the post-grant state.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.target_id:
            live.initiative[idx] = c.model_copy(update={"temp_hp": new_temp})
            break


def _emit_apply_effect_applied(live: _LiveCombat, event: EffectApplied) -> None:
    """Fold an ``EffectApplied`` into running state: track the active effect,
    union its imposed statuses into the target's conditions, and record
    concentration spell-slot expenditure for PCs."""
    applied = event.effect
    live.active_effects.setdefault(applied.target_id, []).append(applied)
    # Union the effect's imposed statuses into the combatant.conditions
    # list so passive projections (advantage/disadvantage on attack,
    # save, etc.) observe the new state immediately.
    target_combatant = _find_combatant(live, applied.target_id)
    if target_combatant is not None and applied.statuses:
        existing_slugs = {ac.condition for ac in target_combatant.conditions}
        new_conditions = list(target_combatant.conditions)
        dirty = False
        for status in applied.statuses:
            if status in existing_slugs:
                continue
            # SRD §Condition Immunity — an immune target never acquires the
            # condition. ``activities/effects.py::apply_activity_effects``
            # already SUPPRESSES the matching ``ConditionApplied``; without the
            # same gate here the status would still land on
            # ``Combatant.conditions`` and drive every C12 projection (the
            # Incapacitated action block, ``project_speed``, the STR/DEX save
            # auto-fail, the within-5-ft auto-crit) against a creature that
            # cannot have the condition — and would diverge from
            # ``live.active_conditions``, the store ``views.py`` shows the host.
            # Compared as a bare slug, matching the emit-gate's convention
            # (``passive_stats._CI_TOKEN_TO_CONDITION`` normalises the one
            # irregular Foundry token at projection time).
            if status in target_combatant.condition_immunities:
                _LOGGER.info(
                    "condition_immune_not_folded status=%s target_id=%s",
                    status,
                    applied.target_id,
                )
                continue
            # Derive source_entity_id from the origin tag when it
            # encodes one (e.g. "cast:bless:char:abc12"); otherwise
            # default to the canonical implied-source marker.
            source_entity_id = "implied:effect"
            new_conditions.append(
                ActiveCondition(
                    condition=status,
                    source_entity_id=source_entity_id,
                    scope="combat",
                    source_effect_id=applied.id,
                )
            )
            dirty = True
        if dirty:
            for idx, c in enumerate(live.initiative):
                if c.entity_id == applied.target_id:
                    live.initiative[idx] = c.model_copy(update={"conditions": new_conditions})
                    break
        # C12 — a newly applied Speed-0 / Exhaustion condition immediately
        # caps whatever movement the target had left this turn.
        _clamp_movement_budget(live, applied.target_id)
    # SRD spell-slot consumption: spell effects with concentration imply
    # a slot was spent. The slot level is not on the event today (follow-up
    # in the cutover); we record under a coarse "slots" label keyed by name.
    is_concentration = bool(applied.flags.get("concentration"))
    if is_concentration and applied.target_id in live.party_ids:
        bucket = live.expended_resources.setdefault(applied.target_id, {})
        bucket[applied.name] = bucket.get(applied.name, 0) + 1


def _emit_apply_effect_expired(live: _LiveCombat, event: EffectExpired) -> None:
    """Fold an ``EffectExpired`` into running state: pop the matching effect,
    then clear each status it imposed from both ``live.active_conditions`` and
    the target's conditions — but only if no OTHER active effect still imposes
    that status."""
    target_effects = live.active_effects.get(event.target_id, [])
    expired_effect: ActiveEffect | None = None
    for i, eff in enumerate(target_effects):
        if eff.id == event.effect_id and eff.origin == event.origin:
            expired_effect = target_effects.pop(i)
            break
    if expired_effect is not None and expired_effect.statuses:
        combatant = _find_combatant(live, event.target_id)
        remaining_effects = live.active_effects.get(event.target_id, [])
        # also clear the status from
        # live.active_conditions (orchestrator_bridge reads this when
        # mirroring combatant conditions back to host storage). Without this,
        # the projection re-attaches the expired status to session
        # state on the next mirror tick.
        active_cond_set = live.active_conditions.get(event.target_id)
        for status in expired_effect.statuses:
            # Only remove if no OTHER active effect still imposes the
            # same status (multiple sources stacking case).
            still_imposed = any(status in other.statuses for other in remaining_effects)
            if still_imposed:
                continue
            if active_cond_set is not None:
                active_cond_set.discard(status)
        if combatant is not None:
            new_conditions = list(combatant.conditions)
            dirty = False
            for status in expired_effect.statuses:
                still_imposed = any(status in other.statuses for other in remaining_effects)
                if still_imposed:
                    continue
                for idx, ac in enumerate(new_conditions):
                    if ac.condition == status:
                        new_conditions.pop(idx)
                        dirty = True
                        break
            if dirty:
                for idx, c in enumerate(live.initiative):
                    if c.entity_id == event.target_id:
                        live.initiative[idx] = c.model_copy(update={"conditions": new_conditions})
                        break


def _maybe_roll_death_save(live: _LiveCombat) -> None:
    """SRD §Dying — when a PC starts their turn at 0 HP, roll a death save.

    Called immediately after a ``TurnStarted`` is emitted for a PC. If the
    active combatant is a Character whose tracked HP is ≤ 0 and who is not
    yet recorded dead, roll one death save via
    ``roll_death_save``, emit the returned events
    through ``_emit`` (so ws_projection picks them up), and apply the
    returned ``Combatant`` mutation back into the live initiative slot.

    The death-save state machine in ``death_saves`` owns
    the success/failure counters; this orchestrator helper is the wiring
    that turns its outcome into emitted ``CombatEvent`` instances.
    """
    actor = _current_actor(live)
    if actor.entity_type != "Character":
        return
    if actor.entity_id in live.dead_ids:
        return
    tracked = live.tracked_hp.get(actor.entity_id, actor.hp_current)
    if tracked > 0:
        return
    # SRD §Death Saving Throws — stabilized PCs do not roll further death
    # saves until they take damage or are healed. The death-save helper's
    # docstring declares "not yet stable" a caller-owned precondition.
    if actor.death_saves and actor.death_saves.get("is_stable"):
        return
    # PC is at 0 HP — roll one death save.
    result = roll_death_save(actor, live.rng)
    for ev in result.events:
        _emit(live, ev)
    # Replace the combatant in initiative with the updated copy.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == actor.entity_id:
            live.initiative[idx] = result.combatant
            break
    # On crit_success (nat-20), HP resets to 1 — sync the tracker so the
    # PC can act on their next turn, and mirror the healing revive's condition
    # events so ``live.active_conditions`` (read by ``views.py`` and by effect
    # expiry) does not keep a stale ``unconscious``. SRD 5.2 Unconscious:
    # "When this condition ends, you remain Prone."
    if result.outcome == "critical_success":
        live.tracked_hp[actor.entity_id] = result.combatant.hp_current
        _emit(live, ConditionRemoved(target_id=actor.entity_id, condition="unconscious"))
        _emit(live, ConditionApplied(target_id=actor.entity_id, condition="prone"))


def _hp_max_for(live: _LiveCombat, entity_id: str) -> int:
    for c in live.initiative:
        if c.entity_id == entity_id:
            return c.hp_max or c.hp_current
    return 0


def _target_kind_for(live: _LiveCombat, entity_id: str) -> Literal["character", "npc", "monster"]:
    for c in live.initiative:
        if c.entity_id == entity_id:
            if c.entity_type == "Character":
                return "character"
            if c.entity_type == "NPC":
                return "npc"
            return "monster"
    return "monster"


def _record_death(live: _LiveCombat, event: Death, *, killer_id: str | None) -> None:
    """Append a DeathRecord and mark the entity dead.

    Killer attribution: the current turn's actor (set by ``TurnStarted``).
    For PC-on-monster damage that's the PC; for monster-on-monster (rare,
    e.g. AOE friendly-fire) it's still the current actor. Synthesized deaths
    from ``DamageApplied`` reuse this path.
    """
    if event.target_id in live.dead_ids:
        return
    live.dead_ids.add(event.target_id)
    live.deaths_recorded.append(
        DeathRecord(
            target_id=event.target_id,
            target_kind=_target_kind_for(live, event.target_id),
            location_id=live.scene_location_id,
            reason=event.reason,
            killer_id=killer_id if killer_id != event.target_id else None,
        )
    )


# ── Sidecar hydration (per-evaluation projection of session state) ──────────
#
# The per-effect handlers under ``app/combat/effects/*.py`` read sidecar
# surfaces hung off ``ctx.the host effect store`` — passive damage modifiers, save /
# check modifiers, existing temp-HP, counter pools, narrative text sink,
# spell book, available slots, active concentration, IEffect graph. The
# orchestrator projects from ``_LiveCombat`` (the in-memory combat state)
# and hands the payload to the active-effect projection immediately
# before invoking the evaluator. ``set_sidecar_state`` resets ``_text_sink``
# each call, so the per-evaluation narrative bag is fresh.
#
# Follow-ups (NOT in scope here; see PR body):
#   * passive damage / save / check modifiers projection requires reading
#     active effect modifiers, which is async (the host effect store). Today we
#     project empty dicts; handlers tolerate the absent state by returning
#     defaults (0 modifier, no resistances, no advantage/disadvantage).
#   * spell_book / available_slots / existing_concentration are not yet
#     carried on _LiveCombat. Project empty; spell-cast handler treats
#     empty as ``CastFailed(no_slot)`` — the safe behavior.
#   * counter pools (custom counters + spell-slot pool) likewise not yet
#     on session state. Empty pools mean ``UseCounter`` warns rather than
#     decrements.
#   * ieffect_graph is hydrated empty; the per-evaluation ``triggering_ieffect``
#     payload still flows through ``ctx.variables``.


# Foundry-native attack-bonus change keys (one per attack category). Bless /
# Bane carry all four with an identical signed-dice value; a creature attacks
# in exactly one category at a time, so the projection folds them once into the
# action-agnostic ``passive_to_hit_bonus`` (see the fold below).
_FOUNDRY_ATTACK_BONUS_KEYS = frozenset(
    {
        "system.bonuses.mwak.attack",
        "system.bonuses.msak.attack",
        "system.bonuses.rsak.attack",
        "system.bonuses.rwak.attack",
    }
)

# Foundry-native attack-CATEGORY damage-bonus change keys (Rage's Rage Damage
# rides ``mwak``; 's ranged analog rides ``rwak``; melee/ranged SPELL
# attack damage bonuses ride ``msak``/``rsak``). A creature attacks in exactly
# one category at a time (mirrors the to-hit fold above), so each key folds
# into its OWN category-scoped sidecar (never a shared bucket) — the consumer
# (``attack.py``) gates each on the swing's own melee/ranged + weapon/spell
# shape.
_FOUNDRY_DAMAGE_BONUS_KEY_TO_SIDECAR = {
    "system.bonuses.mwak.damage": "passive_melee_damage_bonus",
    "system.bonuses.rwak.damage": "passive_ranged_damage_bonus",
    "system.bonuses.msak.damage": "passive_melee_spell_damage_bonus",
    "system.bonuses.rsak.damage": "passive_ranged_spell_damage_bonus",
}

# Foundry-native flat/dice bonus to the CASTER's own spell save DC (e.g. a Rod
# of the Pact Keeper). Folds into the save-DC path (item 1's real
# spellcasting-ability formula) via ``build_context.py::_spell_dc_bonus``.
_FOUNDRY_SPELL_DC_BONUS_KEY = "system.bonuses.spell.dc"

# Foundry-native damage-RESISTANCE trait key on an ACTIVE effect (Rage's
# activation-gated ``dr``: bludgeoning/piercing/slashing while raging). Foundry
# ``mode=2`` here means "add this damage-type to the resistance SET", NOT "add to
# a numeric bucket" — so the value is a damage-type STRING, not a signed number.
# Handled at the very top of the change loop, BEFORE the numeric mode guard and
# the signed-string coercion, appending into the ``resistances`` sidecar list
# ``apply.py`` already reads ; see docs/dev/passive-projection.md).
_FOUNDRY_RESISTANCE_KEY = "system.traits.dr.value"

# F1d — the three D20-test bonus buckets that land on the per-actor CHECK sidecar
# (``check_modifiers[id]``) and the per-ability SAVE sidecar
# (``save_modifiers[id]["saves"]``). Both the engine's short internal key form and
# the Foundry-native ``system.bonuses.*`` / ``system.abilities.*`` form are
# accepted, mirroring the ``system.bonuses.abilities.save`` → ``save.bonus``
# aliasing above.
#
# ``abilities.check`` — a bonus to EVERY ability check (Guidance-shaped); it
# reaches skill checks too, because a skill check IS an ability check (SRD 5.2
# §Ability Checks).
_FOUNDRY_CHECK_BONUS_KEYS = frozenset({"abilities.check", "system.bonuses.abilities.check"})
# ``abilities.skill`` — a bonus to skill checks only.
_FOUNDRY_SKILL_BONUS_KEYS = frozenset({"abilities.skill", "system.bonuses.abilities.skill"})
# ``abilities.<ab>.save`` — a bonus to ONE ability's saving throw (the per-ability
# counterpart of the generic ``system.bonuses.abilities.save`` bucket, which stays
# on the action-agnostic ``passive_save_bonus`` dice sidecar).
_FOUNDRY_PER_ABILITY_SAVE_KEYS: dict[str, str] = {
    key: ability
    for ability in ("str", "dex", "con", "int", "wis", "cha")
    for key in (f"abilities.{ability}.save", f"system.abilities.{ability}.bonuses.save")
}


def _flat_change_value(value: bool | int | str) -> int | None:
    """The int a D20-test bonus change contributes, or ``None`` to skip it.

    ``check_modifiers[id]["ability_mods"/"skills"]`` and
    ``save_modifiers[id]["saves"]`` are RESOLVED INTEGER sidecars — the consumers
    (``activities/check.py::resolve_check``, ``activities/save.py``) add them to a
    natural d20 with no dice parser. So unlike the neighbouring
    ``passive_save_bonus`` / ``passive_to_hit_bonus`` sidecars (signed dice
    STRINGS their consumers roll), a dice-valued change on these buckets is
    dropped rather than folded: rolling it here would both mis-type the sidecar
    and consume RNG draws inside a projection that must stay draw-free
    (determinism contract). Plain integer strings ("2", "-1") still fold.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value.strip())
    except ValueError:
        return None


def _fold_d20_test_bonus(
    change: ActiveEffectChange,
    per_target_check: dict[str, Any],
    per_target_entry: dict[str, Any],
) -> None:
    """Fold one ``abilities.check`` / ``abilities.skill`` / ``abilities.<ab>.save``
    ``add`` change into the per-actor check + per-ability save sidecars.

    SRD 5.2 §Ability Checks — a skill check IS an ability check, so an
    ``abilities.check`` bonus reaches both the six ability-check modifiers and
    every proficient skill; ``abilities.skill`` reaches skills only.
    """
    amount = _flat_change_value(change.value)
    if amount is None:
        return
    key = change.key
    if key in _FOUNDRY_CHECK_BONUS_KEYS or key in _FOUNDRY_SKILL_BONUS_KEYS:
        skills = per_target_check.setdefault("skills", {})
        for skill in skills:
            skills[skill] += amount
        if key in _FOUNDRY_CHECK_BONUS_KEYS:
            ability_mods = per_target_check.setdefault("ability_mods", {})
            for ability in ability_mods:
                ability_mods[ability] += amount
        return
    ability = _FOUNDRY_PER_ABILITY_SAVE_KEYS[key]
    saves = per_target_entry.setdefault("saves", {})
    saves[ability] = saves.get(ability, 0) + amount


def _fold_active_effect_changes(
    active: Sequence[ActiveEffect],
    per_target_dmg: dict[str, Any],
    per_target_entry: dict[str, Any],
    per_target_check: dict[str, Any],
) -> bool:
    """Fold each live effect's Foundry-shaped ``changes`` into the per-target
    ``per_target_dmg`` (attack/damage sidecar), ``per_target_entry`` (save/ac
    sidecar) and ``per_target_check`` (ability/skill-check sidecar) dicts in
    place. Returns whether ``per_target_dmg`` was mutated
    (``dmg_dirty``) so the caller knows to re-store it.

    Pure projection over the passed dicts — no ``live`` mutation.
    """
    dmg_dirty = False
    for active_effect in active:
        # codex equipped enchantments and other
        # ActiveEffects carry mechanically-relevant `changes` entries
        # (Foundry-shaped: attack.roll.bonus / damage.bonus /
        # ac.bonus / save.bonus / save.<ability>.bonus). Fold their
        # int-valued mode=add changes into the engine's attack and
        # save sidecar surfaces so the resolvers see them on
        # monster-driven turns. Dice formulas ("1d4") pass through as
        # additive strings — the handler's existing parser already
        # handles them.
        #
        # Codex when an effect carries an
        # ``applicable_action_types`` restriction (e.g. a +1 weapon
        # tagged ["attack"]), the attack/damage sidecar is
        # action-type-agnostic and would silently buff spell
        # attacks too. Filter those buckets here: a weapon-tagged
        # enchantment's attack.roll.bonus / damage.bonus
        # changes don't reach the engine-sidecar path. The
        # host-side build_dispatch_context still applies them
        # correctly for player-dispatched attack actions; this
        # only means a monster-driven attack handler will not
        # see them — which is the conservative outcome because
        # the sidecar can't action-type-disambiguate.
        applicable = active_effect.flags.get("applicable_action_types")
        applicable_set: set[str] | None = None
        if isinstance(applicable, list) and applicable:
            applicable_set = {str(a).lower() for a in applicable}
        # Foundry models a "+1d4 to attack rolls" buff (Bless) /
        # "-1d4" debuff (Bane) as four sibling change keys —
        # ``system.bonuses.{mwak,msak,rsak,rwak}.attack`` — one per
        # attack category. A creature makes exactly one attack at a
        # time (it is melee XOR ranged, weapon XOR spell), so the
        # four siblings are mutually exclusive; folding all four into
        # the action-agnostic ``passive_to_hit_bonus`` would quadruple
        # the modifier. Fold the attack bonus once per effect.
        attack_bonus_folded = False
        for change in active_effect.changes:
            # Rage's ``system.traits.dr.value`` resistance change.
            # Foundry ``mode=2`` on this key means "add to the resistance SET"
            # (value is a damage-type string like ``"bludgeoning"``), not a
            # numeric bonus — so it must bypass BOTH the ``mode != "add"`` guard
            # and the signed-string coercion below. Append the cleaned type into
            # the ``resistances`` sidecar list ``apply.py`` unions with the
            # target's static resistances. Producer-only fix.
            if change.key == _FOUNDRY_RESISTANCE_KEY:
                dmg_type = str(change.value).strip().strip('"').strip()
                if dmg_type:
                    existing = per_target_dmg.get("resistances")
                    resist_list = list(existing) if existing else []
                    if dmg_type not in resist_list:
                        resist_list.append(dmg_type)
                    per_target_dmg["resistances"] = resist_list
                    dmg_dirty = True
                continue
            if change.mode != "add":
                continue
            # F1d — the three D20-test buckets land on INT sidecars, so they are
            # folded before the signed-dice-string coercion below.
            if (
                change.key in _FOUNDRY_CHECK_BONUS_KEYS
                or change.key in _FOUNDRY_SKILL_BONUS_KEYS
                or change.key in _FOUNDRY_PER_ABILITY_SAVE_KEYS
            ):
                _fold_d20_test_bonus(change, per_target_check, per_target_entry)
                continue
            val = change.value
            if isinstance(val, bool):
                continue
            if isinstance(val, int):
                signed_str = f"{val:+d}"
            elif isinstance(val, str) and val:
                signed_str = val if val.startswith("-") else f"+{val}"
            else:
                continue
            key = change.key
            # Route attack/damage by action-type tag. Effects
            # tagged ["attack"] (right-hand weapon enchantments)
            # write to a weapon-only sidecar surface
            # (passive_weapon_to_hit_bonus / passive_weapon_damage_bonus);
            # untagged effects (Bless, Bane) write to the
            # broadly-applicable passive_to_hit_bonus /
            # passive_damage_bonus that buff weapon AND spell
            # attacks alike. Defensive buckets (ac/save) ignore
            # the tag — they apply against any attacker. Codex
            # (corrects over-filter).
            weapon_only = applicable_set is not None and "attack" in applicable_set
            # Foundry-native attack-bonus keys (Bless/Bane carry the
            # four ``system.bonuses.{mwak,msak,rsak,rwak}.attack``
            # siblings). Normalize them to the internal
            # ``attack.roll.bonus`` surface, folding once per effect
            # (see ``attack_bonus_folded`` above).
            if key in _FOUNDRY_ATTACK_BONUS_KEYS:
                if attack_bonus_folded:
                    continue
                key = "attack.roll.bonus"
                attack_bonus_folded = True
            elif key in _FOUNDRY_DAMAGE_BONUS_KEY_TO_SIDECAR:
                # Rage's ``system.bonuses.mwak.damage`` (melee weapon attack
                # damage) and its ``rwak``/``msak``/``rsak`` siblings
                # 's ranged-weapon analog + melee/ranged spell-attack
                # damage). Each normalizes into its OWN category-scoped
                # damage-bonus sidecar; attack.py gates each on the swing's
                # own melee/ranged + weapon/spell shape.
                sidecar_field = _FOUNDRY_DAMAGE_BONUS_KEY_TO_SIDECAR[key]
                existing = per_target_dmg.get(sidecar_field)
                per_target_dmg[sidecar_field] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
                continue
            elif key == _FOUNDRY_SPELL_DC_BONUS_KEY:
                # A flat/dice bonus to the CASTER's own spell save DC (e.g. a
                # Rod of the Pact Keeper). Folds into the save-DC path
                # (build_context.py::_spell_dc_bonus) on top of the real
                # spellcasting-ability formula from item 1.
                existing = per_target_dmg.get("passive_spell_dc_bonus")
                per_target_dmg["passive_spell_dc_bonus"] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
                continue
            elif key == "system.bonuses.abilities.save":
                key = "save.bonus"
            elif key == "system.attributes.ac.bonus":
                # SRD Shield's own change key (Foundry-native path). Alias to
                # the existing "ac.bonus" branch below — not a new branch
                # the branch already existed, the key never matched).
                key = "ac.bonus"
            if key == "attack.roll.bonus":
                field = "passive_weapon_to_hit_bonus" if weapon_only else "passive_to_hit_bonus"
                existing = per_target_dmg.get(field)
                per_target_dmg[field] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
            elif key == "save.bonus":
                # project ONLY the
                # generic save.bonus into the action-agnostic
                # sidecar. Per-ability buckets (save.wisdom.bonus,
                # save.dexterity.bonus) would silently leak into
                # every saving throw via passive_save_bonus.
                # combat.saving_throw and resolve_check read
                # per-ability buckets directly from active_effects
                # via apply_changes_to_check so the
                # per-ability path is functional without the
                # sidecar projection.
                existing = per_target_entry.get("passive_save_bonus")
                per_target_entry["passive_save_bonus"] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
            elif key == "ac.bonus":
                existing = per_target_entry.get("passive_ac_bonus")
                per_target_entry["passive_ac_bonus"] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
            elif key == "damage.bonus":
                field = "passive_weapon_damage_bonus" if weapon_only else "passive_damage_bonus"
                existing = per_target_dmg.get(field)
                per_target_dmg[field] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
    return dmg_dirty


def _project_target_modifiers(
    c: Combatant,
    live: _LiveCombat,
    passive_damage_modifiers: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project one combatant's per-target save/check entries, folding SRD
    conditions, per-creature resistances/immunities, and active-effect changes.

    Mutates ``passive_damage_modifiers[c.entity_id]`` in place (the damage
    projection lands there directly). Returns ``(save_entry, check_entry)``;
    both are always present (F1d — every combatant carries the six ability-check
    modifiers, so the check entry is no longer condition-gated).
    """
    cond_names = [ac.condition for ac in c.conditions]
    damage_proj = project_passive_damage_modifiers(cond_names)
    save_proj = project_passive_save_modifiers(cond_names)
    check_proj = project_passive_check_modifiers(cond_names)
    # Merge per-creature damage_resistances / damage_immunities (from the
    # monster/character stat block) into the condition-derived projection.
    # SRD §Damage Resistance / §Damage Immunity — both sources are
    # additive (resistance + resistance does not stack per SRD, but
    # union-set membership reflects that correctly: the handler only
    # checks set membership, not count).
    if c.damage_resistances:
        merged_res = list(damage_proj.get("resistances", []) or [])
        for dt in c.damage_resistances:
            if dt not in merged_res:
                merged_res.append(dt)
        damage_proj["resistances"] = merged_res
    if c.damage_immunities:
        merged_imm = list(damage_proj.get("immunities", []) or [])
        for dt in c.damage_immunities:
            if dt not in merged_imm:
                merged_imm.append(dt)
        damage_proj["immunities"] = merged_imm
    # fold the creature's static damage vulnerabilities into the same
    # sidecar (the ONLY producer — vulnerability has no condition-derived
    # source). ``apply.py`` reads ``sidecar["vulnerabilities"]`` and doubles a
    # matching hit. Mirrors the resistances/immunities merge above exactly.
    if c.damage_vulnerabilities:
        merged_vuln = list(damage_proj.get("vulnerabilities", []) or [])
        for dt in c.damage_vulnerabilities:
            if dt not in merged_vuln:
                merged_vuln.append(dt)
        damage_proj["vulnerabilities"] = merged_vuln
    if any(damage_proj.values()):
        passive_damage_modifiers[c.entity_id] = dict(damage_proj)
    # Per-target ``saves`` ability-code → modifier projection. SRD 5.2
    # §Saving Throws: ``d20 + ability modifier + proficiency bonus (if
    # proficient in that save)``. All six abilities project through
    # ``actor_stats.save_modifier`` (F1c), which reads the hydrated
    # ability scores, ``save_proficiencies`` and the level/CR-derived
    # proficiency bonus off the ``Combatant``. save.py reads
    # ``entry["saves"][ability]`` on the lower-case ability key.
    per_target_entry: dict[str, Any] = dict(save_proj)
    per_target_entry["saves"] = {ab: save_modifier(c, ab).total for ab in ABILITY_CODES}

    # Active-effect projection: fold each live effect's Foundry-shaped
    # ``changes`` (Bless +1d4 save, Bane −1d4 save, +1 weapon, etc.) into
    # the per-target save_modifiers and attack-side
    # passive_damage_modifiers. The canonical store is
    # ``live.active_effects[entity_id]`` (event-log-derived). The typed
    # change-fold below is the sole source of these passive modifiers;
    # condition-derived save adv/dis comes from the SRD-condition
    # projection (``project_passive_save_modifiers``).
    # Per-actor ability/skill CHECK projection. SRD 5.2 §D20 Tests: an ability
    # check is ``d20 + ability modifier``, plus the proficiency bonus when the
    # actor is proficient in the skill used (doubled with Expertise). All six
    # ability modifiers and every proficient skill project through
    # ``actor_stats.check_modifier`` (F1a); the condition-derived adv/dis lists
    # (``passive_check_adv`` / ``passive_check_dis``) are MERGED, not replaced,
    # and ``disadvantage`` is their resolved boolean for consumers that want the
    # answer rather than the list. ``activities/check.py`` reads
    # ``entry["skills"][slug]`` first, falling back to
    # ``entry["ability_mods"][ability]``.
    check_entry: dict[str, Any] = dict(check_proj)
    check_entry["ability_mods"] = {ab: check_modifier(c, ab).total for ab in ABILITY_CODES}
    skills: dict[str, int] = {}
    for skill in c.skill_proficiencies:
        ability = skill_ability(skill)
        if ability is None:
            # Not an SRD skill slug (a tool proficiency, or a Foundry 3-letter
            # code): no governing ability to project, so the check falls back to
            # the ability modifier rather than guessing.
            continue
        skills[skill] = check_modifier(c, ability, skill).total
    check_entry["skills"] = skills
    check_entry["disadvantage"] = bool(check_proj.get("passive_check_dis"))

    active = live.active_effects.get(c.entity_id, [])
    if active:
        per_target_dmg = passive_damage_modifiers.get(c.entity_id, dict(damage_proj))
        dmg_dirty = _fold_active_effect_changes(
            active, per_target_dmg, per_target_entry, check_entry
        )
        if dmg_dirty:
            passive_damage_modifiers[c.entity_id] = per_target_dmg

    return per_target_entry, check_entry


def _project_caster_pools(
    live: _LiveCombat, caster: Combatant
) -> tuple[dict[Any, dict[str, Any]], dict[str, dict[str, int]], dict[str, Any]]:
    """Project the active caster's spell book, available slots, and counter
    pool. Pure — reads ``live`` and ``caster``, mutates nothing.

    Returns ``(spell_book, available_slots, counter_state)``.
    """
    spell_book: dict[Any, dict[str, Any]] = {}
    available_slots: dict[str, dict[str, int]] = {}
    counter_state: dict[str, Any] = {"custom_counters": {}, "spell_slots": {}}
    # Slots — handler keys by str(level); CharacterSpec carries int keys.
    slots = live.spell_slots_by_entity.get(caster.entity_id, {})
    if slots:
        slot_str_keyed = {str(level): int(count) for level, count in slots.items()}
        available_slots[caster.entity_id] = slot_str_keyed
        counter_state["spell_slots"] = dict(slot_str_keyed)
    # Spell book — resolve slugs through the bundled lib corpus. Unknown
    # slugs are silently dropped (the lib is the source of truth for what
    # can be cast). Post-cutover this maps to typed ``Spell`` instances; the
    # live ``cast``-delegation seam (``_build_cast_spell_book``) keys spells
    # by Foundry uuid off the resolved intent's own activities instead, so
    # this projection is not that seam's source — it is kept as a per-caster
    # known-spells view (narration/UI), separate from delegation.
    spells_known = live.spells_known_by_entity.get(caster.entity_id, [])
    if spells_known:
        lib_loader = get_lib_loader()
        caster_book: dict[str, Any] = {}
        for slug in spells_known:
            spell = lib_loader.get_spell(slug)
            if spell is not None:
                caster_book[slug] = spell
        if caster_book:
            spell_book[caster.entity_id] = caster_book
    # Custom counters — per-caster bag flowed into the single-caster
    # counter_state dict (the handler reads the global accessor).
    counters = live.custom_counters_by_entity.get(caster.entity_id, {})
    if counters:
        counter_state["custom_counters"] = {k: dict(v) for k, v in counters.items()}
    return spell_book, available_slots, counter_state


def _build_hydration_payload(live: _LiveCombat, caster: Combatant | None = None) -> dict[str, Any]:
    """Project ``the host effect store`` kwargs from live combat state.

    Two projection scopes:

    * **Per-combatant** (keyed by ``entity_id``): ``existing_temp_hp``,
      ``passive_damage_modifiers``, ``save_modifiers``, ``check_modifiers``,
      ``existing_concentration``. Derived from canonical
      ``Combatant`` fields (``temp_hp``,
      ``conditions``, ``concentration_effect_id``) plus the SRD-condition
      projection in ``conditions``.

    * **Per-caster** (single dict for the current evaluator turn): the
      ``_counter_state`` accessor is a single dict the handler reads as
      "the active caster's pool", so we project from ``caster``'s
      ``spell_slots`` and ``custom_counters`` only. ``spell_book`` and
      ``available_slots`` are also per-caster maps (``{caster_id: {...}}``)
      but the spell handler only ever reads the active caster's row, so
      we narrow projection to ``caster`` to avoid loading the SRD asset
      corpus for every combatant.

    Active-effect modifier projection (Bless +1d4, Bane −1d4, +1 weapon,
    etc.) is folded in from each combatant's
    ``active_effects`` row by reading the effects'
    Foundry-shaped ``changes`` directly (the typed change-fold). The
    int/dice ``add`` changes surface on the per-target ``save_modifiers`` /
    ``passive_damage_modifiers`` entries under ``passive_save_bonus`` /
    ``passive_to_hit_bonus`` / ``passive_ac_bonus`` / ``passive_damage_bonus``
    keys. Condition-derived save adv/dis come from the SRD-condition
    projection (``project_passive_save_modifiers`` →
    ``passive_save_adv`` / ``passive_save_dis``).

    ``caster=None`` (e.g. the start-of-combat hydration test path)
    projects per-combatant surfaces only; per-caster pools resolve to
    the canonical empty shape.
    """
    existing_temp_hp: dict[str, int] = {c.entity_id: int(c.temp_hp) for c in live.initiative}

    # ── Per-target passive modifiers (from SRD conditions) ──────────────────
    passive_damage_modifiers: dict[str, dict[str, Any]] = {}
    save_modifiers: dict[str, dict[str, Any]] = {}
    check_modifiers: dict[str, dict[str, Any]] = {}
    for c in live.initiative:
        per_target_entry, check_entry = _project_target_modifiers(c, live, passive_damage_modifiers)
        save_modifiers[c.entity_id] = per_target_entry
        check_modifiers[c.entity_id] = check_entry

    # ── C12 — SRD 5.2 Exhaustion ``-2 x level`` on every D20 Test, per entity ─
    # Only exhausted entities get a row, so an unexhausted combat hands the
    # resolvers an EMPTY dict and every d20 is byte-identical to before.
    d20_penalty: dict[str, int] = {}
    for c in live.initiative:
        penalty = d20_test_penalty(c.conditions)
        if penalty != 0:
            d20_penalty[c.entity_id] = penalty

    # ── Per-combatant concentration map ─────────────────────────────────────
    # SRD §Concentration — surface ``{effect_name, effect_id}`` per the
    # spell-handler contract (it reads ``effect_name``). The orchestrator
    # does not yet carry effect-name metadata on Combatant; we mirror
    # ``effect_id`` as the name so the single-conc check fires (matching
    # the stub-fixture behavior in ``test_orchestrator_hydration``).
    existing_concentration: dict[str, dict[str, Any]] = {}
    for c in live.initiative:
        if c.concentration_effect_id:
            existing_concentration[c.entity_id] = {
                "effect_id": c.concentration_effect_id,
                "effect_name": c.concentration_effect_id,
            }

    # ── Per-caster spell book + slots + counter pool ───────────────────────
    if caster is not None:
        spell_book, available_slots, counter_state = _project_caster_pools(live, caster)
    else:
        spell_book = {}
        available_slots = {}
        counter_state = {"custom_counters": {}, "spell_slots": {}}

    # IEffect parent/child graph: empty initially; the per-evaluation
    # ``triggering_ieffect`` flows through ``ctx.variables`` for now.
    ieffect_graph: dict[str, Any] = {}
    return {
        "passive_damage_modifiers": passive_damage_modifiers,
        "save_modifiers": save_modifiers,
        "check_modifiers": check_modifiers,
        "d20_test_penalty": d20_penalty,
        "existing_temp_hp": existing_temp_hp,
        "counter_state": counter_state,
        "spell_book": spell_book,
        "available_slots": available_slots,
        "existing_concentration": existing_concentration,
        "ieffect_graph": ieffect_graph,
    }


# ── AoE target-list expansion ───────────────────────────────────────────────

# SRD §Areas of Effect — spells with an explicit AoE radius/size project a
# multi-target candidate list (every creature in the targeted zone). The
# in-house orchestrator stores zone occupancy by entity_id (no positional
# coordinates), so the projection rule is: every alive combatant whose zone
# matches the named target's zone (or the caster's zone when no target is
# named) is in the candidate list.
#
# Selection signal: the TYPED activity's ``target.template`` measured-template
# block. Foundry tags every area spell with a measured template
# (``type``/``size``: Fireball=sphere/20, Burning Hands=cone/15, Sleep=sphere/5,
# Faerie Fire=cube/20) on the activity that resolves against creatures; a
# single-target spell (Sacred Flame, Cure Wounds, Magic Missile, Fire Bolt)
# carries no template. The lib's Foundry→canonical converter now surfaces this
# (inherited from ``system.target`` when the activity doesn't override it), so
# the typed activity alone is the AoE discriminator — no the legacy evaluator-wrapper read.

# Activity kinds that resolve against a creature target (vs. ``utility``, which
# is a self/zone-creating rider that affects no external creature). Only these
# carry a meaningful ``target.template`` signal for AoE-vs-single selection.
# Detect Thoughts' 30-ft detection radius lives on its ``utility`` activity, so
# excluding ``utility`` keeps that spell single-target — its creature-resolving
# ``save`` activity carries no template.
_TARGETING_ACTIVITY_KINDS = frozenset({"save", "damage", "attack", "heal"})


def _activity_has_measured_template(activity: Any) -> bool:
    """Return True if a creature-targeting activity carries a measured AoE
    template (a non-empty shape ``type``). Foundry's measured-template block is
    the area signal; an empty ``type`` means the activity resolves against a
    discrete target, not an area."""
    if activity.kind not in _TARGETING_ACTIVITY_KINDS:
        return False
    return bool(activity.target.template.type)


def _typed_spell_broadcasts(activities: Sequence[Any]) -> bool:
    """Return True if the TYPED activities broadcast to every creature in zone.

    The authoritative single-vs-area signal is a measured ``target.template``
    on the activity that resolves against creatures (see
    ``_activity_has_measured_template``):

    - a creature-targeting activity with a measured template (Fireball's
      ``save`` ⇒ sphere/20, Burning Hands ⇒ cone/15) ⇒ area broadcast.
    - no measured template on any creature-targeting activity (Sacred Flame,
      Cure Wounds, Magic Missile, Detect Thoughts' single-creature ``save``)
      ⇒ single target.

    Per-turn / per-creature repeat-save *riders* in genuine clouds
    (Stinking Cloud, Spirit Guardians) resolve their primary cast via a
    ``utility`` activity (excluded above), so they correctly resolve single at
    cast time and surface per-creature saves via the end-of-turn sweep.
    """
    return any(_activity_has_measured_template(a) for a in activities)


# C16 — Foundry ``target.template.type`` → engine template. ``origin`` says
# where the point of origin sits ("target": the named target's cell, else the
# caster's; "caster": always the caster's cell); ``include_origin`` follows
# SRD 5.2 §Areas of Effect (Sphere/Cylinder include it; Cone/Cube/Line and an
# Emanation — Foundry ``radius`` — do not "unless its creator decides
# otherwise", and the engine does not). ``wall`` (Wall of Fire's line of
# panels) has no single-origin geometry and falls back to the legacy list.
_AoeShape = Literal["sphere", "cone", "line", "cube", "cylinder"]
_AOE_TEMPLATE_TYPES: dict[str, tuple[_AoeShape, Literal["target", "caster"], bool]] = {
    "sphere": ("sphere", "target", True),
    "circle": ("sphere", "target", True),
    "cylinder": ("cylinder", "target", True),
    "radius": ("sphere", "caster", False),
    "cube": ("cube", "caster", False),
    "square": ("cube", "caster", False),
    "cone": ("cone", "caster", False),
    "line": ("line", "caster", False),
}


@dataclass(frozen=True)
class _AoeTemplate:
    shape: _AoeShape
    size_ft: int
    origin: Literal["target", "caster"]
    include_origin: bool


def _aoe_template(activities: Sequence[Any]) -> _AoeTemplate | None:
    """The first creature-targeting activity's measured template, or ``None``
    when the spell is single-target or its template has no grid geometry."""
    for activity in activities:
        if not _activity_has_measured_template(activity):
            continue
        template = activity.target.template
        mapped = _AOE_TEMPLATE_TYPES.get(template.type)
        try:
            size_ft = int(float(template.size))
        except (TypeError, ValueError):
            size_ft = 0
        if mapped is None or size_ft <= 0:
            _LOGGER.warning(
                "aoe_template_unsupported type=%s size=%r — "
                "falling back to zone-equality targeting",
                template.type,
                template.size,
            )
            return None
        shape, origin, include_origin = mapped
        return _AoeTemplate(
            shape=shape, size_ft=size_ft, origin=origin, include_origin=include_origin
        )
    return None


def _aoe_direction(
    live: _LiveCombat, caster_id: str, intent: PlayerIntent
) -> tuple[int, int] | None:
    """Aim vector for a directional template: the intent's ``direction``, else
    caster → named target (sign per axis); ``None`` when neither exists."""
    if intent.direction is not None:
        return intent.direction
    caster_cell = live.actor_zone.get(caster_id)
    target_cell = live.actor_zone.get(intent.target_id) if intent.target_id else None
    if caster_cell is None or target_cell is None or caster_cell == target_cell:
        return None
    cc, cr = parse_cell(caster_cell)
    tc, tr = parse_cell(target_cell)
    return ((tc > cc) - (tc < cc), (tr > cr) - (tr < cr))


# SRD 5.2 §Areas of Effect — a Cone, Line or Cube "extends in straight lines
# from a point of origin in a direction its creator chooses", so these three
# shapes cannot be placed without an aim vector. Sphere / Cylinder / Emanation
# are radial and need none.
_DIRECTIONAL_AOE_SHAPES: frozenset[str] = frozenset({"cone", "line", "cube"})


def _directional_aoe_lacks_direction(
    live: _LiveCombat, actor_id: str, intent: PlayerIntent, cast_spell: Spell | None
) -> bool:
    """True iff this cast is a grid AoE whose template needs an aim vector and
    none can be derived (no ``intent.direction``, no distinct named target).

    Reads the ``Spell`` already fetched for casting-time classification, so the
    gate costs no extra loader hit, and shares ``_aoe_template`` /
    ``_aoe_direction`` with ``_expand_aoe_target_list`` — one implementation,
    two call sites. Zone-graph combats never need a direction (the legacy
    zone-equality body ignores geometry), hence the backend guard.
    """
    if intent.intent_type != "cast_spell" or cast_spell is None:
        return False
    if not isinstance(live.topology, GridTopology):
        return False
    template = _aoe_template(cast_spell.activities)
    if template is None or template.shape not in _DIRECTIONAL_AOE_SHAPES:
        return False
    return _aoe_direction(live, actor_id, intent) is None


def _has_line_of_effect(topology: SpatialTopology, origin: str, cell: str) -> bool:
    """SRD 5.2 §Point of Origin — "If all straight lines extending from the
    point of origin to a location ... are blocked, that location isn't included
    ... To block a line, an obstruction must provide Total Cover." Walls and
    blocked cells block; creatures (half cover at most) never do, so no
    ``occupied_cells`` are passed."""
    return origin == cell or (
        topology.has_line_of_sight(origin, cell) and topology.cover_between(origin, cell) != "total"
    )


def _activities_bear_effects(activities: Sequence[Any]) -> bool:
    """True iff any activity carries effect riders (``effects[]``).

    A self-buff (Shield, Mirror Image, Disguise Self) hangs its mechanical
    payload as effect riders on a ``UtilityActivity``; with no riders there is
    nothing to apply to the caster and the self-target default is a no-op we
    should skip.
    """
    return any(getattr(a, "effects", None) for a in activities)


def _activities_target_self(activities: Sequence[Any]) -> bool:
    """True iff every activity's ``target.affects.type`` is ``"self"``.

    A class-feature invocation (Rage's self-buff, Second Wind's self-heal) names
    no foe, so the named-target filter yields ``[]`` and the rider/heal would
    apply to nobody. The typed ``target.affects.type == "self"`` is the
    authoritative self-target signal (mirrors the spell self-target default).
    """
    return all(
        getattr(getattr(a.target, "affects", None), "type", None) == "self" for a in activities
    )


def _spell_is_self_or_targetless(cast_spell: Spell | None, named_target_id: str | None) -> bool:
    """True iff a cast resolves onto the caster rather than a named foe.

    Two shapes qualify: a spell whose typed ``range.units`` is ``self``/``touch``
    (Shield, Mirror Image, Disguise Self), OR any cast that named no target and
    is not an AoE (the AoE branch sets its own target list by zone expansion).
    """
    if cast_spell is not None and cast_spell.range.units in (
        SpellRangeUnits.SELF,
        SpellRangeUnits.TOUCH,
    ):
        return True
    return named_target_id is None


def _aoe_cover_origin(
    live: _LiveCombat,
    caster_id: str,
    intent: PlayerIntent,
    activities: Sequence[Any],
) -> str | None:
    """The cell an AoE's template is centred on — its SRD 5.2 point of origin —
    or ``None`` when this cast is not a grid AoE (no grid backend, no mappable
    template, or no tracked caster cell).

    Single source of truth for two consumers that must agree: the template walk
    in ``_expand_aoe_target_list`` (which cells are in the area, and which have
    line of effect) and the cover sweep in ``_target_cover_map`` (§Cover — "if
    a target is behind an area of effect's point of origin, measure cover from
    that point"). A ``target``-origin template (Fireball) centres on the named
    target's cell; a ``caster``-origin one (Burning Hands, Thunderwave) on the
    caster's.
    """
    if not isinstance(live.topology, GridTopology):
        return None
    caster_cell = live.actor_zone.get(caster_id)
    if caster_cell is None:
        return None
    template = _aoe_template(activities)
    if template is None:
        return None
    if template.origin == "target" and intent.target_id:
        return live.actor_zone.get(intent.target_id, caster_cell)
    return caster_cell


def _expand_aoe_target_list(
    live: _LiveCombat,
    caster: Combatant,
    intent: PlayerIntent,
    activities: Sequence[Any],
) -> list[Combatant]:
    """Build the AoE candidate list (SRD 5.2 §Areas of Effect).

    Grid backend: resolve the typed template (``_aoe_template``), place its
    point of origin, aim it, enumerate ``cells_in_template``, drop every cell
    without line of effect from the origin, and return every alive combatant
    standing in a surviving cell (allies and the caster included when the
    geometry says so — Fireball hits the caster in its own radius).

    Zone graph (legacy, removed with the backend in 0.7): every alive
    combatant whose zone equals the anchor zone (the named target's, else the
    caster's).
    """
    named_target_id = intent.target_id
    alive = [c for c in live.initiative if c.is_alive and c.entity_id not in live.dead_ids]
    topology = live.topology
    caster_cell = live.actor_zone.get(caster.entity_id)
    # ``_aoe_template`` is only consulted on the grid: it logs
    # ``aoe_template_unsupported`` for a template it cannot map, and the zone
    # graph never reads geometry, so calling it there would warn for nothing.
    if isinstance(topology, GridTopology) and caster_cell is not None:
        template = _aoe_template(activities)
        if template is not None:
            origin = _aoe_cover_origin(live, caster.entity_id, intent, activities) or caster_cell
            direction: tuple[int, int] | None = None
            if template.shape in _DIRECTIONAL_AOE_SHAPES:
                direction = _aoe_direction(live, caster.entity_id, intent)
                if direction is None:
                    # Unreachable on the live cast path: the pre-slot
                    # ``_directional_aoe_lacks_direction`` gate in
                    # ``submit_player_intent`` already emitted
                    # ``CastFailed(target_invalid)`` and returned before any
                    # slot or action was spent. Kept as a defensive floor so an
                    # unaimed template can never reach ``cells_in_template``,
                    # which raises.
                    return []
            cells = topology.cells_in_template(
                origin, template.shape, template.size_ft, direction=direction
            )
            area = {c for c in cells if _has_line_of_effect(topology, origin, c)}
            if not template.include_origin:
                area.discard(origin)
            return [c for c in alive if live.actor_zone.get(c.entity_id) in area]
    # zone graph: legacy behaviour until removal in 0.7
    anchor_zone: str | None = None
    if named_target_id:
        anchor_zone = live.actor_zone.get(named_target_id)
    if anchor_zone is None:
        anchor_zone = caster_cell
    if anchor_zone is None:
        # No zone info — fall back to caster + named target only.
        return [c for c in live.initiative if c.entity_id in {caster.entity_id, named_target_id}]
    return [c for c in alive if live.actor_zone.get(c.entity_id) == anchor_zone]


# ── Concentration writeback ─────────────────────────────────────────────────


def _writeback_concentration(live: _LiveCombat, caster: Combatant, pre_event_count: int) -> None:
    """Project post-evaluation concentration events onto the caster's Combatant.

    Per SRD §Concentration the caster carries at most one concentration
    effect at a time. When the evaluator emits ``EffectApplied(is_concentration=True)``
    during this turn, the caster's ``concentration_effect_id`` must be
    updated so the next ``_build_hydration_payload`` projects the existing
    concentration onto the sidecar (the ieffect2 handler's single-conc
    rule reads it). Symmetric: when ``ConcentrationDropped`` or an
    ``EffectExpired`` for the caster's tracked effect fires, clear it.

    ``EffectApplied`` does not carry the caster's id; we rely on the
    canonical pairing — the *current actor* (active caster on this turn)
    is the one who emits the concentration spell. Events on prior turns
    are ignored via ``pre_event_count`` slicing.
    """
    new_events = live.event_log[pre_event_count:]
    tracked_name: str | None = None
    for ev in new_events:
        if isinstance(ev, EffectApplied) and ev.effect.flags.get("concentration"):
            # The active caster is the one who initiated this concentration
            # spell. ``EffectApplied`` carries ``target_id`` on the
            # embedded ActiveEffect (the affected combatant) but not the
            # source caster — pairing by "active turn" is the canonical
            # projection here.
            tracked_name = ev.effect.id
        elif isinstance(ev, ConcentrationDropped) and ev.target_id == caster.entity_id:
            tracked_name = None
    # Find caster's index in initiative and update in place. ``Combatant``
    # is a pydantic model; ``model_copy`` returns a new instance.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == caster.entity_id:
            if tracked_name is not None and c.concentration_effect_id != tracked_name:
                live.initiative[idx] = c.model_copy(
                    update={"concentration_effect_id": tracked_name}
                )
            elif tracked_name is None and c.concentration_effect_id is not None:
                # Only clear if a ConcentrationDropped was observed this turn —
                # not when no conc events fired at all (the absent EffectApplied
                # case is "nothing happened", not "concentration dropped").
                cleared = any(
                    isinstance(ev, ConcentrationDropped) and ev.target_id == caster.entity_id
                    for ev in new_events
                )
                if cleared:
                    live.initiative[idx] = c.model_copy(update={"concentration_effect_id": None})
            break


# ── Persistent IEffect-graph lifecycle linkage ──────────────────────────────


def _record_effect_lifecycle_links(
    live: _LiveCombat, caster: Combatant, pre_event_count: int
) -> None:
    """Project this turn's effect-application events into persistent lifecycle state.

    The ieffect2 handler's ``ctx.parent_chain`` is per-evaluation; the
    cross-turn cascade walks (concentration drop → expire dependent
    effects → remove sourced conditions) need a persistent index. We
    walk the slice of ``live.event_log`` produced by this evaluator
    call and fold three pieces of structure into ``_LiveCombat``:

    * ``concentration_chain[caster_id][effect_name] = [target_ids]`` —
      every ``EffectApplied(is_concentration=True)`` emitted while
      ``caster`` was the active actor is owned by that caster. The
      damage-driven concentration save in ``_emit`` consults this map
      to decide whether to roll a save; ``_drop_concentration`` walks
      it to cascade EffectExpired across every target.

    * ``conditions_by_effect[(target_id, effect_name)] = [conditions]``
      — every ``ConditionApplied`` that lands on a target within the
      same evaluator call as an ``EffectApplied`` for that target is
      attributed to that effect. SRD §Hold Person installs the
      paralyzed condition as a structured passive on the ieffect2 node,
      so the canonical pairing in the event stream is *(EffectApplied,
      ConditionApplied)* on the same target inside the save's fail
      branch. The orchestrator does not need IR-level parent links to
      observe this — the emit order is the load-bearing signal.

    * ``repeat_save_on_turn_end[target_id]`` — when a save just failed
      against the same target inside the same evaluator call and a
      condition was then applied with a concurrent
      ``EffectApplied(is_concentration=True)``, the target rolls a
      repeat save at the end of each of its turns (SRD §Hold Person:
      *"At the end of each of its turns, the target repeats the save,
      ending the spell on itself on a success."*). We record the
      ability + DC from the original failed save so the end-of-turn
      hook can re-roll without re-parsing the IR.

    Linkage scope: only events emitted by THIS evaluator call (the
    ``pre_event_count`` slice). Events from prior turns have already
    been folded in; re-walking them would double-count.
    """
    new_events = live.event_log[pre_event_count:]
    # Per-target tracking within this slice.
    last_failed_save_by_target: dict[str, SaveRolled] = {}
    last_effect_by_target: dict[str, ActiveEffect] = {}
    for ev in new_events:
        if isinstance(ev, SaveRolled) and not ev.succeeded:
            last_failed_save_by_target[ev.target_id] = ev
            continue
        if isinstance(ev, EffectApplied):
            applied = ev.effect
            if applied.flags.get("concentration"):
                chain = live.concentration_chain.setdefault(caster.entity_id, [])
                identity = (applied.target_id, applied.id, applied.origin)
                if identity not in chain:
                    chain.append(identity)
            last_effect_by_target[applied.target_id] = applied
            continue
        if isinstance(ev, ConditionApplied):
            eff = last_effect_by_target.get(ev.target_id)
            if eff is None:
                continue
            key = (ev.target_id, eff.id, eff.origin)
            live.conditions_by_effect.setdefault(key, []).append(ev.condition)
            failed_save = last_failed_save_by_target.get(ev.target_id)
            # Repeat-save lineage requires:
            #   - a same-evaluation failed save on this target (the
            #     spell's gating save, which the SRD repeat-save flow
            #     mirrors at end-of-turn),
            #   - the concurrent EffectApplied is a concentration effect
            #     (SRD §Hold Person / §Hold Monster / §Dominate Person are
            #     all concentration spells with the repeat-save clause).
            # Non-concentration condition applies (e.g. ghoul claw →
            # paralyzed, which is SRD instantaneous and has no repeat-save
            # mechanic) are skipped.
            if failed_save is not None and eff.flags.get("concentration"):
                live.repeat_save_on_turn_end.setdefault(key, []).append(
                    {
                        "ability": failed_save.ability,
                        "dc": failed_save.dc,
                        "effect_name": eff.name,
                        "condition": ev.condition,
                        "caster_id": caster.entity_id,
                    }
                )
            continue


def _hook_run_end_of_turn_saves(live: _LiveCombat, actor_id: str | None) -> None:
    """``turn_end`` hook — adapt ``_run_end_of_turn_saves`` to ``TurnHook``."""
    if actor_id is None:
        return
    _run_end_of_turn_saves(live, actor_id)


def _hook_tick_durations(live: _LiveCombat, actor_id: str | None) -> None:
    """``turn_end`` hook — adapt ``_tick_durations_at_turn_end`` to ``TurnHook``."""
    if actor_id is None:
        return
    _tick_durations_at_turn_end(live, actor_id)


def _hook_expire_timed_effects(live: _LiveCombat, actor_id: str | None) -> None:
    """``turn_end`` hook — adapt ``_expire_timed_effects_at_turn_end`` to ``TurnHook``."""
    if actor_id is None:
        return
    _expire_timed_effects_at_turn_end(live, actor_id)


def _register_default_turn_hooks(live: _LiveCombat) -> None:
    """Register the engine's built-in turn-boundary hooks on ``live``.

    Registration order IS execution order. The two F3a hooks (duration tick,
    reaction-effect expiry) reproduce exactly where each used to run inline, so
    seeded replays are byte-identical apart from the new ``TurnPhase`` markers.
    F3b's ``engine:timed-effect-expiry`` is appended AFTER the round tick, so an
    effect carrying both a ``rounds`` counter and a ``seconds`` duration is
    resolved by the ``rounds`` counter first and the seconds branch then sees
    ``rounds is not None`` and stands down ("rounds wins" — see
    ``_expire_timed_effects_at_turn_end``).
    ``engine:repeat-save`` is registered FIRST among the ``turn_end`` hooks: the
    SRD repeat save (Hold Person / Hold Monster / Dominate Person) must resolve
    while its source effect is still live, so it runs before
    ``engine:duration-tick`` could expire that effect on the same boundary.
    Before F3a-follow-up this ran as a hand-placed call at two sites *above* the
    ``TurnPhase(turn_end)`` marker, which also let a bonus action trigger a
    second repeat save in the same turn; as a hook it runs exactly once per turn
    end, inside the phase it belongs to.
    Later clusters (ongoing damage, regeneration, recharge, legendary reset)
    append here rather than editing the advance path.
    """
    live.lifecycle.register("turn_end", _hook_run_end_of_turn_saves, key="engine:repeat-save")
    live.lifecycle.register("turn_end", _hook_tick_durations, key="engine:duration-tick")
    live.lifecycle.register(
        "turn_end", _hook_expire_timed_effects, key="engine:timed-effect-expiry"
    )
    live.lifecycle.register(
        "turn_start", _hook_expire_reaction_effects, key="engine:reaction-effect-expiry"
    )


def _tick_durations_at_turn_end(live: _LiveCombat, actor_id: str) -> None:
    """Decrement ``ActiveEffect.duration.rounds`` on the actor's owned
    maintained effects at turn-end and emit ``EffectExpired``
    (reason=duration) when a count reaches zero.

    SRD §Combat: spells with a "rounds" duration count down once per
    round, at the **caster's** turn-end. Bless cast on three allies
    should still last 10 rounds total — not 10/3 ≈ 3 — so the tick is
    keyed to the caster, not each affected target. Effects without an
    active rounds counter (``rounds is None`` — permanent / item-
    equipped / non-rounds duration) skip the tick.

    Caster identification: effect ``origin`` follows the convention
    ``"cast:<slug>:<caster_id>"`` for spells; ``"item:<item_id>:<id>"``
    for equipped items. Only the cast-origin effects tick here, only
    when their caster's turn ends.

    For non-cast-origin effects with rounds (e.g. environmental traps
    or a future seed pattern that doesn't carry a caster), fall back to
    the target-turn-end tick so they still expire eventually.

    introduced the tick; refined it to the caster-keyed semantics. Pre-Phase-6 the host's
    ``_sweep_effects`` already tracked sources separately for this
    case; this restores the same shape.

    Pure on ``live.active_effects``: ``_emit`` consumes the
    ``EffectExpired`` we emit and removes the effect from the
    registry. We snapshot identities first so in-loop emissions don't
    invalidate the iteration.
    """
    to_expire: list[tuple[str, str, str]] = []
    # Walk every (target_id, effect) pair. Tick when the caster (parsed
    # from origin) matches the actor whose turn ended; for orphan
    # origins (no "cast:" prefix), tick at the target's turn-end as the
    # fallback.
    for target_id, target_effects in list(live.active_effects.items()):
        for idx, eff in enumerate(list(target_effects)):
            if eff.duration.rounds is None:
                continue
            # Concentration-gated effects (Bless, Bane, Faerie Fire, Hold
            # Person, Hunter's Mark) live and die with the caster's
            # concentration, not a round counter — SRD §Concentration. The
            # Foundry packs carry a ``duration.rounds`` purely for the
            # turn-tracker display (and some packs ship a too-short value,
            # e.g. Bane's ``rounds: 1``), so ticking it would expire the
            # spell prematurely. The concentration cascade (_drop_concentration
            # on a failed CON save / caster death) and the per-turn repeat
            # save own these effects' lifetimes.
            if eff.flags.get("concentration"):
                continue
            # Caster-keyed, with a target-keyed fallback for item /
            # environment / non-spell origins so they still expire (see
            # ``_duration_tick_matches_actor`` — F3b extracted this predicate
            # verbatim so the seconds branch keys off the same owner).
            if not _duration_tick_matches_actor(
                origin=eff.origin or "", target_id=target_id, actor_id=actor_id
            ):
                continue
            new_rounds = eff.duration.rounds - 1
            if new_rounds > 0:
                # Immutable replacement: previously-emitted EffectApplied
                # events hold references to the same ActiveEffect instance,
                # so in-place mutation would silently mutate captured event
                # payloads. Replace the slot in active_effects with a fresh
                # copy via model_copy and leave the original intact.
                new_duration = eff.duration.model_copy(update={"rounds": new_rounds})
                new_eff = eff.model_copy(update={"duration": new_duration})
                target_effects[idx] = new_eff
                continue
            to_expire.append((target_id, eff.id, eff.origin))

    for target_id, effect_id, origin in to_expire:
        _emit(
            live,
            EffectExpired(
                effect_id=effect_id,
                target_id=target_id,
                origin=origin,
                reason="duration",
            ),
        )


#: SRD 5.2 §Duration — "a round represents about 6 seconds in the game world".
#: The conversion factor for ``ActiveEffectDuration.seconds`` -> rounds.
_SECONDS_PER_ROUND = 6


def _duration_tick_matches_actor(*, origin: str, target_id: str, actor_id: str) -> bool:
    """Whether a round-scoped duration ticks now, at ``actor_id``'s turn end.

    Effect ``origin`` follows ``"cast:<slug>:<caster_id>"`` for spells and
    ``"item:<item_id>:<id>"`` for equipped items. Cast-origin effects tick at
    the CASTER's turn end (SRD §Combat: Bless on three allies still lasts ten
    rounds, not ten thirds). Everything else — item, environment, or a seeded
    effect with no caster in its origin — falls back to the TARGET's turn end
    so it still expires eventually.
    """
    if origin.startswith("cast:"):
        parts = origin.split(":", 2)
        caster_id = parts[2] if len(parts) == 3 else ""
        return caster_id == actor_id
    return target_id == actor_id


def _effect_applied_during_current_turn(
    live: _LiveCombat, actor_id: str, identity: tuple[str, str, str]
) -> bool:
    """Was ``identity`` applied during the turn of ``actor_id`` that is ending?

    Read-only over ``live.event_log``: find the most recent
    ``TurnStarted(actor_id)`` (the turn now ending, since this is only called
    from a ``turn_end`` hook) and look for a matching ``EffectApplied`` after
    it. This is how "until the end of your NEXT turn" gets its one-turn grace
    without a side table — an effect applied on your own turn survives that
    turn's end; one applied on somebody else's turn dies at your very next
    one. Effects seeded into ``start_combat`` emit no ``EffectApplied`` and so
    read as "not applied this turn", which is the right answer for them.
    """
    target_id, effect_id, origin = identity
    last_start = -1
    for i in range(len(live.event_log) - 1, -1, -1):
        ev = live.event_log[i]
        if isinstance(ev, TurnStarted) and ev.actor_id == actor_id:
            last_start = i
            break
    if last_start < 0:
        return False
    return any(
        isinstance(ev, EffectApplied)
        and ev.effect.target_id == target_id
        and ev.effect.id == effect_id
        and ev.effect.origin == origin
        for ev in live.event_log[last_start + 1 :]
    )


def _expire_timed_effects_at_turn_end(live: _LiveCombat, actor_id: str) -> None:
    """F3b — the three duration shapes ``_tick_durations_at_turn_end`` does not own.

    Registered as the ``engine:timed-effect-expiry`` ``turn_end`` hook, right
    after the ``rounds`` tick. Every branch emits
    ``EffectExpired(reason="duration")`` and, like the round tick, snapshots the
    identities first so in-loop ``_emit`` calls (which pop the effect out of
    ``live.active_effects``) cannot invalidate the iteration. No RNG.

    ``turns`` — SRD durations counted in the *subject's* turns ("until the end
    of its next turn", Foundry's ``duration.turns``). Decremented at the
    TARGET's own turn end, not the caster's, and independent of any ``rounds``
    counter: whichever counter reaches zero first expires the effect.

    ``seconds`` — SRD §Duration puts a round at 6 seconds, so a seconds-valued
    duration is ``ceil(seconds / 6)`` rounds ticked exactly like ``rounds``
    (caster-keyed, via ``_duration_tick_matches_actor``). The derived counter is
    materialised ONCE into ``duration.rounds`` — decremented in the same pass,
    so ``seconds=12`` is indistinguishable from ``rounds=2`` — after which the
    pre-existing round tick owns it and this branch stands down. ``seconds`` is
    never mutated; it stays readable as the effect's narrative-time duration.
    An effect that arrives with BOTH ``rounds`` and ``seconds`` (Bless ships
    ``rounds=10, seconds=60``) is governed by ``rounds``: the seconds branch
    only fires when ``rounds is None``.

    ``flags["until_end_of_next_turn_of"] = <actor_id>`` — "until the end of
    your next turn". Expires at that actor's next turn end, with a one-turn
    grace when the effect was applied during that same actor's turn
    (``_effect_applied_during_current_turn``).

    Concentration-flagged effects are exempt from all three branches, exactly
    as they are from the round tick: the concentration cascade and the
    per-turn repeat save own their lifetime, and the Foundry packs ship
    display-only counters on them (Hunter's Mark's ``seconds=600``).
    """
    to_expire: list[tuple[str, str, str]] = []
    for target_id, target_effects in list(live.active_effects.items()):
        for idx, eff in enumerate(list(target_effects)):
            if eff.flags.get("concentration"):
                continue
            duration = eff.duration
            expired = False

            # (1) turns — the TARGET's own turn end.
            if duration.turns is not None and target_id == actor_id:
                turns_left = duration.turns - 1
                if turns_left > 0:
                    duration = duration.model_copy(update={"turns": turns_left})
                else:
                    expired = True

            # (2) seconds -> ceil(seconds / 6) rounds, caster-keyed. Skipped
            # entirely once a rounds counter exists (rounds wins).
            if (
                not expired
                and duration.rounds is None
                and duration.seconds is not None
                and _duration_tick_matches_actor(
                    origin=eff.origin or "", target_id=target_id, actor_id=actor_id
                )
            ):
                whole_rounds = -(-duration.seconds // _SECONDS_PER_ROUND)
                rounds_left = whole_rounds - 1
                if rounds_left > 0:
                    duration = duration.model_copy(update={"rounds": rounds_left})
                else:
                    expired = True

            # (3) until the end of <actor>'s next turn.
            if (
                not expired
                and eff.flags.get("until_end_of_next_turn_of") == actor_id
                and not _effect_applied_during_current_turn(
                    live, actor_id, (target_id, eff.id, eff.origin)
                )
            ):
                expired = True

            if expired:
                to_expire.append((target_id, eff.id, eff.origin))
            elif duration is not eff.duration:
                # Immutable replacement — previously emitted EffectApplied
                # events hold the same ActiveEffect instance (see the round
                # tick's note), so never mutate the duration in place.
                target_effects[idx] = eff.model_copy(update={"duration": duration})

    for target_id, effect_id, origin in to_expire:
        _emit(
            live,
            EffectExpired(
                effect_id=effect_id,
                target_id=target_id,
                origin=origin,
                reason="duration",
            ),
        )


def _run_end_of_turn_saves(live: _LiveCombat, actor_id: str) -> None:
    """SRD §Hold Person / §Hold Monster / §Dominate Person — *"At the end
    of each of its turns, the target repeats the save, ending the spell
    on itself on a success."*

    Walks ``live.repeat_save_on_turn_end[actor_id]`` and rolls one save
    per pending spec. Emit order per spec: ``SaveRolled`` first, then
    on success an ``EffectExpired(reason=duration)`` for the source
    effect + ``ConditionRemoved`` for the applied condition (mirrors
    the cascade ``_drop_concentration`` performs on concentration drop,
    minus the ConcentrationDropped event — the caster keeps their
    concentration if the target shakes free on their own turn). Also
    clears the matching entry from ``concentration_chain[caster_id]``
    so the caster's concentration tracking reflects the target's exit.

    The repeat save applies the target's real ability modifier +
    proficiency bonus (F1c, via ``actor_stats.save_modifier``), matching
    the IR-level Save handler's per-target sidecar projection, and the d20
    goes through the shared ``roll_d20_test`` primitive (F2c) with no
    advantage source — a single draw, as before.
    """
    # Collect every repeat-save spec keyed on the actor_id-prefixed
    # identity tuples. Identity is (target_id, effect.id, effect.origin)
    # post-Phase-6 rekey.
    pending_keys = [k for k in live.repeat_save_on_turn_end if k[0] == actor_id]
    if not pending_keys:
        return
    # One lookup for the whole call: every spec here re-saves for ``actor_id``
    # (the creature whose turn is ending), so the combatant is invariant across
    # both loops. The ``else 0`` below cannot fire in practice — this function
    # is only reached from the turn-advance path for a combatant that is in
    # ``live.initiative`` — but ``_run_end_of_turn_saves`` runs inside the
    # non-throwing turn-boundary contract, so a missing combatant degrades to an
    # unmodified save rather than aborting the turn.
    target = _find_combatant(live, actor_id)
    for identity in pending_keys:
        target_id, effect_id, origin = identity
        specs = live.repeat_save_on_turn_end.get(identity, [])
        surviving: list[dict[str, Any]] = []
        for spec in specs:
            ability = spec["ability"]
            dc = int(spec["dc"])
            condition = str(spec["condition"])
            caster_id = str(spec["caster_id"])
            # SRD 5.2 Conditions on the repeat save: the same auto-fail /
            # disadvantage projection the activity save path gets, plus the
            # Exhaustion D20-Test penalty. An unconditioned target projects
            # nothing, so the seeded stream is unmoved.
            save_proj = project_passive_save_modifiers(_condition_names(target)) if target else {}
            ability_upper = ability.upper()
            if ability_upper in save_proj.get("passive_save_auto_fail", []):
                # SRD 5.2 Paralyzed / Stunned / Petrified / Unconscious —
                # automatic failure, no d20 drawn (mirrors save_primitive).
                roll_total, succeeded = 0, False
                mode: AdvantageMode = "normal"
                natural: int | None = None
                roll_modifier = 0
                roll_sources: list[AdvantageSource] = []
            else:
                modifier = (
                    save_modifier(target, ability).total + d20_test_penalty(target.conditions)
                    if target
                    else 0
                )
                dis: tuple[AdvantageSource, ...] = (
                    ("condition:target",)
                    if ability_upper in save_proj.get("passive_save_dis", [])
                    else ()
                )
                roll = roll_d20_test(live.rng, modifier, AdvantageSources(disadvantage=dis))
                roll_total, succeeded = roll.total, roll.total >= dc
                mode, natural, roll_modifier = roll.mode, roll.kept, roll.modifier
                roll_sources = list(roll.sources)
            _emit(
                live,
                SaveRolled(
                    target_id=actor_id,
                    ability=ability,
                    dc=dc,
                    roll_total=roll_total,
                    succeeded=succeeded,
                    advantage=mode,
                    natural=natural,
                    modifier=roll_modifier,
                    sources=roll_sources,
                ),
            )
            if not succeeded:
                surviving.append(spec)
                continue
            # Save succeeded — the spell ends on the target. Expire the
            # effect and remove its sourced condition. The caster's
            # concentration_chain entry for this target is pruned so a
            # future damage-driven CON save knows the target no longer
            # carries this effect (the caster's concentration itself
            # persists if other targets remain — SRD §Hold Person
            # higher-slot casts target multiple humanoids).
            _emit(
                live,
                EffectExpired(
                    target_id=actor_id,
                    effect_id=effect_id,
                    origin=origin,
                    reason="duration",
                ),
            )
            _emit(
                live,
                ConditionRemoved(
                    target_id=actor_id,
                    condition=condition,
                ),
            )
            live.conditions_by_effect.pop(identity, None)
            chain = live.concentration_chain.get(caster_id)
            if chain is not None:
                survivors = [entry for entry in chain if entry != (target_id, effect_id, origin)]
                if survivors:
                    live.concentration_chain[caster_id] = survivors
                else:
                    live.concentration_chain.pop(caster_id, None)
        if surviving:
            live.repeat_save_on_turn_end[identity] = surviving
        else:
            live.repeat_save_on_turn_end.pop(identity, None)


# ── Public seam ─────────────────────────────────────────────────────────────


def _pc_condition_immunities(pc: PartyMemberSpec) -> list[str]:
    """Union the PC spec's ``condition_immunities`` with those projected from
    its always-on granted-feature ``system.traits.ci.value`` changes .

    A PC built via ``build_party_member`` already carries its projected
    condition immunities on the spec; a host that constructs a raw
    ``PartyMemberSpec`` (as the S02 druid does) still gets its always-on
    subclass/class condition immunities projected here at combat-build time —
    Nature's Ward on a level-10 Circle-of-Land druid. Idempotent: the union
    dedupes, so re-projecting a ``build_party_member`` PC is a no-op. Scoped to
    condition immunities only — a brand-new field, so this cannot change any
    existing combat's damage/senses behavior; resistances/senses/movement stay
    owned by ``build_party_member`` (re-projecting them here would double-count
    the walk-speed bonus).
    """
    immunities = list(pc.condition_immunities)
    if not (pc.class_slug or pc.subclass_slug or pc.species_slug):
        return immunities
    loader = get_lib_loader()
    sources: list[Class | Subclass | Species | None] = []
    if pc.class_slug:
        sources.append(loader.get_class(pc.class_slug))
    if pc.subclass_slug:
        sources.append(loader.get_subclass(pc.subclass_slug))
    if pc.species_slug:
        sources.append(loader.get_species(pc.species_slug))
    changes: list[Any] = []
    for slug in granted_feature_slugs(sources, level=pc.character_level):
        feature = loader.get_feature(slug)
        if feature is None:
            continue
        for passive in feature.passive_effects:
            if passive.transfer and not passive.disabled:
                changes.extend(passive.changes)
    derived = interpret_passive_stats(changes=changes, trait_grants=(), species_senses=None)
    for ci in derived.condition_immunities:
        if ci not in immunities:
            immunities.append(ci)
    return immunities


def _build_pc_combatants(
    party: list[PartyMemberSpec],
    combatants: list[Combatant],
    actor_zone: dict[str, str],
    tracked_hp: dict[str, int],
    spell_slots_by_entity: dict[str, dict[int, int]],
    spells_known_by_entity: dict[str, list[str]],
    custom_counters_by_entity: dict[str, dict[str, dict[str, int]]],
) -> None:
    """Append a ``Combatant`` per party member and populate the passed
    accumulator dicts (actor_zone, tracked_hp, spell_slots/spells_known/
    custom_counters) in place. Mutation-only helper — returns ``None``.
    """
    for pc in party:
        combatants.append(
            Combatant(
                entity_id=pc.entity_id,
                entity_type="Character",
                name=pc.name,
                initiative=pc.initiative,
                hp_current=pc.hp_current,
                hp_max=pc.hp_max,
                ac=pc.ac,
                attack_bonus=pc.attack_bonus,
                strength=pc.strength,
                dexterity=pc.dexterity,
                constitution=pc.constitution,
                intelligence=pc.intelligence,
                wisdom=pc.wisdom,
                charisma=pc.charisma,
                concentration_effect_id=pc.concentration_effect_id,
                creature_type=pc.creature_type,
                damage_resistances=list(pc.damage_resistances),
                damage_immunities=list(pc.damage_immunities),
                damage_vulnerabilities=list(pc.damage_vulnerabilities),
                condition_immunities=_pc_condition_immunities(pc),
                senses=pc.senses,
                character_level=pc.character_level,
                base_speed=pc.base_speed,
                movement_remaining=pc.base_speed,
                movement_modes=pc.movement_modes,
                melee_reach_ft=pc.reach_ft,
                class_slug=pc.class_slug,
                subclass_slug=pc.subclass_slug,
                species_slug=pc.species_slug,
                save_proficiencies=list(pc.save_proficiencies),
                skill_proficiencies=list(pc.skill_proficiencies),
                skill_expertise=list(pc.skill_expertise),
                weapon_proficiencies=list(pc.weapon_proficiencies),
            )
        )
        actor_zone[pc.entity_id] = pc.zone_id
        tracked_hp[pc.entity_id] = pc.hp_current
        if pc.spell_slots:
            spell_slots_by_entity[pc.entity_id] = dict(pc.spell_slots)
        if pc.spells_known:
            spells_known_by_entity[pc.entity_id] = list(pc.spells_known)
        if pc.custom_counters:
            custom_counters_by_entity[pc.entity_id] = {
                k: dict(v) for k, v in pc.custom_counters.items()
            }


def _build_foe_combatants(
    encounter: list[EncounterMemberSpec],
    combatants: list[Combatant],
    actor_zone: dict[str, str],
    tracked_hp: dict[str, int],
    monster_slug_by_entity: dict[str, str],
    xp_value_by_entity: dict[str, int],
) -> None:
    """Append a ``Combatant`` per encounter foe and populate the passed
    accumulator dicts (actor_zone, tracked_hp, monster_slug, xp_value) in
    place. Mutation-only helper — returns ``None``.
    """
    for foe in encounter:
        # hydrate the monster's SRD-canonical damage vulnerabilities
        # from its template when the spec leaves the field empty (the Skeleton's
        # ``["bludgeoning"]``). Scoped to vulnerabilities — the field is new, so
        # this cannot change any existing combat's behavior; resistances/
        # immunities stay host-populated by the existing convention.
        vulnerabilities = list(foe.damage_vulnerabilities)
        # F1b (2026-08-26) — hydrate the five non-DEX ability scores,
        # proficiency bonus, and save/skill proficiencies from the SRD
        # monster template when one is set. Dexterity is spec-authoritative
        # only when the host moved it away from the ``10`` default sentinel
        # (an EncounterMemberSpec can't distinguish "left at 10" from
        # "explicitly set to 10", so 10 always defers to the template).
        # Read by ``activities/actor_stats`` on every save/check path (F1c/F1d);
        # a foe with no ``monster_template_slug`` keeps the spec's values.
        template_kw: dict[str, Any] = {}
        if foe.monster_template_slug:
            monster = get_lib_loader().get_monster(foe.monster_template_slug)
            if monster is not None:
                if not vulnerabilities:
                    vulnerabilities = list(monster.damage_vulnerabilities)
                sc = monster.ability_scores
                template_kw = {
                    "strength": sc.str,
                    "constitution": sc.con,
                    "intelligence": sc.int,
                    "wisdom": sc.wis,
                    "charisma": sc.cha,
                    "proficiency_bonus_override": monster.proficiency_bonus,
                    "save_proficiencies": [
                        a
                        for a in ("str", "dex", "con", "int", "wis", "cha")
                        if getattr(monster.saving_throws, a) is not None
                    ],
                    "skill_proficiencies": [
                        k for k, v in monster.skills.model_dump().items() if v is not None
                    ],
                    "trait_mechanics": [
                        a.mechanic for a in monster.special_abilities if a.mechanic is not None
                    ],
                }
                if foe.dexterity == 10:
                    template_kw["dexterity"] = sc.dex
        combatants.append(
            Combatant(
                entity_id=foe.entity_id,
                entity_type=foe.entity_type,
                name=foe.name,
                initiative=foe.initiative,
                hp_current=foe.hp_current,
                hp_max=foe.hp_max,
                ac=foe.ac,
                attack_bonus=foe.attack_bonus,
                damage_dice=foe.damage_dice,
                damage_type=foe.damage_type,
                behavior_profile=foe.behavior_profile,
                dexterity=template_kw.pop("dexterity", foe.dexterity),
                creature_type=foe.creature_type,
                damage_resistances=list(foe.damage_resistances),
                damage_immunities=list(foe.damage_immunities),
                damage_vulnerabilities=vulnerabilities,
                condition_immunities=list(foe.condition_immunities),
                physical_resistances_nonmagical_only=foe.physical_resistances_nonmagical_only,
                base_speed=foe.base_speed,
                movement_remaining=foe.base_speed,
                **template_kw,
            )
        )
        actor_zone[foe.entity_id] = foe.zone_id
        tracked_hp[foe.entity_id] = foe.hp_current
        if foe.monster_template_slug:
            monster_slug_by_entity[foe.entity_id] = foe.monster_template_slug
        if foe.xp_value > 0:
            xp_value_by_entity[foe.entity_id] = foe.xp_value


def _resolve_topology(
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    scene_zones: SceneTopology | None,
    grid_scene: GridScene | None,
) -> SpatialTopology:
    """Select the combat's ``SpatialTopology`` (grid vs. zone graph),
    validating grid start-cells. Raises ``ValueError`` on ambiguous/absent
    topology or an out-of-bounds/blocked grid start cell.
    """
    topology: SpatialTopology
    if grid_scene is not None and scene_zones is not None:
        raise ValueError("start_combat: pass exactly one of scene_zones or grid_scene")
    if grid_scene is not None:
        grid = GridTopology(grid_scene)
        # Reject combatants whose start cell is out of bounds or impassable —
        # an illegal start position would silently disable the range/move gates
        # for that actor (they read actor_zone, which would hold a bad cell).
        members: list[PartyMemberSpec | EncounterMemberSpec] = [*party, *encounter]
        for spec in members:
            if not grid.is_valid_cell(spec.zone_id):
                raise ValueError(
                    f"start_combat: {spec.entity_id} start cell {spec.zone_id!r} "
                    f"is out of bounds or blocked"
                )
        topology = grid
    elif scene_zones is not None:
        warnings.warn(
            "start_combat(scene_zones=...) is deprecated since 0.6.0 and will be "
            "removed in 0.7.0; pass grid_scene=GridScene(...) instead "
            "(docs/migration/v0.5-to-v0.6.md, 'Zone graph deprecated').",
            DeprecationWarning,
            stacklevel=2,
        )
        topology = _ZoneGraph(scene_zones)
    else:
        raise ValueError("start_combat: one of scene_zones or grid_scene is required")
    return topology


def _seed_active_effects(live: _LiveCombat, active_effects: Sequence[ActiveEffect]) -> None:
    """Seed ``live`` from caller-supplied ActiveEffects, mutating ``live`` in
    place: append to active_effects, parse the concentration chain (and write
    the caster's concentration_effect_id), build conditions_by_effect, and
    project active_conditions + per-combatant Combatant.conditions.
    """
    for eff in active_effects:
        live.active_effects.setdefault(eff.target_id, []).append(eff)

        # Concentration chain: parse caster_id from origin convention
        # "cast:<slug>:<caster_id>". Equipped-item enchantments use
        # "item:<item_id>:<effect_id>" — no caster, skipped.
        if eff.flags.get("concentration"):
            origin = eff.origin or ""
            caster_id: str | None = None
            if origin.startswith("cast:"):
                parts = origin.split(":", 2)
                if len(parts) == 3:
                    caster_id = parts[2]
            if caster_id:
                chain = live.concentration_chain.setdefault(caster_id, [])
                identity = (eff.target_id, eff.id, eff.origin)
                if identity not in chain:
                    chain.append(identity)
                # also write the caster's
                # Combatant.concentration_effect_id so _build_hydration_payload
                # can derive existing_concentration. Without this, a seeded
                # concentration effect (Bless carried over from a prior
                # combat, future cross-combat persistence) looks like
                # the caster isn't concentrating and the next cast won't
                # drop the old one.
                for idx, c in enumerate(live.initiative):
                    if c.entity_id != caster_id:
                        continue
                    if c.concentration_effect_id is None:
                        live.initiative[idx] = c.model_copy(
                            update={"concentration_effect_id": eff.id}
                        )
                    break

        # SRD §Condition Immunity — the same gate the runtime
        # ``EffectApplied`` fold and ``activities/effects.py`` apply: a status
        # the target is immune to never attaches, on EITHER store. A seeded
        # effect is the one path that writes ``live.active_conditions``
        # directly, so without this the host-facing view (``views.py``) and
        # ``Combatant.conditions`` would BOTH carry a condition the creature
        # cannot suffer. The ActiveEffect itself is still seeded (its non-
        # condition riders stay live), exactly as the emit-path keeps the
        # ``EffectApplied`` and drops only the ``ConditionApplied``.
        target_combatant = _find_combatant(live, eff.target_id)
        immunities = set(target_combatant.condition_immunities) if target_combatant else set()
        statuses = {s for s in eff.statuses if s not in immunities}

        # Conditions-by-effect: every status the effect imposes is
        # attributed to (target_id, id, origin), so expire/concentration
        # cascade can find them.
        if statuses:
            key = (eff.target_id, eff.id, eff.origin)
            existing = live.conditions_by_effect.get(key)
            if existing is None:
                live.conditions_by_effect[key] = list(statuses)
            else:
                for status in statuses:
                    if status not in existing:
                        existing.append(status)

        if not statuses:
            continue
        # Also project into live.active_conditions so orchestrator_bridge's
        # project_combat_state_to_redis sees the seeded statuses on the next
        # mirror tick. Without this, statuses only land on initiative[*]
        # .conditions (set below) and are silently dropped when the bridge
        # rebuilds host storage conditions from active_conditions. # .
        live.active_conditions.setdefault(eff.target_id, set()).update(statuses)
        for idx, c in enumerate(live.initiative):
            if c.entity_id != eff.target_id:
                continue
            current_conditions = c.conditions
            existing_keys = {(ac.condition, ac.source_effect_id) for ac in current_conditions}
            new_conditions = list(current_conditions)
            dirty = False
            for status in statuses:
                if (status, eff.id) in existing_keys:
                    continue
                new_conditions.append(
                    ActiveCondition(
                        condition=status,
                        source_entity_id="implied:effect",
                        scope="combat",
                        source_effect_id=eff.id,
                    )
                )
                dirty = True
            if dirty:
                live.initiative[idx] = c.model_copy(update={"conditions": new_conditions})
            break


async def start_combat(
    *,
    session_id: str,
    party: list[PartyMemberSpec],
    encounter: list[EncounterMemberSpec],
    scene_zones: SceneTopology | None = None,
    grid_scene: GridScene | None = None,
    rng_seed: int,
    scene_location_id: str = "loc:unknown",
    active_effects: Sequence[ActiveEffect] = (),
) -> StartCombatResult:
    """Open a combat, materialize runtime state, kick off the initiative loop.

    Returns a ``StartCombatResult`` envelope wrapping the ``CombatHandle``
    the caller threads through subsequent seam calls and the events emitted
    during open (round-start + first turn-start).

    ``scene_zones`` is deprecated (0.6.0) and removed in 0.7.0 — use
    ``grid_scene``.
    """
    if not party:
        raise ValueError("start_combat: party must be non-empty")
    if not encounter:
        raise ValueError("start_combat: encounter must be non-empty")

    # Initiative order: descending by initiative, ties broken by dex then
    # by entity_id for deterministic order. Mirrors the existing session
    # path's deterministic-tie-break convention.
    combatants: list[Combatant] = []
    actor_zone: dict[str, str] = {}
    monster_slug_by_entity: dict[str, str] = {}
    xp_value_by_entity: dict[str, int] = {}
    tracked_hp: dict[str, int] = {}
    tracked_temp_hp: dict[str, int] = {}
    spell_slots_by_entity: dict[str, dict[int, int]] = {}
    spells_known_by_entity: dict[str, list[str]] = {}
    custom_counters_by_entity: dict[str, dict[str, dict[str, int]]] = {}
    _build_pc_combatants(
        party,
        combatants,
        actor_zone,
        tracked_hp,
        spell_slots_by_entity,
        spells_known_by_entity,
        custom_counters_by_entity,
    )
    _build_foe_combatants(
        encounter,
        combatants,
        actor_zone,
        tracked_hp,
        monster_slug_by_entity,
        xp_value_by_entity,
    )

    combatants.sort(
        key=lambda c: (-c.initiative, -c.dexterity, c.entity_id),
    )

    topology = _resolve_topology(party, encounter, scene_zones, grid_scene)

    handle_id = f"combat:{session_id}:{rng_seed:08x}"
    live = _LiveCombat(
        handle_id=handle_id,
        session_id=session_id,
        initiative=combatants,
        party_ids={p.entity_id for p in party},
        encounter_ids={e.entity_id for e in encounter},
        topology=topology,
        rng=random.Random(rng_seed),
        event_queue=asyncio.Queue(),
        scene_location_id=scene_location_id,
        actor_zone=actor_zone,
        monster_slug_by_entity=monster_slug_by_entity,
        xp_value_by_entity=xp_value_by_entity,
        tracked_hp=tracked_hp,
        tracked_temp_hp=tracked_temp_hp,
        spell_slots_by_entity=spell_slots_by_entity,
        spells_known_by_entity=spells_known_by_entity,
        custom_counters_by_entity=custom_counters_by_entity,
    )
    _REGISTRY[handle_id] = live
    _register_default_turn_hooks(live)

    # — seed _LiveCombat.active_effects from the caller. The hook
    # is live today for equipped-magic-item enchantments (the host-side
    # _project_party_equipped_enchantments) and reserved for the wider
    # [effects-cross-combat] surface.
    #
    # Lifecycle bookkeeping: in addition to active_effects + combatant
    # conditions, seeded effects must also populate the concentration_chain
    # and conditions_by_effect indexes that runtime EffectApplied events
    # would have set via _record_effect_lifecycle_links. Without this,
    # a seeded concentration effect (Bless cast pre-combat, Hold Person
    # carried over) would never trigger concentration-drop on caster damage
    # and end-of-turn repeat saves would never fire. repeat_save_on_turn_end
    # is NOT seeded here — it requires a failed-save record we don't have
    # at seed time; the next runtime save will repopulate as needed.
    _seed_active_effects(live, active_effects)

    # C12 — a Character HYDRATED into combat already at 0 HP is Unconscious
    # (SRD 5.2 "Dropping to 0 Hit Points"). The runtime fold hangs off the
    # damage path, so without this a host resuming a saved combat with a downed
    # PC would get a PC that can act. ``_fold_condition_onto_combatant`` writes
    # BOTH condition stores, so the host-facing ``active_conditions`` view
    # agrees with ``Combatant.conditions``. State-only, no event: this is
    # hydration of a state the host already knows about, not a transition now —
    # and the death-save state stays exactly as the host supplied it (the
    # condition is what makes ``_maybe_roll_death_save`` fire on the PC's turn;
    # no failure is charged here). Monsters are excluded — a monster at 0 HP is
    # dead, never Unconscious.
    for c in list(live.initiative):
        if c.entity_id in live.party_ids and c.is_alive and c.hp_current <= 0:
            _fold_condition_onto_combatant(live, c.entity_id, "unconscious")

    # C12 — the seeded conditions may already zero or reduce a Speed; project
    # every combatant's opening movement budget before the first turn opens.
    for c in list(live.initiative):
        _clamp_movement_budget(live, c.entity_id)

    # Emit the round-start + first turn-start so a consumer of
    # ``narration_events`` sees combat actually open. The evaluator
    # itself is invoked only from inside ``submit_player_intent`` once
    # an intent arrives — this matches the scaffold's
    # "RuntimeContext per evaluation" frozen-context model.
    start_events: list[CombatEvent] = []
    live.event_listeners.append(start_events.append)
    try:
        _begin_turn(live, new_round=True)
    finally:
        live.event_listeners.remove(start_events.append)

    return StartCombatResult(
        handle=CombatHandle(handle_id=handle_id),
        events=start_events,
    )


def _granted_feature_slugs(caster: Combatant) -> frozenset[str]:
    """Feature slugs the caster's class (+ subclass) + species grants at/below its level.

    The USE_FEATURE repertoire gate: a PC may only invoke a feature its
    class, subclass, or species ``granted_features`` list grants at a level no
    higher than the caster's. The parser prompt routes both class AND species
    features through USE_FEATURE, so the gate must accept either source.
    Monsters / casters with no ``class_slug`` and no ``species_slug`` grant
    nothing (empty set ⇒ every USE_FEATURE rejected, the correct default).
    """
    loader = get_lib_loader()
    sources: list[Class | Subclass | Species | None] = []
    if caster.class_slug:
        sources.append(loader.get_class(caster.class_slug))
    if caster.subclass_slug:
        sources.append(loader.get_subclass(caster.subclass_slug))
    if caster.species_slug:
        sources.append(loader.get_species(caster.species_slug))
    return frozenset(granted_feature_slugs(sources, level=caster.character_level))


@dataclass(frozen=True)
class _FeatureInvocation:
    """A USE_FEATURE intent resolved to ONE concrete activity, after the
    repertoire gate + single-activity validation pass.

    ``is_bonus_action`` is read by the action-economy block to decide whether
    the invocation spends the Bonus Action (Rage, Second Wind) or the Action.
    Resolving this BEFORE consuming any budget is the fix for the economy
    ordering bug: a gate-rejected or multi-activity-no-op feature returns
    ``None`` from ``_resolve_feature_invocation`` and spends nothing.
    """

    activities: list[Any]
    passive_effects: list[Any]
    is_bonus_action: bool
    # SRD 5.2 §Limited-Use Features — the per-rest use cap resolved
    # from the feature's typed ``uses`` block (a literal or a ``@scale.*`` max
    # resolved against the caster's ScaleValue map), or ``None`` when the feature
    # is uncapped: no ``uses`` block, empty ``max``, or a symbolic ``max`` that
    # cannot be resolved. See ``_feature_use_cap``.
    use_cap: int | None = None


def _feature_use_cap(feature: Any, scale_values: Mapping[str, int | str]) -> int | None:
    """Resolve a feature's per-rest use cap from its typed ``uses`` block.

    Returns ``None`` — meaning UNCAPPED, never gated — for a feature with no
    ``uses`` block, an empty ``uses.max``, or a ``max`` this cannot resolve. The
    resolvable cases:

    * a literal integer ``max`` (``"1"``, ``"3"``) is honoured exactly;
    * a Foundry ``@scale.<owner>.<key>`` roll-data token is resolved against
      ``scale_values`` — the SAME per-caster ScaleValue map the orchestrator
      already builds for activity resolution (``build_scale_values``). Second
      Wind's ``@scale.fighter.second-wind`` resolves to 3 at Fighter level 5,
      per the class scale table ``{1: 2, 4: 3, 10: 4}``.

    Any OTHER symbolic ``max`` — ``@prof``, ``max(1, @abilities.cha.mod)``,
    ``5 * @classes.paladin.levels`` — is NOT resolved here (it would need the
    caster's proficiency bonus / ability modifiers threaded through, and no
    scenario exercises it). Rather than guess or wrongly floor such a feature to
    a single use per rest (which would REGRESS the pre-Cluster-9 behaviour, where
    every feature was uncapped), it falls back to ``None`` / uncapped — a capped
    resource is never wrongly rejected. Lifting that residual (non-``@scale``
    symbolic maxes) is a recorded follow-up (see BACKLOG "Rest & recovery").
    """
    uses = getattr(feature, "uses", None)
    if uses is None:
        return None
    max_raw = str(getattr(uses, "max", "") or "").strip()
    if not max_raw:
        return None
    try:
        parsed = int(max_raw)
    except ValueError:
        parsed = None
    if parsed is not None:
        # A literal max of "0" (or negative) maps to UNCAPPED today. No corpus
        # feature carries max="0", and "0 uses" arguably means UNUSABLE rather
        # than unlimited — revisit if such data ever appears.
        return parsed if parsed > 0 else None
    if max_raw.startswith("@scale."):
        resolved = scale_values.get(max_raw[len("@scale.") :])
        if isinstance(resolved, int) and resolved > 0:
            return resolved
    # Unresolvable symbolic max (``@prof``, ``max(1, ...)``, an absent @scale
    # owner/key): fall back to UNCAPPED rather than wrongly gating (pre-C09
    # behaviour). See BACKLOG.
    return None


def _feature_use_counter_key(feature_id: str) -> str:
    """The ``custom_counters`` sidecar key namespacing a feature's use tally."""
    return f"{FEATURE_USE_COUNTER_PREFIX}{feature_id}"


def _feature_use_spent(live: _LiveCombat, entity_id: str, feature_id: str) -> int:
    """Uses of ``feature_id`` already spent by ``entity_id`` this rest cycle."""
    return (
        live.custom_counters_by_entity.get(entity_id, {})
        .get(_feature_use_counter_key(feature_id), {})
        .get("spent", 0)
    )


def _increment_feature_use(live: _LiveCombat, entity_id: str, feature_id: str) -> None:
    """Record one spent use of ``feature_id`` on the caster's sidecar counter."""
    counters = live.custom_counters_by_entity.setdefault(entity_id, {})
    counter = counters.setdefault(_feature_use_counter_key(feature_id), {"spent": 0})
    counter["spent"] = counter.get("spent", 0) + 1


def _feature_uses_exhausted(
    live: _LiveCombat,
    actor_id: str,
    feature_id: str,
    feature_invocation: _FeatureInvocation,
) -> bool:
    """SRD §Limited-Use Features — True (after emitting ``CastFailed``) when a
    capped feature's per-rest uses are spent with no intervening rest.

    Emits ``CastFailed(reason="no_uses_remaining")`` — the ``no_action_economy``
    reject shape, extended from a per-turn budget to a per-rest one. Uncapped
    features (``use_cap is None``) never gate.
    """
    cap = feature_invocation.use_cap
    if cap is None or _feature_use_spent(live, actor_id, feature_id) < cap:
        return False
    _emit(live, CastFailed(actor_id=actor_id, spell_id="", reason="no_uses_remaining"))
    return True


def _record_capped_feature_use(
    live: _LiveCombat,
    actor_id: str,
    feature_id: str | None,
    feature_invocation: _FeatureInvocation | None,
) -> None:
    """Increment the per-rest use counter for a committed capped-feature invocation.

    No-op for a non-feature intent (``feature_id`` / ``feature_invocation`` is
    ``None``) or an uncapped feature (``use_cap is None``) — only a within-cap
    invocation reaches here past the early exhaustion gate.
    """
    if (
        feature_id is not None
        and feature_invocation is not None
        and feature_invocation.use_cap is not None
    ):
        _increment_feature_use(live, actor_id, feature_id)


def _item_use_counter_key(item_id: str) -> str:
    """The ``custom_counters`` sidecar key namespacing an item's charge tally."""
    return f"{ITEM_USE_COUNTER_PREFIX}{item_id}"


def _activity_item_use_cost(item_slug: str, activity: Any) -> int:
    """Positive literal ``itemUses`` cost of ONE activity.

    Symbolic or negative targets (``-3d4``, ``-@item.uses.spent``,
    ``@item.uses.max``) are recharge/whole-pool semantics, not a spend
    cost — skipped, never coerced.
    """
    cost = 0
    for target in activity.consumption.targets:
        if target.type != "itemUses":
            continue
        try:
            value = int(str(target.value).strip())
        except ValueError:
            _LOGGER.info("item_charge_target_symbolic slug=%s value=%r", item_slug, target.value)
            continue
        if value > 0:
            cost += value
    return cost


def _item_charge_activity(item: Any, activity_id: str | None) -> Any | None:
    """The activity ``_item_charge_cost`` prices for this intent: the
    explicitly selected activity, else the first consuming activity
    (Foundry activities are alternative invocations, never a batch).

    Shared with charge-scaling validation so the cost and the scaling
    ceiling are always evaluated against the SAME activity.
    """
    if activity_id:
        for activity in item.activities:
            if activity.id == activity_id:
                return activity
        return None
    consuming = [
        activity for activity in item.activities if _activity_item_use_cost(item.slug, activity) > 0
    ]
    if len(consuming) > 1:
        _LOGGER.warning(
            "item_charge_ambiguous_activity slug=%s charging_first_of=%d",
            item.slug,
            len(consuming),
        )
    return consuming[0] if consuming else None


def _item_charge_cost(item: Any, activity_id: str | None) -> int:
    """Cost of ONE invocation: the selected activity's cost, else the first
    consuming activity's (Foundry activities are alternative invocations,
    never a batch)."""
    activity = _item_charge_activity(item, activity_id)
    if activity is None:
        return 0
    return _activity_item_use_cost(item.slug, activity)


_CONSUMPTION_MAX_MIN_RE = re.compile(r"^min\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$")


def _eval_consumption_max(expr: str, *, remaining: int, cap: int | None) -> int | None:
    """Evaluate the closed ``consumption.scaling.max`` grammar of the SRD item corpus."""
    text = expr.strip()
    if not text:
        return None

    def _term(tok: str) -> int | None:
        tok = tok.strip()
        if tok == "@item.uses.value":
            return remaining
        if tok == "@item.uses.max":
            return cap
        try:
            return int(tok)
        except ValueError:
            return None

    match = _CONSUMPTION_MAX_MIN_RE.match(text)
    if match:
        left, right = _term(match.group(1)), _term(match.group(2))
        if left is None or right is None:
            _LOGGER.warning("consumption_max_unparseable expr=%r", expr)
            return None
        return min(left, right)
    value = _term(text)
    if value is None:
        _LOGGER.warning("consumption_max_unparseable expr=%r", expr)
    return value


def _item_charge_cap(item: Any) -> int | None:
    """Resolve an item's charge pool cap from its typed ``uses`` block.

    ``None`` — meaning UNCAPPED, never gated — for an item with no ``uses``
    block or an unparseable ``max``. Mirrors ``_feature_use_cap``'s
    fail-open contract: a capped resource is never wrongly rejected.
    """
    uses = getattr(item, "uses", None)
    if uses is None or not uses.max:
        return None
    try:
        return int(str(uses.max).strip())
    except ValueError:
        _LOGGER.warning("item_charge_cap_unparseable slug=%s max=%r", item.slug, uses.max)
        return None


def _item_charges_spent(live: _LiveCombat, entity_id: str, item_id: str) -> int:
    """Charges of ``item_id`` already spent by ``entity_id`` this rest cycle."""
    return (
        live.custom_counters_by_entity.get(entity_id, {})
        .get(_item_use_counter_key(item_id), {})
        .get("spent", 0)
    )


def _resolve_charge_request(
    live: _LiveCombat,
    actor_id: str,
    item_id: str,
    item: Any,
    intent: PlayerIntent,
    base_cost: int,
    cap: int,
) -> int | None:
    """Validate ``intent.charges_to_spend`` against the SAME activity
    ``_item_charge_cost`` priced. Returns the effective (requested) cost, or
    ``None`` after emitting ``CastFailed(reason="invalid_charge_spend")``
    when the activity doesn't allow scaling or the request is out of the
    evaluated bounds.

    I1: scaling is only honored on a ``kind == "cast"`` activity. Charge
    scaling on a non-cast activity (staff-of-striking's damage, ring-of-
    the-ram's attack) would need "extra dice per charge" semantics the
    resolver doesn't implement — honest reject rather than silently
    charging N and delivering the base effect.

    I3: also rejected when ``base_cost <= 0`` — an activity whose only
    ``itemUses`` targets are negative/symbolic (recharge, not spend; see
    ``_activity_item_use_cost``) has nothing for ``charges_to_spend`` to
    scale against (rope-of-climbing's scaling utility activity), so a
    request there would deduct charges for no effect. Already implied for
    most cases by the cast-only rule above (those are ``kind == "utility"``),
    but kept as an explicit guard — cheap, and a belt for host content packs
    whose "cast" activities might ship a zero/negative cost.
    """
    requested = intent.charges_to_spend
    activity = _item_charge_activity(item, intent.activity_id)
    scaling = activity.consumption.scaling if activity is not None else None
    if (
        scaling is None
        or not scaling.allowed
        or getattr(activity, "kind", "") != "cast"
        or base_cost <= 0
    ):
        _emit(live, CastFailed(actor_id=actor_id, spell_id="", reason="invalid_charge_spend"))
        return None
    remaining = cap - _item_charges_spent(live, actor_id, item_id)
    ceiling = _eval_consumption_max(scaling.max, remaining=remaining, cap=cap)
    upper_bound = min(ceiling, remaining) if ceiling is not None else remaining
    if requested is None or requested < base_cost or requested > upper_bound:
        _emit(live, CastFailed(actor_id=actor_id, spell_id="", reason="invalid_charge_spend"))
        return None
    return requested


def _item_charge_gate(live: _LiveCombat, actor_id: str, intent: PlayerIntent) -> bool:
    """True (after emitting ``CastFailed``) when a capped item's remaining
    charges cannot cover this invocation's cost — reject before any budget
    is consumed. Items with no ``uses`` pool (``cap is None``) never gate,
    preserving today's fully ungated ``use_item`` behavior — UNLESS the
    intent carries ``charges_to_spend``, which has nothing to scale against
    on a pool-less item and rejects ``invalid_charge_spend``.
    """
    if intent.intent_type != "use_item" or not intent.item_id:
        return False
    item = get_lib_loader().get_item(intent.item_id)
    if item is None:
        return False  # unknown slug falls through to the existing empty-resolution path
    cap = _item_charge_cap(item)
    requested = intent.charges_to_spend
    if cap is None:
        if requested is not None:
            _emit(live, CastFailed(actor_id=actor_id, spell_id="", reason="invalid_charge_spend"))
            return True
        return False
    cost = _item_charge_cost(item, intent.activity_id)
    if requested is not None:
        resolved = _resolve_charge_request(live, actor_id, intent.item_id, item, intent, cost, cap)
        if resolved is None:
            return True
        cost = resolved
    elif cost <= 0:
        return False
    if _item_charges_spent(live, actor_id, intent.item_id) + cost > cap:
        _emit(live, CastFailed(actor_id=actor_id, spell_id="", reason="no_charges_remaining"))
        return True
    return False


def _gate_feature_and_item_uses(
    live: _LiveCombat,
    actor_id: str,
    intent: PlayerIntent,
    feature_invocation: _FeatureInvocation | None,
) -> bool:
    """True (rejects) when a capped feature invocation's per-rest uses, or a
    capped item's charge pool, cannot cover this intent.

    Extracted out of ``submit_player_intent`` to keep it under the C901
    complexity ceiling; groups both gates at their shared placement point —
    after feature resolution, BEFORE any action-economy budget is consumed.
    """
    if (
        intent.feature_id
        and feature_invocation is not None
        and _feature_uses_exhausted(live, actor_id, intent.feature_id, feature_invocation)
    ):
        return True
    return _item_charge_gate(live, actor_id, intent)


def _record_item_charge_spend(live: _LiveCombat, actor_id: str, intent: PlayerIntent) -> None:
    """Commit the charge spend once every gate has passed. No-op for a non-
    ``use_item`` intent or an uncapped item — only a within-cap invocation
    reaches here past the early exhaustion gate.
    """
    if intent.intent_type != "use_item" or not intent.item_id:
        return
    item = get_lib_loader().get_item(intent.item_id)
    if item is None or _item_charge_cap(item) is None:
        return
    cost = (
        intent.charges_to_spend
        if intent.charges_to_spend is not None
        else _item_charge_cost(item, intent.activity_id)
    )
    if cost <= 0:
        return
    counters = live.custom_counters_by_entity.setdefault(actor_id, {})
    counter = counters.setdefault(_item_use_counter_key(intent.item_id), {"spent": 0})
    counter["spent"] = counter.get("spent", 0) + cost


def _resolve_feature_invocation(
    caster: Combatant, feature_id: str, activity_id: str | None = None
) -> _FeatureInvocation | None:
    """Resolve a USE_FEATURE intent to its single concrete activity, or ``None``.

    Applies the REPERTOIRE GATE (class / subclass / species ``granted_features``
    at/below the caster's level) and the SINGLE-ACTIVITY contract. Returns
    ``None`` — after a loud, tracked warning — when the feature is out of
    repertoire, absent from the lib, or has no typed activities.

    A multi-activity feature is a repertoire of ALTERNATIVES (Channel Divinity:
    Divine Spark Heal vs Save vs Turn Undead). When ``activity_id`` names one of
    them, resolve EXACTLY that activity; when it is absent or names none of them,
    keep the safe no-op reject (never guess). Returning ``None`` lets the caller
    reject the invocation BEFORE any action-economy budget is consumed.

    Rage / Second Wind activate as a Bonus Action (``activation.type ==
    "bonus"``); that does NOT end the turn, so the actor may rage then swing on
    the same turn.
    """
    if feature_id not in _granted_feature_slugs(caster):
        _LOGGER.warning(
            "feature_not_in_repertoire feature_id=%s class_slug=%s subclass_slug=%s "
            "species_slug=%s level=%d",
            feature_id,
            caster.class_slug,
            caster.subclass_slug,
            caster.species_slug,
            caster.character_level,
        )
        return None
    feature = get_lib_loader().get_feature(feature_id)
    feature_activities = list(feature.activities) if feature else []
    if not feature_activities:
        _LOGGER.warning("class_feature_no_typed_activities feature_id=%s", feature_id)
        return None
    if len(feature_activities) > 1:
        # Repertoire of ALTERNATIVES — resolve the caller-selected activity, or
        # defer with a loud, tracked no-op when no valid selection is supplied
        # (firing all of them is wrong; guessing one is worse).
        selected = next((a for a in feature_activities if a.id == activity_id), None)
        if selected is None:
            _LOGGER.warning(
                "feature_multi_activity_selection_deferred feature_id=%s count=%d activity_id=%s",
                feature_id,
                len(feature_activities),
                activity_id,
            )
            return None
        feature_activities = [selected]
    is_bonus = getattr(feature_activities[0].activation, "type", None) == "bonus"
    # Resolve the per-rest use cap against the caster's real ScaleValue map — the
    # same ``build_scale_values`` machinery activity resolution uses — so a
    # ``@scale.*`` max (Second Wind's ``@scale.fighter.second-wind`` → 3 at L5)
    # yields its true, level-scaled cap rather than a conservative floor.
    scale_values = build_scale_values(
        class_slug=caster.class_slug,
        subclass_slug=caster.subclass_slug,
        species_slug=caster.species_slug,
        level=caster.character_level,
        loader=get_lib_loader(),
    )
    # Rage's mwak buff + resistances ride a PassiveEffect on the feature; thread
    # them so its UtilityActivity's effect rider (``effects[].id``) resolves to a
    # runtime ActiveEffect.
    return _FeatureInvocation(
        activities=feature_activities,
        passive_effects=list(feature.passive_effects) if feature else [],
        is_bonus_action=is_bonus,
        use_cap=_feature_use_cap(feature, scale_values),
    )


def _begin_turn(live: _LiveCombat, *, new_round: bool) -> None:
    """Open the turn ``live.current_turn_index`` now points at.

    The second half of the turn boundary, shared by ``start_combat`` (which has
    no turn to end) and ``_end_turn_and_advance``. Emits the round-start pair
    when ``new_round``, then ``TurnStarted`` (whose ``_emit`` fold performs the
    action-economy resets), the ``turn_start`` marker + hooks, and finally any
    pending death save.
    """
    if new_round:
        _emit(live, RoundStarted(round_number=live.round_number))
        _emit(
            live,
            TurnPhase(actor_id=None, phase="round_start", round_number=live.round_number),
        )
        run_round_start(live)
    actor_id = _current_actor(live).entity_id
    _emit(live, TurnStarted(actor_id=actor_id))
    _emit(
        live,
        TurnPhase(actor_id=actor_id, phase="turn_start", round_number=live.round_number),
    )
    run_turn_start(live, actor_id)
    _maybe_roll_death_save(live)


def _end_turn_and_advance(live: _LiveCombat, actor_id: str) -> None:
    """SRD §Action Economy — end ``actor_id``'s turn and start the next.

    The ONE turn-advance implementation in the engine: ``submit_player_intent``
    (both the spell-slot reject paths and the normal post-resolution path) and
    ``advance_monster_turn`` all route through here, and ``start_combat`` runs
    the second half via ``_begin_turn``. Before F3a each of those three sites
    carried its own copy of the emit-and-wrap block.

    Event order at the boundary is fixed and pinned by
    ``tests/test_turn_lifecycle.py``::

        TurnPhase(turn_end, A) -> [turn_end hooks: repeat-save, duration tick,
                                    timed-effect expiry] -> TurnEnded(A)
        -> (on wrap) RoundStarted -> TurnPhase(round_start) -> [round_start hooks]
        -> TurnStarted(B) -> TurnPhase(turn_start, B) -> [turn_start hooks]
        -> pending death save

    The marker precedes its hooks so a host reading the stream sees the phase
    announced before anything that phase causes. That includes the SRD repeat
    save (Hold Person & co.), which is the ``engine:repeat-save`` ``turn_end``
    hook rather than a call at the intent sites — so it fires exactly once per
    turn end and never on the bonus-action path, which returns before reaching
    here.
    """
    _emit(
        live,
        TurnPhase(actor_id=actor_id, phase="turn_end", round_number=live.round_number),
    )
    run_turn_end(live, actor_id)
    _emit(live, TurnEnded(actor_id=actor_id))
    live.current_turn_index += 1
    new_round = live.current_turn_index >= len(live.initiative)
    if new_round:
        live.current_turn_index = 0
        live.round_number += 1
    _begin_turn(live, new_round=new_round)


def _validate_intent_preconditions(
    live: _LiveCombat,
    handle: CombatHandle,
    actor_id: str,
    *,
    intent: PlayerIntent | None = None,
) -> Combatant:
    """Validate that combat is live, ``actor_id`` is in initiative, it is
    currently ``actor_id``'s turn, and — when ``intent`` is given — the actor
    is not Incapacitated for an action/bonus/reaction-shaped intent. Raises
    ``IntentRejectedError`` on any failure; returns the current actor's
    ``Combatant`` on success."""
    if live.ended:
        raise IntentRejectedError("combat_ended", f"handle={handle.handle_id}")

    in_initiative = any(c.entity_id == actor_id for c in live.initiative)
    if not in_initiative:
        raise IntentRejectedError(
            "actor_not_in_initiative",
            f"actor_id={actor_id!r} not in initiative order",
        )

    current = _current_actor(live)
    if current.entity_id != actor_id:
        raise IntentRejectedError(
            "not_actor_turn",
            f"current_turn={current.entity_id!r}, submitted={actor_id!r}",
        )

    # SRD 5.2 Incapacitated: "You can't take any action, Bonus Action, or
    # Reaction." (implied by Paralyzed / Petrified / Stunned / Unconscious).
    if (
        intent is not None
        and intent.intent_type not in _INCAPACITATED_ALLOWED_INTENTS
        and conditions_block_actions(_condition_names(current))
    ):
        raise IntentRejectedError(
            "actor_incapacitated",
            f"actor_id={actor_id!r} is Incapacitated and cannot take {intent.intent_type!r}",
        )
    return current


def _handle_move(live: _LiveCombat, current: Combatant, intent: PlayerIntent) -> None:
    """SRD 5.2 §Movement and Position — move ``current`` to ``target_zone_id``
    along the fewest-cells legal route (``shortest_path``), paying each leg's
    ``edge_distance`` (difficult terrain doubles) out of ``movement_remaining``.
    One ``ActorMoved`` per intent carries the total distance. Movement does
    NOT end the turn.

    Rejections (``MoveFailed``, nothing mutated): ``not_adjacent`` — no
    destination / untracked position / destination is the current cell (the
    legacy reason is retained for hosts), or, on the zone backend, a
    destination that is not an adjacent zone; ``occupied`` — "You can't willingly
    end a move in a space occupied by another creature"; ``blocked_path`` —
    the destination is adjacent but the step crosses a wall or cuts a blocked
    corner; ``unreachable`` — no legal route (enemy-occupied cells are
    impassable, allies may be passed through); ``insufficient_movement`` — the
    whole route costs more than the remaining budget, and nothing moves.

    Multi-hop routing, ``occupied`` and the enemy-impassability rule are all
    GRID-only: a zone is an area rather than a 5-ft square and ``_ZoneGraph``
    does not model occupancy, so the zone backend keeps its pre-C16 behaviour
    byte-for-byte — a single step to an ADJACENT zone (a non-adjacent
    destination is rejected ``not_adjacent``, never routed through
    intermediate zones), and a PC may still move into a zone an enemy holds to
    engage it in melee.

    Opportunity attacks (monster reactor / PC mover) fire before each cell is
    left; a mover dropped to 0 HP stops where the drop happened and the
    ``ActorMoved`` (if any cells were crossed) reflects the partial walk.
    """
    actor_id = current.entity_id
    # SRD 5.2 "Speed 0. Your Speed is 0 and can't increase." (Grappled /
    # Restrained / Paralyzed / Petrified / Unconscious) and Exhaustion's
    # ``-5 ft x level``: a creature whose effective Speed is 0 cannot move at
    # all — distinct from ``insufficient_movement`` (budget spent this turn).
    if _effective_speed(current) == 0:
        _emit(live, MoveFailed(actor_id=actor_id, reason="speed_zero"))
        return
    destination = intent.target_zone_id
    start_zone = live.actor_zone.get(actor_id)
    if destination is None or start_zone is None or destination == start_zone:
        _emit(live, MoveFailed(actor_id=actor_id, reason="not_adjacent"))
        return
    # Occupancy is a GRID rule: a zone is an area, not a 5-ft square, so the
    # zone graph keeps its pre-C16 behaviour.
    # zone graph: legacy behaviour until removal in 0.7
    on_grid = isinstance(live.topology, GridTopology)
    # SRD §Moving Around Other Creatures — a move may not END in another
    # creature's space, ally or enemy alike.
    if on_grid and destination in _occupied_cells(live, exclude=(actor_id,)):
        _emit(live, MoveFailed(actor_id=actor_id, reason="occupied"))
        return
    # Grid backend: adjacency alone doesn't guarantee a legal step — a wall
    # crossing the segment or a diagonal cutting a blocked corner yields None
    # from edge_distance (SRD 5.2 "Corners").
    if (
        live.topology.is_adjacent(start_zone, destination)
        and live.topology.edge_distance(start_zone, destination) is None
    ):
        _emit(live, MoveFailed(actor_id=actor_id, reason="blocked_path"))
        return
    if on_grid:
        # Enemy spaces are impassable on the grid only, for the same reason.
        side = live.party_ids if actor_id in live.party_ids else live.encounter_ids
        enemy_cells: Collection[str] = _occupied_cells(live, exclude=side)
        path = live.topology.shortest_path(start_zone, destination, avoid=enemy_cells)
        if not path:
            _emit(live, MoveFailed(actor_id=actor_id, reason="unreachable"))
            return
    else:
        # zone graph: legacy behaviour until removal in 0.7 — multi-hop
        # routing is GRID-only. A zone is an area, not a 5-ft square, so a
        # zone MOVE stays the pre-C16 single-hop step to an ADJACENT zone and
        # a non-adjacent destination keeps its ``not_adjacent`` rejection.
        if not live.topology.is_adjacent(start_zone, destination):
            _emit(live, MoveFailed(actor_id=actor_id, reason="not_adjacent"))
            return
        path = [start_zone, destination]
    # "To enter a square, you must have enough movement left to pay for
    # entering" — the whole route is priced up front so a rejection is atomic.
    total_cost = _path_total_distance(live.topology, path)
    if total_cost is None or current.movement_remaining < total_cost:
        _emit(live, MoveFailed(actor_id=actor_id, reason="insufficient_movement"))
        return
    spent = 0
    position = start_zone
    for next_zone in path[1:]:
        step_distance = live.topology.edge_distance(position, next_zone)
        if step_distance is None:  # pragma: no cover - route is legal by construction
            break
        # SRD §Opportunity Attacks — monster-reactor / PC-mover direction,
        # fired before the mover leaves each cell's reach. A mover dropped to
        # 0 HP stops where the drop happened.
        if _fire_monster_opportunity_attacks_on_move(
            live, mover_id=actor_id, from_zone=position, to_zone=next_zone
        ):
            break
        spent += step_distance
        position = next_zone
        # Decrement budget + update position. model_copy + slot-replace
        # mirrors the C-1 action-economy mutation pattern.
        for idx, c in enumerate(live.initiative):
            if c.entity_id == actor_id:
                live.initiative[idx] = c.model_copy(
                    update={"movement_remaining": c.movement_remaining - step_distance}
                )
                break
        live.actor_zone[actor_id] = next_zone
    if spent == 0:
        return
    _emit(
        live,
        ActorMoved(
            actor_id=actor_id,
            from_zone=start_zone,
            to_zone=position,
            distance_ft=spent,
        ),
    )
    # Turn stays live — no TurnEnded, no current_turn_index advance.


@dataclass
class _ActionCost:
    """Action-economy classification for an intent: which budget it consumes
    and whether it is a reaction cast (which additionally emits
    ``ReactionTriggered``). ``cast_spell_for_timing`` is the timing-only spell
    fetch reused by the slot gate downstream."""

    is_bonus_action: bool
    is_reaction_cast: bool
    cast_spell_for_timing: Spell | None


def _classify_action_cost(
    intent: PlayerIntent, feature_invocation: _FeatureInvocation | None
) -> _ActionCost:
    """SRD §Action Economy — classify an intent's action cost BEFORE emitting
    IntentSubmitted. Cast spells consult their asset's typed
    ``casting_time.unit``; a feature invocation reads its resolved cost; all
    other intents are Actions."""
    cast_spell_for_timing = (
        get_lib_loader().get_spell(intent.spell_id)
        if intent.intent_type == "cast_spell" and intent.spell_id
        else None
    )
    casting_unit = (
        cast_spell_for_timing.casting_time.unit if cast_spell_for_timing is not None else None
    )
    is_bonus_action = casting_unit == CastingTimeUnit.BONUS
    # SRD §Action Economy — a class feature is a Bonus Action when its (single)
    # activity's ``activation.type`` is ``"bonus"`` (Rage, Second Wind). A bonus
    # action does NOT end the turn, so the actor may rage then swing on the same
    # turn — the very flow exercises. ``feature_invocation`` is already
    # resolved (gate + single-activity validation) above; read its cost here.
    if feature_invocation is not None and feature_invocation.is_bonus_action:
        is_bonus_action = True
    is_reaction_cast = casting_unit == CastingTimeUnit.REACTION
    return _ActionCost(
        is_bonus_action=is_bonus_action,
        is_reaction_cast=is_reaction_cast,
        cast_spell_for_timing=cast_spell_for_timing,
    )


def _spell_out_of_range(
    live: _LiveCombat,
    actor_id: str,
    intent: PlayerIntent,
    cast_spell_for_timing: Spell | None,
) -> bool:
    """SRD §Spell Range — return ``True`` if this is a targeted cast whose
    target lies beyond the spell's metric range. ``self``/``special`` ranges
    carry no metric distance and never gate."""
    if not (
        intent.intent_type == "cast_spell"
        and cast_spell_for_timing is not None
        and intent.target_id is not None
    ):
        return False
    spell_range = cast_spell_for_timing.range
    if spell_range.units == SpellRangeUnits.FEET:
        range_ft: int | None = spell_range.value
    elif spell_range.units == SpellRangeUnits.TOUCH:
        range_ft = 5
    else:
        range_ft = None
    if isinstance(range_ft, int) and range_ft > 0:
        caster_zone = live.actor_zone.get(actor_id)
        target_zone = live.actor_zone.get(intent.target_id)
        if (
            caster_zone is not None
            and target_zone is not None
            and not _in_range_with_los(live.topology, caster_zone, target_zone, range_ft)
        ):
            return True
    return False


def _spell_out_of_range_failure(
    live: _LiveCombat,
    actor_id: str,
    intent: PlayerIntent,
    cast_spell_for_timing: Spell | None,
) -> CombatEvent | None:
    """``CastFailed(reason="out_of_range")`` when ``intent`` is a spell-range-
    gated cast; ``None`` otherwise. One of the ``pre_resolution_gates``
    failure-builders consumed by ``submit_player_intent``."""
    if not _spell_out_of_range(live, actor_id, intent, cast_spell_for_timing):
        return None
    return CastFailed(actor_id=actor_id, spell_id=intent.spell_id or "", reason="out_of_range")


def _hellish_rebuke_target_invalid(current: Combatant, intent: PlayerIntent) -> bool:
    """SRD §Hellish Rebuke — return ``True`` if this is a Hellish Rebuke cast
    whose target is not the most-recent damager tracked on the caster."""
    return (
        intent.intent_type == "cast_spell"
        and intent.spell_id == "hellish-rebuke"
        and (current.last_damaged_by is None or intent.target_id != current.last_damaged_by)
    )


def _cast_target_invalid(
    live: _LiveCombat,
    caster: Combatant,
    actor_id: str,
    intent: PlayerIntent,
    cast_spell: Spell | None,
) -> bool:
    """Every pre-slot ``target_invalid`` reason for a cast, in one predicate.

    Two today: Hellish Rebuke's "the creature that damaged you" trigger target,
    and a Cone/Line/Cube AoE template with no way to aim it. Both must reject
    before budget/slot consumption, so they share one gate in
    ``submit_player_intent`` and one ``CastFailed`` emission.
    """
    return _hellish_rebuke_target_invalid(caster, intent) or _directional_aoe_lacks_direction(
        live, actor_id, intent, cast_spell
    )


def _cast_target_invalid_failure(
    live: _LiveCombat,
    current: Combatant,
    actor_id: str,
    intent: PlayerIntent,
    cast_spell: Spell | None,
) -> CombatEvent | None:
    """``CastFailed(reason="target_invalid")`` for every pre-slot illegal
    target or template placement (Hellish Rebuke's fixed target, an unaimed
    Cone/Line/Cube) — see ``_cast_target_invalid``; ``None`` otherwise. One of
    the ``pre_resolution_gates`` failure-builders consumed by
    ``submit_player_intent``."""
    if not _cast_target_invalid(live, current, actor_id, intent, cast_spell):
        return None
    return CastFailed(actor_id=actor_id, spell_id=intent.spell_id or "", reason="target_invalid")


def _consume_action_budget(live: _LiveCombat, actor_id: str, cost: _ActionCost) -> Combatant:
    """Consume the classified action-economy budget on ``actor_id``'s
    initiative slot and return the refreshed current actor. ``current`` is a
    stale snapshot; mutate via slot model_copy so subsequent reads see the
    updated state."""
    for idx, c in enumerate(live.initiative):
        if c.entity_id == actor_id:
            if cost.is_bonus_action:
                live.initiative[idx] = c.model_copy(update={"bonus_action_available": False})
            elif cost.is_reaction_cast:
                live.initiative[idx] = c.model_copy(update={"reaction_available": False})
            else:
                live.initiative[idx] = c.model_copy(update={"action_available": False})
            break
    return _current_actor(live)


def _consume_spell_slot(
    live: _LiveCombat, current: Combatant, actor_id: str, intent: PlayerIntent
) -> bool:
    """SRD §Spellcasting — Spell Slots: "Whenever a character casts a
    spell, they expend a slot of that spell's level or higher." The
    slot gate lives on the orchestrator: the typed resolver walks the
    spell's own activities directly (no wrapping ``CastActivity``), so it
    never reaches a slot-consuming handler — the orchestrator owns the
    gate + decrement for this PC seam. The decrement is final here; the
    typed resolver does not mutate any per-evaluation slot sidecar, so there
    is no post-resolution slot writeback to reconcile with.

    Returns ``True`` if the cast was REJECTED (a ``CastFailed`` was emitted
    and the turn advanced — the caller must return); ``False`` otherwise.
    """
    if not (intent.intent_type == "cast_spell" and intent.spell_id):
        return False
    slot_gate_spell = get_lib_loader().get_spell(intent.spell_id)
    if slot_gate_spell is None:
        return False
    base_level = slot_gate_spell.level
    slot_level = intent.slot_level if intent.slot_level is not None else base_level
    # SRD §Cantrips — "A cantrip is a spell that can be cast at
    # will, without using a spell slot." Cantrips cannot be cast
    # at higher slot levels; the engine's only correct response
    # to an intent that requests a slot on a base_level=0 spell
    # is to reject the cast (caller bug, not a silent demotion to
    # base level — silent demotion would let a "buggy" intent
    # surface as a successful cast with unintended scaling).
    if base_level == 0 and intent.slot_level not in (None, 0):
        _emit(
            live,
            CastFailed(
                actor_id=current.entity_id,
                spell_id=intent.spell_id,
                reason="no_slot",
            ),
        )
        _end_turn_and_advance(live, actor_id)
        return True
    if base_level > 0:
        slots = live.spell_slots_by_entity.get(current.entity_id, {})
        available = int(slots.get(slot_level, 0))
        if available <= 0:
            _emit(
                live,
                CastFailed(
                    actor_id=current.entity_id,
                    spell_id=intent.spell_id,
                    reason="no_slot",
                ),
            )
            _end_turn_and_advance(live, actor_id)
            return True
        # Consume the slot. The typed PC resolver does not touch
        # ``_counter_state``, so this subtract is the authoritative
        # decrement — no post-evaluation writeback overwrites it.
        slots[slot_level] = available - 1
    return False


@dataclass
class _ResolvedActivities:
    """The typed-entity fetch result for an intent: the activities the resolver
    will walk, plus the ancillary carriers (cast spell, weapon, spellcasting
    ability, feature passive effects) the context builder needs."""

    activities: list[Any]
    cast_spell: Spell | None
    fetched_weapon: Weapon | None
    spellcasting_ability: str | None
    feature_passive_effects: list[Any]


def _resolve_caster_spellcasting_ability(caster: Combatant) -> str | None:
    """SRD 5.2 §Spellcasting — the ability that governs a caster's spell
    attacks and save DCs is a per-CLASS mapping (cleric -> wis, wizard -> int,
    druid -> wis, ...), read from the caster's class doc's
    ``spellcasting.ability``. Returns ``None`` when the caster has no
    ``class_slug``, the class is unknown to the lib, or the class carries no
    spellcasting ability (a non-caster class) — callers fall back to the
    legacy flat approximation in that case."""
    if not caster.class_slug:
        return None
    cls = get_lib_loader().get_class(caster.class_slug)
    if cls is None or not cls.spellcasting.ability:
        return None
    return cls.spellcasting.ability


def _resolve_intent_activities(
    intent: PlayerIntent, feature_invocation: _FeatureInvocation | None, caster: Combatant
) -> _ResolvedActivities:
    """Fetch the typed entity for the intent's kind from the lib loader and
    collect the activities the resolver will walk. This is the sole PC
    resolution path; the old the legacy evaluator IR path was retired in ."""
    cast_spell: Spell | None = None
    fetched_weapon: Weapon | None = None
    activities: list[Any] = []
    spellcasting_ability: str | None = None
    # The owner entity's PassiveEffect definitions, threaded into the context so
    # an activity's effect riders (``activity.effects[].id``) resolve to a runtime
    # ActiveEffect. A spell carries them on ``Spell.passive_effects``; a feature
    # (Rage) on ``Feature.passive_effects``. Empty for kinds with no rider source.
    feature_passive_effects: list[Any] = []
    if intent.intent_type == "attack" and intent.weapon_id:
        fetched_weapon = get_lib_loader().get_weapon(intent.weapon_id)
        if fetched_weapon is not None:
            activities = list(fetched_weapon.activities)
            # SRD §Weapon Attacks — most mundane weapons ship the AttackActivity
            # on ``Weapon.activities``; a handful of magic weapons whose attack
            # rides their base weapon ship empty activities. Synthesize one from
            # the weapon's ``damage_parts`` so a swing still resolves (parity
            # with the OLD ``_synthesize_weapon_attack``).
            if not activities:
                activities = [_synthesize_attack_from_weapon(fetched_weapon)]
    elif intent.intent_type == "cast_spell" and intent.spell_id:
        cast_spell = get_lib_loader().get_spell(intent.spell_id)
        if cast_spell is not None:
            activities = list(cast_spell.activities)
            # SRD 5.2 §Spellcasting — the real class->ability mapping
            # (cleric -> wis, wizard -> int, ...), read off the caster's own
            # class doc. ``None`` (unknown class / non-caster class) falls
            # back to the legacy flat approximation in ``build_context.py``.
            spellcasting_ability = _resolve_caster_spellcasting_ability(caster)
    elif intent.intent_type == "use_item" and intent.item_id:
        # Parity with the OLD resolver's ``use_item`` branch: an item (potion,
        # scroll, wand) may carry its own activities — most often a
        # ``CastActivity`` that delegates to a referenced spell. Fetch the
        # typed item and resolve its activities directly. ``get_item`` spans
        # Item/Weapon/Armor/MagicItem, all of which inherit ``activities``.
        fetched_item = get_lib_loader().get_item(intent.item_id)
        if fetched_item is not None:
            if intent.activity_id:
                activities = [a for a in fetched_item.activities if a.id == intent.activity_id]
            else:
                # C2: an unselected use_item must resolve the SAME single
                # activity ``_item_charge_activity`` will charge — resolving
                # every activity on the item (the old behavior) emits events
                # for activities that were never paid for (wand-of-binding:
                # both Hold Monster AND Hold Person fired while only Hold
                # Monster's 5 charges were spent). An item with no consuming
                # activity (nothing prices > 0 itemUses) has nothing for
                # ``_item_charge_activity`` to select — keep the pre-existing
                # resolve-all behavior for that case.
                charged = _item_charge_activity(fetched_item, None)
                activities = [charged] if charged is not None else list(fetched_item.activities)
    elif intent.feature_id:
        # USE_FEATURE — the feature was already resolved to its single concrete
        # activity (repertoire gate + single-activity validation) above, BEFORE
        # any action-economy budget was consumed. A rejected / no-op feature
        # returned early there; reaching here means ``feature_invocation`` holds
        # the resolved activity + its PassiveEffect riders.
        assert feature_invocation is not None
        activities = feature_invocation.activities
        feature_passive_effects = feature_invocation.passive_effects
    return _ResolvedActivities(
        activities=activities,
        cast_spell=cast_spell,
        fetched_weapon=fetched_weapon,
        spellcasting_ability=spellcasting_ability,
        feature_passive_effects=feature_passive_effects,
    )


def _build_cast_spell_book(activities: Sequence[Any]) -> dict[str, Spell]:
    """uuid -> Spell map for the ``cast`` activities among the resolved
    intent's activities — the delegation seam a scroll/wand's ``CastActivity``
    (``activities/cast.py``) looks its referenced spell up in. A miss (an
    absent uuid, or one the lib can't resolve) stays out of the book; it is
    never silent — ``resolve_cast`` logs ``cast_spell_unresolved`` on a
    lookup failure."""
    book: dict[str, Spell] = {}
    loader = get_lib_loader()
    for activity in activities:
        uuid = getattr(getattr(activity, "spell", None), "uuid", "")
        if not uuid or uuid in book:
            continue
        spell = loader.get_spell_by_uuid(uuid)
        if spell is not None:
            book[uuid] = spell
    return book


def _item_cast_level_override(intent: PlayerIntent) -> int | None:
    """The forced cast level a ``use_item`` charges_to_spend request implies
    for the ``cast`` activity being charged, or ``None`` when no override
    applies (no charges_to_spend, or the charged activity doesn't delegate a
    cast).

    SRD §Casting a Spell at a Higher Level — the extra charges spent above
    the wrapper's own base cost fund a level bump: ``base_level + (requested
    - base_cost)``. ``base_level`` is the wrapper's own ``spell.level``
    override (never the referenced spell's base level — a scroll/wand casts
    AT its own printed level by default); ``base_cost`` is the SAME
    itemUses cost ``_item_charge_gate`` priced this invocation against.

    C2/M2: reuses ``_item_charge_activity`` directly (via a fresh
    ``get_lib_loader().get_item`` lookup) instead of a private
    re-implementation of its selection rule, so the level override and the
    charge gate can never disagree on which activity is being charged.
    """
    if intent.intent_type != "use_item" or intent.charges_to_spend is None or not intent.item_id:
        return None
    item = get_lib_loader().get_item(intent.item_id)
    if item is None:
        return None
    activity = _item_charge_activity(item, intent.activity_id)
    if activity is None or getattr(activity, "kind", "") != "cast":
        return None
    base_level = activity.spell.level
    if base_level is None:
        return None
    # M2: no ``or 1`` fallback — after I1/I3 this path only ever reaches a
    # "cast" kind activity with a positive itemUses cost, so
    # ``_activity_item_use_cost``'s value is used as-is and can never
    # disagree with what ``_resolve_charge_request`` priced.
    base_cost = _activity_item_use_cost(item.slug, activity)
    return int(base_level) + (intent.charges_to_spend - base_cost)


def _resolve_targets(
    live: _LiveCombat,
    current: Combatant,
    intent: PlayerIntent,
    activities: list[Any],
    cast_spell: Spell | None,
) -> list[Combatant]:
    """SRD §Areas of Effect / §Range: Self — resolve the target list. An AoE
    cast expands through ``_expand_aoe_target_list`` (on the grid: every
    creature standing in a cell of the measured template that has line of
    effect from the point of origin; on the legacy zone graph: every creature
    in the anchor zone). Otherwise the named target is used, defaulting to the
    caster for an effect-bearing self/targetless buff or a self-targeting
    feature."""
    targets: list[Combatant]
    if intent.intent_type == "cast_spell" and _typed_spell_broadcasts(activities):
        targets = _expand_aoe_target_list(live, current, intent, activities)
    else:
        targets = [c for c in live.initiative if c.entity_id == intent.target_id]
        # SRD §Range: Self — an effect-bearing self/targetless buff (Shield,
        # Mirror Image, Disguise Self) names no foe, so the named-target filter
        # above yields []. Its riders would then apply to nobody and the buff
        # would silently do nothing. Default the target to the caster. AoE
        # (handled above) and single-target casts (target_id present) are
        # untouched.
        if (
            (
                not targets
                and intent.intent_type == "cast_spell"
                and _activities_bear_effects(activities)
                and _spell_is_self_or_targetless(cast_spell, intent.target_id)
            )
            or (
                not targets
                and intent.feature_id
                and activities
                and _activities_target_self(activities)
            )
            or (
                # SRD §Channel Divinity, Divine Spark (Heal) — a feature heal that
                # names no target defaults to the caster (you use the healing option
                # on yourself). Scoped to feature invocations with no named target
                # and only heal-kind activities, so an offensive feature activity
                # (Divine Spark: Save) with no target still resolves to nobody.
                not targets
                and intent.feature_id
                and intent.target_id is None
                and bool(activities)
                and all(getattr(a, "kind", None) == "heal" for a in activities)
            )
        ):
            targets = [current]
    return targets


# ── pre-armed reaction queue ─────────────────────────────────────
#
# See docs/dev/reaction-queue.md for the full design. This section holds the
# shared drain/fire machinery; the per-reaction call sites live inline in
# submit_player_intent / advance_monster_turn / _handle_move below.


def _register_pending_reaction(live: _LiveCombat, actor_id: str, intent: PlayerIntent) -> None:
    """SRD §Ready — register a ``"ready"`` intent's pre-armed reaction.

    Replaces any prior pending entry for the same owner (a combatant has one
    Action per turn, so at most one freshly-armed reaction at a time — see
    docs/dev/reaction-queue.md, "Queue data structure"). No-op for any other
    intent type or a ``"ready"`` without a ``reaction_trigger``.
    """
    if intent.intent_type != "ready" or intent.reaction_trigger is None:
        return
    live.pending_reactions = [pr for pr in live.pending_reactions if pr.owner_id != actor_id]
    live.pending_reactions.append(
        _PendingReaction(
            owner_id=actor_id,
            trigger=intent.reaction_trigger,
            spell_id=intent.spell_id,
            slot_level=intent.slot_level,
        )
    )


def _drain_pre_resolution_reactions(
    live: _LiveCombat,
    current: Combatant,
    intent: PlayerIntent,
    targets: Sequence[Combatant],
) -> set[str]:
    """Drain target-owned pending reactions for a resolving PC intent.

    ``"attack"`` intents fire ``hit_by_attack`` reactions (Shield's +5 AC
    lands before the hit/miss comparison); a ``magic-missile`` cast fires
    ``targeted_by_magic_missile`` reactions, returning the target ids whose
    reaction fired so the caller can inject the force carve-out. Every
    other intent drains nothing (the overwhelmingly common case).
    """
    if intent.intent_type == "attack":
        _drain_targeted_reactions(
            live,
            trigger="hit_by_attack",
            triggering_actor_id=current.entity_id,
            targets=targets,
        )
        return set()
    if intent.intent_type == "cast_spell" and intent.spell_id == "magic-missile":
        return _drain_targeted_reactions(
            live,
            trigger="targeted_by_magic_missile",
            triggering_actor_id=current.entity_id,
            targets=targets,
        )
    return set()


def _apply_magic_missile_shield_carveout(
    payload: dict[str, Any], shielded_target_ids: set[str]
) -> None:
    """SRD Shield — *"...and you take no damage from Magic Missile."*

    Inject a transient ``"force"`` immunity entry into the (per-resolution,
    never persisted) hydration payload for each target whose Shield reaction
    just fired against a Magic Missile trigger.
    ``activities/apply.py::apply_damage`` already merges the sidecar's
    ``immunities`` list unconditionally, flooring the rolled force damage to
    ``0`` (still emitting ``DamageApplied(amount=0)`` per that module's
    "never a suppressed event" contract). Deliberately spell-slug-scoped —
    NOT a general force-immunity mechanic (docs/dev/reaction-queue.md,
    "Magic Missile carve-out").
    """
    for target_id in shielded_target_ids:
        entry = payload["passive_damage_modifiers"].setdefault(target_id, {})
        immunities = list(entry.get("immunities", ()))
        if "force" not in immunities:
            immunities.append("force")
        entry["immunities"] = immunities


def _pop_pending_reaction(
    live: _LiveCombat,
    trigger: ReactionTrigger,
    *,
    triggering_actor_id: str,
    only_owner_id: str | None = None,
) -> _PendingReaction | None:
    """SRD §Reactions — pop the first pending reaction matching ``trigger``,
    scanning ``live.initiative`` in INITIATIVE ORDER (the documented firing
    order when multiple reactions could match one trigger). A candidate
    reactor must not be the triggering actor themselves, must match
    ``only_owner_id`` when given (the ``hit_by_attack`` /
    ``targeted_by_magic_missile`` triggers are owned by the creature actually
    under attack/targeted, not any bystander), must be alive, and must have
    ``reaction_available``. Removes + returns the match (a reaction fires — and
    is spent — at most once); ``None`` when nothing qualifies.
    """
    for reactor in live.initiative:
        if reactor.entity_id == triggering_actor_id:
            continue
        if only_owner_id is not None and reactor.entity_id != only_owner_id:
            continue
        if not reactor.is_alive or reactor.hp_current <= 0:
            continue
        # SRD 5.2 Incapacitated — no Reaction (so no opportunity attack either).
        if conditions_block_actions(_condition_names(reactor)):
            continue
        if not reactor.reaction_available:
            continue
        match = next(
            (
                pr
                for pr in live.pending_reactions
                if pr.owner_id == reactor.entity_id and pr.trigger == trigger
            ),
            None,
        )
        if match is not None:
            live.pending_reactions.remove(match)
            return match
    return None


def _resolve_readied_spell_cast(
    live: _LiveCombat, reactor: Combatant, popped: _PendingReaction
) -> None:
    """Auto-fire a pre-armed reaction spell (Shield) as a full self-cast.

    Consumes the reactor's Reaction + spell slot, emits ``ReactionTriggered``,
    then resolves the spell's own activities against the reactor as sole
    target through the SAME typed resolver every on-turn cast uses — no
    bespoke Shield-only mechanics. Any ``EffectApplied`` this produces on the
    reactor with a round-scoped duration is registered for the off-turn
    expiry fix (``reaction_effects_pending_expiry`` — see
    ``docs/dev/reaction-queue.md``), since the reactor is by construction NOT
    the active turn-actor when a reaction fires.
    """
    spell = get_lib_loader().get_spell(popped.spell_id or "")
    if spell is None:
        return

    for idx, c in enumerate(live.initiative):
        if c.entity_id == reactor.entity_id:
            live.initiative[idx] = c.model_copy(update={"reaction_available": False})
            break

    slot_level = popped.slot_level if popped.slot_level is not None else spell.level
    if spell.level > 0:
        slots = live.spell_slots_by_entity.get(reactor.entity_id, {})
        if slots.get(slot_level, 0) > 0:
            slots[slot_level] = slots[slot_level] - 1

    _emit(
        live,
        ReactionTriggered(
            actor_id=reactor.entity_id,
            reaction_name=popped.spell_id or "",
            trigger_event_uuid="",
        ),
    )

    spellcasting_ability = _resolve_caster_spellcasting_ability(reactor)
    payload = _build_hydration_payload(live, caster=reactor)
    actx = build_activity_context(
        reactor,
        [reactor],
        rng=live.rng,
        event_emitter=lambda ev: _emit(live, ev),
        slot_level=slot_level,
        base_spell_level=spell.level,
        spellcasting_ability=spellcasting_ability,
        concentration=spell.concentration,
        source_passive_effects=list(spell.passive_effects),
        # Monster/reaction paths don't delegate casts yet — PC-path
        # delegation lives in _build_cast_spell_book; extending it here is a
        # recorded follow-up.
        spell_book={},
        passive_damage_modifiers=payload["passive_damage_modifiers"],
        save_modifiers=payload["save_modifiers"],
        check_modifiers=payload["check_modifiers"],
        d20_test_penalty=payload["d20_test_penalty"],
        target_distance_ft=_target_distance_map(live, reactor.entity_id, [reactor]),
        attacker_grappler_id=_condition_source_entity(live, reactor, "grappled"),
    )
    pre_event_count = len(live.event_log)
    for activity in spell.activities:
        resolve_activity(activity, actx, weapon=None)

    for ev in live.event_log[pre_event_count:]:
        if (
            isinstance(ev, EffectApplied)
            and ev.effect.target_id == reactor.entity_id
            and ev.effect.duration.rounds is not None
        ):
            live.reaction_effects_pending_expiry.setdefault(reactor.entity_id, []).append(
                (ev.effect.target_id, ev.effect.id, ev.effect.origin)
            )


def _drain_targeted_reactions(
    live: _LiveCombat,
    *,
    trigger: ReactionTrigger,
    triggering_actor_id: str,
    targets: Sequence[Combatant],
) -> set[str]:
    """Pop + fully resolve one matching reaction per entry in ``targets``
    (each target can own at most one match). Returns the set of target
    entity_ids whose reaction fired — Shield vs. Magic Missile's force
    carve-out needs to know which targets just got shielded."""
    fired: set[str] = set()
    for target in targets:
        popped = _pop_pending_reaction(
            live,
            trigger,
            triggering_actor_id=triggering_actor_id,
            only_owner_id=target.entity_id,
        )
        if popped is None:
            continue
        reactor = _find_combatant(live, popped.owner_id)
        if reactor is None:
            continue
        _resolve_readied_spell_cast(live, reactor, popped)
        fired.add(target.entity_id)
    return fired


def _drain_counterspell_reaction(
    live: _LiveCombat, current: Combatant, actor_id: str, intent: PlayerIntent
) -> bool:
    """SRD 5.2 Counterspell — pop a pending ``"cast_spell"``-trigger reaction
    (if any) and resolve it against ``current`` (the interrupted caster) via
    Counterspell's OWN canonical ``save``-kind activity, through the
    existing, unmodified ``activities/save.py`` resolver.

    Returns ``True`` iff the triggering cast was countered (``CastFailed``
    emitted + the turn already advanced) — the caller must return
    immediately, BEFORE ``_consume_spell_slot`` ever runs for the triggering
    spell (this is what preserves the interrupted caster's slot — see
    ``docs/dev/reaction-queue.md``, "Slot-consumption redesign"). ``False``
    means no reaction fired OR the save succeeded; either way the triggering
    cast proceeds exactly as if this function had never been called.
    """
    if intent.intent_type != "cast_spell" or not intent.spell_id:
        return False
    popped = _pop_pending_reaction(live, "cast_spell", triggering_actor_id=actor_id)
    if popped is None:
        return False
    reactor = _find_combatant(live, popped.owner_id)
    if reactor is None:
        return False
    counterspell = get_lib_loader().get_spell(popped.spell_id or "counterspell")
    if counterspell is None:
        return False
    save_activity = next((a for a in counterspell.activities if isinstance(a, SaveActivity)), None)
    if save_activity is None:
        return False

    # Counterspell's OWN slot is spent whether or not it succeeds — only the
    # INTERRUPTED spell's slot is conditionally preserved, below.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == reactor.entity_id:
            live.initiative[idx] = c.model_copy(update={"reaction_available": False})
            break
    cs_level = popped.slot_level if popped.slot_level is not None else counterspell.level
    if counterspell.level > 0:
        reactor_slots = live.spell_slots_by_entity.get(reactor.entity_id, {})
        if reactor_slots.get(cs_level, 0) > 0:
            reactor_slots[cs_level] = reactor_slots[cs_level] - 1

    _emit(
        live,
        ReactionTriggered(
            actor_id=reactor.entity_id,
            reaction_name=popped.spell_id or "counterspell",
            trigger_event_uuid="",
        ),
    )

    reactor_spellcasting_ability = _resolve_caster_spellcasting_ability(reactor)
    payload = _build_hydration_payload(live, caster=reactor)
    actx = build_activity_context(
        reactor,
        [current],
        rng=live.rng,
        event_emitter=lambda ev: _emit(live, ev),
        slot_level=cs_level,
        base_spell_level=counterspell.level,
        spellcasting_ability=reactor_spellcasting_ability,
        concentration=False,
        source_passive_effects=list(counterspell.passive_effects),
        # Monster/reaction paths don't delegate casts yet — PC-path
        # delegation lives in _build_cast_spell_book; extending it here is a
        # recorded follow-up.
        spell_book={},
        passive_damage_modifiers=payload["passive_damage_modifiers"],
        save_modifiers=payload["save_modifiers"],
        check_modifiers=payload["check_modifiers"],
        d20_test_penalty=payload["d20_test_penalty"],
        target_distance_ft=_target_distance_map(live, reactor.entity_id, [current]),
        attacker_grappler_id=_condition_source_entity(live, reactor, "grappled"),
    )
    pre_event_count = len(live.event_log)
    resolve_activity(save_activity, actx, weapon=None)
    save_events = [
        ev
        for ev in live.event_log[pre_event_count:]
        if isinstance(ev, SaveRolled) and ev.target_id == current.entity_id
    ]
    succeeded = save_events[-1].succeeded if save_events else True
    if succeeded:
        return False

    _emit(
        live,
        CastFailed(
            actor_id=actor_id,
            spell_id=intent.spell_id or "",
            reason="countered",
        ),
    )
    _end_turn_and_advance(live, actor_id)
    return True


async def _dispatch_turn_nonending_intent(
    live: _LiveCombat, current: Combatant, intent: PlayerIntent
) -> bool:
    """Dispatch the turn-non-ending intents; return ``True`` when handled.

    SRD §Action Economy — these intents keep the actor on turn (no
    ``_end_turn_and_advance``); the actor may follow with another intent:

    * ``move_mark`` — SRD §Hunter's Mark: *"If the target drops to 0 Hit
      Points before this spell ends, you can take a Bonus Action to move
      the mark to a new creature you can see within range."* A narrow seam:
      no IR evaluation, no slot consumption, no concentration re-check.
    * ``move`` — SRD §Movement: step to an adjacent zone, paying the edge's
      ``distance_ft`` from the per-turn movement budget (movement is
      interleaved with Actions / Bonus Actions). Rejections emit
      ``MoveFailed`` without mutating budget or position.
    * ``dash`` — SRD §Dash: spend the Action (or, for Rogues with Cunning
      Action, the Bonus Action) to add ``base_speed`` to the movement
      budget. Rejections raise ``IntentRejectedError("no_action_economy")``.
    * ``disengage`` — SRD §Disengage: spend the Action; movement provokes
      no Opportunity Attacks for the rest of the turn. Like Dash, keeps
      the actor on turn so a same-turn Disengage→Move sequence works
      ; closes the discovered turn-ending fall-through where
      "disengage" fell through to the generic Action tail that
      unconditionally calls ``_end_turn_and_advance``).
    """
    if intent.intent_type == "move_mark":
        await _handle_move_mark(live, current, intent)
        return True
    if intent.intent_type == "move":
        _handle_move(live, current, intent)
        return True
    if intent.intent_type == "dash":
        _handle_dash(live, current, intent)
        return True
    if intent.intent_type == "disengage":
        _handle_disengage(live, current, intent)
        return True
    return False


async def submit_player_intent(
    handle: CombatHandle,
    actor_id: str,
    intent: PlayerIntent,
) -> None:
    """Accept a PC intent for the current turn, validate it, resolve it.

    Validation:
      - ``actor_id`` must be in the live combat's initiative order
      - it must currently be ``actor_id``'s turn
      - combat must not have ended

    On success: emit ``IntentSubmitted``, fetch the typed entity for the
    intent from the lib loader, and walk its activities through the per-kind
    resolvers under ``activities``, emitting the resulting
    ``CombatEvent`` stream.
    """
    live = _get_live(handle)
    current = _validate_intent_preconditions(live, handle, actor_id, intent=intent)

    # Turn-non-ending intents (move_mark / move / dash) dispatch through
    # their dedicated handlers and keep the actor on turn — see
    # ``_dispatch_turn_nonending_intent``'s docstring for the SRD framing
    # of each.
    if await _dispatch_turn_nonending_intent(live, current, intent):
        return

    # USE_FEATURE — resolve the feature to its single concrete activity BEFORE
    # any action-economy budget is consumed. A gate-rejected or multi-activity
    # no-op feature returns ``None`` (after a loud, tracked warning) and the turn
    # stays untouched: no Bonus Action / Action spent, no IntentSubmitted emitted,
    # turn preserved. This ordering is the fix for the economy bug where a
    # rejected feature still spent the Bonus Action.
    feature_invocation: _FeatureInvocation | None = None
    if intent.feature_id:
        feature_invocation = _resolve_feature_invocation(
            current, intent.feature_id, intent.activity_id
        )
        if feature_invocation is None:
            return

    # SRD §Limited-Use Features / §Item Charges — a capped feature
    # (Second Wind) rejects when its per-rest uses are exhausted with no
    # intervening rest; a capped item (Pipes of Haunting) rejects when its
    # charge pool cannot cover this invocation's cost. Checked BEFORE any
    # budget consumption (mirroring the bonus-action gate): a rejected
    # invocation spends no Action/Bonus Action. The matching spend is
    # recorded only once the invocation is committed to resolving (below).
    if _gate_feature_and_item_uses(live, actor_id, intent, feature_invocation):
        return

    # SRD §Action Economy — classify the action cost BEFORE emitting
    # IntentSubmitted so a budget-exhausted intent doesn't pollute the
    # event log with a half-completed cast. Cast spells consult their
    # asset's typed ``casting_time.unit`` (ACTION / BONUS / REACTION);
    # non-cast intents (attack, dash, etc.) are always Actions on this
    # path. Reactions never come through here — they arrive via a future
    # off-turn intent path; treat REACTION as a routing error and surface
    # it as CastFailed.
    #
    # Reactions don't have a dedicated off-turn intent path yet (deferred
    # to the reaction-flow piece). Until then submit_player_intent is the
    # only ingress; consume ``reaction_available`` and otherwise advance
    # the turn like an Action so existing reaction-spell scenarios keep
    # working. The proper off-turn path will reject reactions through
    # this entrypoint.
    action_cost = _classify_action_cost(intent, feature_invocation)
    cast_spell_for_timing = action_cost.cast_spell_for_timing
    is_bonus_action = action_cost.is_bonus_action
    is_reaction_cast = action_cost.is_reaction_cast

    # Pre-resolution reject gates — each checked BEFORE any action budget is
    # consumed, so a rejection spends no Action/Bonus Action/slot and leaves
    # the turn untouched. Order matters and is preserved from the original
    # sequential if-chain: spell range (SRD §Spell Range) -> weapon reach
    # (SRD §Weapon Reach / Range) -> Charmed target (SRD 5.2 "You can't
    # attack the charmer or target the charmer with damaging abilities or
    # magical effects") -> pre-slot ``target_invalid`` (Hellish Rebuke's fixed
    # target, SRD §Hellish Rebuke; an unaimed Cone/Line/Cube AoE template).
    # The first gate whose failure-builder returns a non-``None`` event
    # wins; that event is emitted and the intent is rejected.
    pre_resolution_gates: tuple[Callable[[], CombatEvent | None], ...] = (
        lambda: _spell_out_of_range_failure(live, actor_id, intent, cast_spell_for_timing),
        lambda: _attack_out_of_range_failure(live, actor_id, intent),
        lambda: _charmed_target_failure(live, actor_id, current, intent),
        lambda: _cast_target_invalid_failure(
            live, current, actor_id, intent, cast_spell_for_timing
        ),
    )
    for build_pre_resolution_failure in pre_resolution_gates:
        failure = build_pre_resolution_failure()
        if failure is not None:
            _emit(live, failure)
            return

    if is_bonus_action:
        if not current.bonus_action_available:
            _emit(
                live,
                CastFailed(
                    actor_id=current.entity_id,
                    spell_id=intent.spell_id or "",
                    reason="no_action_economy",
                ),
            )
            return
    elif is_reaction_cast:
        if not current.reaction_available:
            _emit(
                live,
                CastFailed(
                    actor_id=current.entity_id,
                    spell_id=intent.spell_id or "",
                    reason="no_action_economy",
                ),
            )
            return
    else:
        if not current.action_available:
            if intent.intent_type == "cast_spell":
                _emit(
                    live,
                    CastFailed(
                        actor_id=current.entity_id,
                        spell_id=intent.spell_id or "",
                        reason="no_action_economy",
                    ),
                )
                return
            raise IntentRejectedError(
                "no_action_economy",
                f"actor_id={actor_id!r} has no Action remaining this turn",
            )

    # Consume the budget now. ``current`` is a stale snapshot; mutate via
    # initiative-list model_copy so subsequent reads (and the post-resolve
    # turn-advance branch below) see the updated state.
    current = _consume_action_budget(live, actor_id, action_cost)

    _emit(
        live,
        IntentSubmitted(
            actor_id=actor_id,
            intent_type=intent.intent_type,
            spell_id=intent.spell_id,
            target_id=intent.target_id,
            item_id=intent.item_id,
        ),
    )

    # SRD §Ready — a "ready" intent pre-arms the pending-reaction queue
    # (docs/dev/reaction-queue.md): the Action is spent NOW (the budget
    # consumption above), the Reaction later, when the trigger fires.
    # Registration draws no dice and resolves no activities; the generic
    # tail below advances the turn exactly as for any other Action. No-op
    # for every other intent type (guard inside the helper).
    _register_pending_reaction(live, actor_id, intent)

    # SRD §Reactions — a 1-reaction-class cast consumes the actor's
    # reaction. Emit ReactionTriggered so downstream consumers (UI,
    # reaction-pool accounting, future off-turn polling) can observe the
    # spend. ``trigger_event_uuid`` is empty until a proper trigger model
    # threads the originating event UUID through.
    if is_reaction_cast:
        _emit(
            live,
            ReactionTriggered(
                actor_id=actor_id,
                reaction_name=intent.spell_id or "",
                trigger_event_uuid="",
            ),
        )

    # SRD 5.2 Counterspell — drain a pending "cast_spell" reaction BEFORE
    # the slot gate: a countered cast never reaches ``_consume_spell_slot``,
    # so the interrupted caster's slot is never expended ; see
    # docs/dev/reaction-queue.md, "Slot-consumption redesign"). Returns True
    # iff the cast was countered — CastFailed(reason="countered") emitted
    # and the turn already advanced (the wasted action).
    if _drain_counterspell_reaction(live, current, actor_id, intent):
        return

    # SRD §Spellcasting — Spell Slots. Gate + decrement live on the
    # orchestrator; a rejected cast emits ``CastFailed`` + advances the turn
    # and signals the caller to return.
    if _consume_spell_slot(live, current, actor_id, intent):
        return

    # SRD §Limited-Use Features — every action-economy / slot gate has
    # passed and the invocation is now committed to resolving; record the spend on
    # the caster's per-rest use counter so a later same-rest invocation rejects
    # above. The early gate rejects an over-cap invocation before reaching here, so
    # this only increments a within-cap use (no-op for uncapped / non-feature intents).
    _record_capped_feature_use(live, actor_id, intent.feature_id, feature_invocation)

    # SRD §Item Charges — the item-charge gate above has passed; commit the
    # spend on the actor's per-rest charge counter (no-op for uncapped /
    # non-use_item intents).
    _record_item_charge_spend(live, actor_id, intent)

    # ── Typed-Activity resolution (Foundry cutover, ─────────────
    #
    # Fetch the typed entity for the intent's kind from the lib loader and
    # collect the activities the resolver will walk. This is the sole PC
    # resolution path; the old the legacy evaluator IR path was retired in .
    resolved = _resolve_intent_activities(intent, feature_invocation, current)
    activities = resolved.activities
    cast_spell = resolved.cast_spell
    fetched_weapon = resolved.fetched_weapon
    spellcasting_ability = resolved.spellcasting_ability
    feature_passive_effects = resolved.feature_passive_effects

    # SRD §Areas of Effect — fireball / burning-hands hit every creature in
    # the targeted zone. The AoE discriminator is the typed activity's measured
    # ``target.template`` -A): the lib's converter now surfaces Foundry's
    # measured-template block onto each creature-targeting activity, so a spell
    # whose resolving activity carries a template shape (Fireball sphere/20,
    # Burning Hands cone/15) broadcasts to the zone, while a template-less spell
    # (Sacred Flame, Cure Wounds, Magic Missile, Detect Thoughts' single save)
    # stays single-target. No the legacy evaluator-wrapper read.
    targets = _resolve_targets(live, current, intent, activities, cast_spell)

    # SRD §Reactions — drain any pending target-owned reactions (Shield)
    # BEFORE the sidecar projection below, so a just-applied reaction effect
    # (Shield's +5 AC) folds into this very resolution's hydration payload
    # . Returns the target ids whose reaction fired against a
    # Magic Missile trigger — needed for the carve-out injection below.
    shielded_vs_magic_missile = _drain_pre_resolution_reactions(live, current, intent, targets)

    # The orchestrator already owns the per-entity passive sidecars; project
    # them once and hand the two dicts ``build_activity_context`` needs in
    # (it stays pure — no orchestrator import, no double-compute).
    payload = _build_hydration_payload(live, caster=current)

    # SRD Shield — *"...and you take no damage from Magic Missile."* Inject
    # the transient, spell-slug-scoped force carve-out into THIS payload only
    # (rebuilt fresh per resolution; nothing persists). No-op for an empty
    # set (guard inside the helper).
    _apply_magic_missile_shield_carveout(payload, shielded_vs_magic_missile)

    pre_event_count = len(live.event_log)

    if not activities:
        # Slug absent from the lib (e.g. a wrapper-only spell) or a non-
        # resolving intent kind. Emit nothing, but log the loss — never a
        # silent no-op. The divergence triage classifies these.
        if intent.intent_type == "cast_spell" and intent.spell_id:
            _LOGGER.warning("activity_resolution_empty slug=%s", intent.spell_id)
        elif intent.intent_type == "attack" and intent.weapon_id:
            _LOGGER.warning("activity_resolution_empty slug=%s", intent.weapon_id)
        elif intent.intent_type == "use_item" and intent.item_id:
            _LOGGER.warning("activity_resolution_empty slug=%s", intent.item_id)
    else:
        # Pre-resolve the caster's ScaleValue magnitudes + class levels at the
        # seam (loader access here), passing plain data into the pure
        # ``build_activity_context``. ``@scale.*`` / ``@classes.<class>.levels``
        # formula tokens read these carriers — the formula resolver never
        # touches a loader. The species slug threads through so species @scale
        # tables (e.g. Dragonborn breath) resolve alongside class + subclass.
        scale_values = build_scale_values(
            class_slug=current.class_slug,
            subclass_slug=current.subclass_slug,
            species_slug=current.species_slug,
            level=current.character_level,
            loader=get_lib_loader(),
        )
        class_levels = {current.class_slug: current.character_level} if current.class_slug else {}
        target_unseen, attacker_unseen_by = _target_visibility_maps(live, current, targets)
        actx = build_activity_context(
            current,
            targets,
            rng=live.rng,
            event_emitter=lambda ev: _emit(live, ev),
            slot_level=intent.slot_level,
            base_spell_level=cast_spell.level if cast_spell is not None else None,
            spellcasting_ability=spellcasting_ability,
            concentration=cast_spell.concentration if cast_spell is not None else False,
            source_passive_effects=(
                list(cast_spell.passive_effects) if cast_spell else feature_passive_effects
            ),
            # ``spell_book`` is the Foundry-uuid → Spell map a ``CastActivity``
            # delegates through (scroll/wand casting a referenced spell) — the
            # real uuid→Spell resolution over THIS invocation's own resolved
            # activities. A miss is not silent: ``resolve_cast``
            # (activities/cast.py) logs ``cast_spell_unresolved uuid=...`` at
            # WARNING and returns.
            spell_book=_build_cast_spell_book(activities),
            # SRD §Casting a Spell at a Higher Level — a charges_to_spend
            # ``use_item`` upcast forces the delegated cast to the level the
            # extra charges paid for; ``None`` (the common case) lets
            # ``resolve_cast`` fall through to the wrapper's own/base level.
            cast_level_override=_item_cast_level_override(intent),
            passive_damage_modifiers=payload["passive_damage_modifiers"],
            save_modifiers=payload["save_modifiers"],
            check_modifiers=payload["check_modifiers"],
            d20_test_penalty=payload["d20_test_penalty"],
            # SRD 5.2 §Cover — an area of effect measures cover from its point
            # of origin, which for a target-origin template is NOT the caster's
            # cell. ``None`` for every non-AoE cast/attack ⇒ caster's cell. The
            # degenerate case where that point of origin coincides with the
            # target's own cell (a small sphere centred on the lone creature it
            # affects) is handled inside ``_target_cover_map`` itself — see its
            # docstring — rather than by special-casing the call here.
            target_cover=_target_cover_map(
                live,
                current.entity_id,
                targets,
                origin_cell=(
                    _aoe_cover_origin(live, current.entity_id, intent, activities)
                    if intent.intent_type == "cast_spell" and _typed_spell_broadcasts(activities)
                    else None
                ),
            ),
            target_distance_ft=_target_distance_map(live, current.entity_id, targets),
            attacker_grappler_id=_condition_source_entity(live, current, "grappled"),
            target_unseen=target_unseen,
            attacker_unseen_by=attacker_unseen_by,
            scale_values=scale_values,
            class_levels=class_levels,
            # A FEATURE invocation must not inherit the blanket spell
            # save_dc_override; its save activity computes its own ability+PB DC.
            is_feature_invocation=bool(intent.feature_id),
            # SRD §Advantage / §Sneak Attack — the caster's own active effects
            # (attacker-side advantage flags) plus the two Sneak Attack
            # sidecars: the per-turn "spent" gate rebuilt from the live
            # Combatant flag, and the per-target ally-adjacent predicate (a
            # spatial read owned here, not in the pure resolver).
            active_effects=tuple(live.active_effects.get(current.entity_id, [])),
            sneak_attack_spent={current.entity_id: current.sneak_attack_spent_this_turn},
            sneak_attack_ally_adjacent=_sneak_ally_adjacent_map(live, current, targets),
        )
        for activity in activities:
            resolve_activity(activity, actx, weapon=fetched_weapon)

        # SRD §Sneak Attack, "Once per turn" — record that the rider fired so a
        # (future) second qualifying attack this turn is capped. The rider folds
        # inside the pure resolver; the orchestrator owns the actor-state write.
        # A rider fired iff the caster was sneak-eligible for a hit target this
        # resolution (finesse/ranged weapon + Advantage or an adjacent ally),
        # was not already spent, and at least one target took damage.
        _record_sneak_attack_spent(
            live, current, intent, fetched_weapon, targets, actx, pre_event_count
        )

        # SRD 5.2 §Spell Descriptions — typed forced-movement riders (e.g.
        # Thunderwave's "pushed 10 feet away from you") fire after the
        # save/damage resolution so the push never perturbs the seeded roll
        # order and a target that died is left where it fell.
        _apply_forced_movement_riders(live, current, intent, pre_event_count)

    # SRD §Concentration — fold any emitted ``EffectApplied(is_concentration=True)``
    # back onto the caster's ``Combatant.concentration_effect_id`` so the
    # next hydration projects the existing concentration onto the sidecar
    # (closes the wave-05 one-way wiring). The typed resolver preserves
    # EffectApplied→ConditionApplied emit order, so this seam and
    # ``_record_effect_lifecycle_links`` below keep working unchanged.
    _writeback_concentration(live, current, pre_event_count)

    # Persistent IEffect-graph linkage — record concentration ownership,
    # effect→condition bijection, and any end-of-turn repeat-save specs
    # produced by this resolution. Closes the codex shelf finding
    # ``ieffect2.py`` P1 ("parent links don't survive across turns") by
    # owning the lifecycle graph at the orchestrator.
    _record_effect_lifecycle_links(live, current, pre_event_count)

    # SRD §Hold Person / §Hold Monster — *"At the end of each of its turns,
    # the target repeats the save."* This runs as the ``engine:repeat-save``
    # ``turn_end`` hook inside ``_end_turn_and_advance``, NOT here: a bonus
    # action does not end the turn, so it must not trigger a repeat save.
    #
    # Advance the turn. End-of-round wraps to next round + emits a
    # RoundStarted; a follow-up RoundEnded would land in the cutover
    # path where the evaluator drives the loop. Keeping the additive
    # surface minimal: TurnEnded → TurnStarted (and RoundStarted on
    # wrap) is what a narrator-side consumer needs to see today.
    #
    # SRD §Action Economy — a bonus action does NOT end the turn; the
    # actor keeps initiative and may follow with a regular Action.
    if is_bonus_action:
        _maybe_roll_death_save(live)
        return
    _end_turn_and_advance(live, actor_id)


def _fire_pc_opportunity_attacks_on_move(
    live: _LiveCombat,
    *,
    mover_id: str,
    from_zone: str,
    to_zone: str,
) -> bool:
    """SRD §Opportunity Attacks — fire PC AoOs when ``mover_id`` leaves reach.

    *"You can make an opportunity attack when a hostile creature that you
    can see moves out of your Reach. To make the opportunity attack, you
    use your Reaction to make a single Melee Attack against the provoking
    creature. The attack interrupts the provoking creature's Movement,
    occurring right before the creature leaves your Reach."*

    Phase-6 wires this for the **PC reactor / monster mover** direction
    only — the symmetric monster-AoO path requires the reaction-queue
    machinery deferred to the monster-spellcasting epic (see
    ``BACKLOG.md`` [combat] entry).

    Zone-graph reach approximation: in the current zone model the only
    reach band the orchestrator can resolve cheaply is "same zone" (≤5ft
    melee adjacency). A 10ft-reach AoO from a polearm-wielding PC against
    a mover in an adjacent zone is not modeled here; ``melee_reach_ft``
    on the Combatant is the threshold but the within-range check below
    only fires for same-zone reactors. Extending to adjacent-zone reach
    is a follow-up when the zone graph carries directional
    "melee-adjacent" semantics.

    For each alive PC with reaction available in ``from_zone`` (the zone
    the mover is *leaving*), where ``to_zone`` falls outside the PC's
    ``melee_reach_ft``, fire one AoO:

      * roll d20 + PC.attack_bonus, hit on total ≥ mover.ac (nat 20 crit,
        nat 1 auto-miss — same rules as the regular attack handler);
      * emit ``AttackRolled(is_opportunity_attack=True)``;
      * on hit, roll the PC's ``damage_dice`` and emit ``DamageApplied``
        — ``_emit`` handles HP tracking + synthesizing the ``Death`` if
        the mover drops to 0 HP;
      * consume the PC's ``reaction_available``.

    Returns ``True`` if the mover dropped to 0 HP from any AoO this
    step — the caller cancels the remaining MOVE then (SRD: *"the attack
    interrupts the provoking creature's Movement"*; a dead mover stops
    in place rather than completing the step).
    """
    mover = next((c for c in live.initiative if c.entity_id == mover_id), None)
    if mover is None:
        return False
    mover_died = False
    for idx, reactor in enumerate(live.initiative):
        if reactor.entity_id not in live.party_ids:
            continue
        if not reactor.is_alive or reactor.hp_current <= 0:
            continue
        # SRD 5.2 Incapacitated — no Reaction (so no opportunity attack either).
        if conditions_block_actions(_condition_names(reactor)):
            continue
        if not reactor.reaction_available:
            continue
        if live.actor_zone.get(reactor.entity_id) != from_zone:
            continue
        # Same-zone reach approximation: a 5ft melee reach covers same-zone
        # adjacency; an out-of-zone move always provokes (the mover leaves
        # the reactor's reach band).
        if to_zone == from_zone:
            continue
        # Roll the AoO attack: same rules shape as effects/attack.py — nat 20
        # crit, nat 1 auto-miss, total ≥ AC on hit.
        natural = live.rng.randint(1, 20)
        total = natural + reactor.attack_bonus
        if natural == 20:
            is_crit, is_hit = True, True
        elif natural == 1:
            is_crit, is_hit = False, False
        else:
            is_crit = False
            is_hit = total >= mover.ac
        _emit(
            live,
            IntentSubmitted(
                actor_id=reactor.entity_id,
                intent_type="reaction",
                target_id=mover_id,
            ),
        )
        _emit(
            live,
            AttackRolled(
                attacker_id=reactor.entity_id,
                target_id=mover_id,
                roll_total=total,
                advantage="normal",
                is_crit=is_crit,
                is_hit=is_hit,
                is_opportunity_attack=True,
            ),
        )
        # Consume the reaction regardless of hit/miss (SRD: reactions are
        # spent on use, not on success).
        live.initiative[idx] = reactor.model_copy(update={"reaction_available": False})
        if is_hit:
            damage = _roll_damage_expression(live, reactor.damage_dice, crit=is_crit)
            if damage > 0:
                tracked_before = live.tracked_hp.get(mover_id, mover.hp_current)
                _emit(
                    live,
                    DamageApplied(
                        target_id=mover_id,
                        amount=damage,
                        damage_type=reactor.damage_type,
                        is_overkill=damage > tracked_before,
                    ),
                )
                # _emit synthesizes Death + records dead_ids when tracked HP
                # hits 0 — check that here to cancel the rest of the move.
                if mover_id in live.dead_ids:
                    mover_died = True
                    break
    return mover_died


def _fire_monster_opportunity_attacks_on_move(
    live: _LiveCombat,
    *,
    mover_id: str,
    from_zone: str,
    to_zone: str,
) -> bool:
    """SRD §Opportunity Attacks — fire monster AoOs when a PC leaves reach.

    The monster-reactor / PC-mover mirror of
    ``_fire_pc_opportunity_attacks_on_move`` same hit/crit rules,
    same reaction-consumed-on-use semantics, same
    ``AttackRolled(is_opportunity_attack=True)`` event shape, same same-zone
    reach approximation (see the shipped direction's docstring — extending
    to adjacent-zone ``melee_reach_ft`` reach is a follow-up on BOTH
    directions). An opportunity attack is an always-available reaction gated
    only on ``reaction_available`` — it does NOT go through the pre-armed
    ``pending_reactions`` queue (docs/dev/reaction-queue.md, "Why AoO is not
    a queued reaction").

    One guard the shipped direction does not need: a mover who took the
    Disengage action this turn (``disengaging_this_turn``) never provokes —
    the trigger is suppressed entirely, no reactor spends a Reaction
    .

    Returns ``True`` if the mover dropped to 0 HP from any AoO — the caller
    cancels the move (SRD: *"The attack occurs right before it leaves your
    reach"*; a dead mover stops in place).
    """
    mover = next((c for c in live.initiative if c.entity_id == mover_id), None)
    if mover is None or mover.disengaging_this_turn:
        return False
    mover_died = False
    for idx, reactor in enumerate(live.initiative):
        if reactor.entity_id not in live.encounter_ids:
            continue
        if not reactor.is_alive or reactor.hp_current <= 0:
            continue
        # SRD 5.2 Incapacitated — no Reaction (so no opportunity attack either).
        if conditions_block_actions(_condition_names(reactor)):
            continue
        if not reactor.reaction_available:
            continue
        if live.actor_zone.get(reactor.entity_id) != from_zone:
            continue
        # Same-zone reach approximation: a 5ft melee reach covers same-zone
        # adjacency; an out-of-zone move always provokes (the mover leaves
        # the reactor's reach band).
        if to_zone == from_zone:
            continue
        natural = live.rng.randint(1, 20)
        total = natural + reactor.attack_bonus
        if natural == 20:
            is_crit, is_hit = True, True
        elif natural == 1:
            is_crit, is_hit = False, False
        else:
            is_crit = False
            is_hit = total >= mover.ac
        _emit(
            live,
            IntentSubmitted(
                actor_id=reactor.entity_id,
                intent_type="reaction",
                target_id=mover_id,
            ),
        )
        _emit(
            live,
            AttackRolled(
                attacker_id=reactor.entity_id,
                target_id=mover_id,
                roll_total=total,
                advantage="normal",
                is_crit=is_crit,
                is_hit=is_hit,
                is_opportunity_attack=True,
            ),
        )
        # Consume the reaction regardless of hit/miss (SRD: reactions are
        # spent on use, not on success).
        live.initiative[idx] = reactor.model_copy(update={"reaction_available": False})
        if is_hit:
            damage = _roll_damage_expression(live, reactor.damage_dice, crit=is_crit)
            if damage > 0:
                tracked_before = live.tracked_hp.get(mover_id, mover.hp_current)
                _emit(
                    live,
                    DamageApplied(
                        target_id=mover_id,
                        amount=damage,
                        damage_type=reactor.damage_type,
                        is_overkill=damage > tracked_before,
                    ),
                )
                if mover_id in live.dead_ids:
                    mover_died = True
                    break
    return mover_died


def _roll_damage_expression(live: _LiveCombat, expr: str, *, crit: bool) -> int:
    """Roll an ``XdY+Z`` damage expression with the live RNG.

    Crit doubles dice (SRD §Critical Hits: *"roll all the attack's damage
    dice twice"*); flat modifier is added once. Unparseable expressions
    return 0 — the caller treats that as "no damage applied" rather than
    propagating a parser error mid-turn.
    """
    if not expr:
        return 0
    expr = expr.strip().lower().replace(" ", "")
    # Strip a trailing +N / -N modifier.
    modifier = 0
    sign_idx = max(expr.rfind("+"), expr.rfind("-"))
    if sign_idx > 0:  # >0: leading '-' would mean negative dice count
        try:
            modifier = int(expr[sign_idx:])
            expr = expr[:sign_idx]
        except ValueError:
            return 0
    if "d" not in expr:
        return max(0, modifier)
    count_s, sides_s = expr.split("d", 1)
    try:
        count = int(count_s) if count_s else 1
        sides = int(sides_s)
    except ValueError:
        return 0
    if count <= 0 or sides <= 0:
        return max(0, modifier)
    rolls = count * (2 if crit else 1)
    total = sum(live.rng.randint(1, sides) for _ in range(rolls)) + modifier
    return max(0, total)


async def advance_monster_turn(handle: CombatHandle) -> None:
    """Drive one monster turn through typed selection + the Activity resolver.

    Validation mirrors ``submit_player_intent``:

      - combat must not have ended
      - the current actor must be a non-Character entity (Monster /
        NPC); calling on a PC turn raises ``IntentRejectedError`` so
        the WS-side dispatch can branch on it

    Selection: ``select_typed_monster_action``
    picks an action from the typed ``Monster.actions`` (fetched from the lib
    loader by ``monster_template_slug``); ``expand_action_to_activities`` fans
    multiattack out into its sub-attacks. Targeting: lowest-HP alive PC in
    initiative order (the legacy gambit's ``target_priority="lowest_hp"``
    semantics). Resolution: each returned ``Activity`` runs through
    ``resolve_activity`` against a context
    built by ``build_activity_context`` — the same typed path as the PC
    turn /6 of the Foundry cutover).

    On dead monsters, an unresolvable slug, or no usable action (flee
    threshold, no attack, no PC targets), the orchestrator records
    ``IntentSubmitted(pass)`` and advances the turn without resolving any
    activity — the safe no-op the legacy dispatch also produced.
    """
    live = _get_live(handle)
    if live.ended:
        raise IntentRejectedError("combat_ended", f"handle={handle.handle_id}")

    current = _current_actor(live)
    if current.entity_type == "Character":
        raise IntentRejectedError(
            "not_actor_turn",
            f"current_turn={current.entity_id!r} is a Character, not a monster",
        )

    # Dead / unconscious monsters skip with a no-op record. The legacy
    # behavior-based flee gate (monster_ai.select_monster_action) is reapplied
    # here against the live Combatant — the typed selector only sees the static
    # Monster, so a wounded AGGRESSIVE/RANGED monster would otherwise keep
    # attacking instead of fleeing. A fleeing monster takes the same no-action /
    # pass path dead monsters take.
    skip_to_record_pass = (
        not current.is_alive
        or current.hp_current <= 0
        or _monster_is_fleeing(current)
        # SRD 5.2 Incapacitated — the monster takes no action this turn.
        or conditions_block_actions(_condition_names(current))
    )

    # Build alive-PC target list (lowest_hp priority — the legacy
    # gambit's target rule). Empty targets degrades to pass.
    alive_pcs: list[Combatant] = [
        c
        for c in live.initiative
        if c.entity_id in live.party_ids and c.is_alive and c.hp_current > 0
    ]
    # SRD 5.2 Charmed — "You can't attack the charmer or target the charmer
    # with damaging abilities or magical effects." The player path enforces
    # this as a pre-resolution reject gate (``_charmed_target_failure``); the
    # monster path has no intent to reject, so the charmer is removed from the
    # selectable targets instead. A charmed monster still attacks anyone else;
    # with no other target left it passes the turn. Unknown charmer (no
    # resolvable source) imposes no restriction, exactly as on the player path.
    charmer_id = _condition_source_entity(live, current, "charmed")
    if charmer_id is not None:
        alive_pcs = [c for c in alive_pcs if c.entity_id != charmer_id]
        # Knock-on, accepted deliberately: ``alive_pcs`` is also the threat list
        # ``_execute_flee_retreat`` measures distance against, so a charmed
        # FLEEING monster no longer counts its charmer as someone to run from.
        # Flavour-defensible (you do not flee the creature that has charmed you)
        # and SRD-silent, but it is a second consequence of this one filter.
    if not alive_pcs:
        skip_to_record_pass = True

    chosen_target: Combatant | None = (
        min(alive_pcs, key=lambda c: c.hp_current) if alive_pcs else None
    )

    # ── Fleeing retreat ──────────────────────────────────────────
    # A live monster over the flee threshold spends its movement putting
    # distance between itself and the nearest threat BEFORE the pass is
    # recorded. Selection/attack stay gated off (``skip_to_record_pass`` is
    # already True for a fleeing monster), so the turn still collapses to
    # ``IntentSubmitted(intent_type="pass")`` — but now with real
    # ``ActorMoved`` events preceding it (reusing ``"pass"`` per the catalog;
    # no new IntentType is minted). Dead/unconscious monsters never retreat.
    if current.is_alive and current.hp_current > 0 and _monster_is_fleeing(current):
        _execute_flee_retreat(live, current, alive_pcs)
        current = next(c for c in live.initiative if c.entity_id == current.entity_id)

    # ── Typed-Activity monster resolution (Foundry cutover, ─────────
    #
    # Fetch the typed ``Monster`` from the lib loader, pick its action, and fan
    # out multiattack. This is the sole monster-turn path; the old the legacy evaluator IR
    # path was retired in .
    monster_slug = live.monster_slug_by_entity.get(current.entity_id)
    monster_activities: list[Any] = []
    if not skip_to_record_pass and monster_slug is not None:
        monster = get_lib_loader().get_monster(monster_slug)
        if monster is None:
            # Slug absent from the lib — no action this turn. Loud, never
            # silent; the turn still advances through the pass shape below.
            _LOGGER.warning("monster_unresolved slug=%s", monster_slug)
        else:
            monster_action = select_typed_monster_action(monster)
            if monster_action is not None:
                # hand the labelless-multiattack fallback the live
                # distance + profile so it can prefer a sibling whose own range
                # already covers the target (scout → longbow at 100 ft) instead
                # of the first-listed melee weapon. Distance is the same zone-path
                # cost the movement gate below reads, so the two agree.
                monster_activities = expand_action_to_activities(
                    monster,
                    monster_action,
                    target_distance_ft=_monster_target_distance_ft(
                        live, current.entity_id, chosen_target
                    ),
                    behavior_profile=current.behavior_profile,
                    melee_reach_ft=current.melee_reach_ft,
                )
    has_action = bool(monster_activities)

    # Phase-5: monster gambit zone awareness. When the chosen attack is
    # out of range, the monster MOVEs toward the target along the
    # shortest path, paying each edge's distance_ft out of its per-turn
    # movement budget. If the move brings it within range, the attack
    # then proceeds; otherwise the attack is skipped this turn (no
    # ``AttackFailed`` — the monster simply spent its movement closing
    # the distance). Ranged gambits whose normal range already covers
    # the target stay put and fire as before. Movement is planned and
    # executed BEFORE ``IntentSubmitted`` is emitted so the recorded
    # intent_type reflects what the monster actually does this turn —
    # ``"attack"`` when it ends in range, ``"pass"`` when it spent the
    # turn closing the gap.
    attack_skipped_due_to_range = False
    # SRD §Actions in Combat, Dash — set when the gambit below spends the
    # monster's Action on a Dash to close a gap it couldn't otherwise
    # cross. Dash IS the Action this turn (SRD action economy: one Action
    # per turn), so no Attack fires in the same turn a Dash was taken —
    # mirrors ``_handle_dash``'s Action-consuming default (the PC path also
    # supports a Rogue Cunning-Action Dash; monsters have no such
    # bonus-action gambit today, so this is always the base Action).
    dashed_this_turn = False
    if has_action and chosen_target is not None:
        monster_range_ft = _monster_attack_range_ft(monster_activities, current.melee_reach_ft)
        attacker_zone = live.actor_zone.get(current.entity_id)
        target_zone = live.actor_zone.get(chosen_target.entity_id)
        if (
            isinstance(monster_range_ft, int)
            and monster_range_ft > 0
            and attacker_zone is not None
            and target_zone is not None
            and not _in_range_with_los(live.topology, attacker_zone, target_zone, monster_range_ft)
        ):
            # Plan the path and walk it greedily within budget.
            path = live.topology.shortest_path(attacker_zone, target_zone)
            dashed_budget = _monster_dash_movement_budget(
                _path_total_distance(live.topology, path),
                current.movement_remaining,
                # SRD 5.2 Dash adds the creature's EFFECTIVE Speed: a Speed-0
                # monster (Grappled / Restrained / …) "can't increase" it, so
                # the gambit is declined outright (budget <= 0 → None).
                _effective_speed(current),
            )
            if dashed_budget is not None and current.action_available:
                dashed_this_turn = True
                for idx, c in enumerate(live.initiative):
                    if c.entity_id == current.entity_id:
                        live.initiative[idx] = c.model_copy(
                            update={
                                "action_available": False,
                                "movement_remaining": dashed_budget,
                            }
                        )
                        break
                _emit(
                    live,
                    DashTaken(
                        actor_id=current.entity_id,
                        doubled_movement_remaining=dashed_budget,
                        budget_consumed="action",
                    ),
                )
            # path[0] is attacker_zone; skip it. Walk forward step by step
            # until either (a) we exhaust the budget, (b) the next edge
            # doesn't fit, or (c) we end up within attack range.
            for next_zone in path[1:]:
                # Re-read the monster snapshot — it may have been mutated
                # by a previous _emit(ActorMoved) loop iteration.
                actor_snapshot = next(
                    c for c in live.initiative if c.entity_id == current.entity_id
                )
                step_distance = live.topology.edge_distance(
                    live.actor_zone[current.entity_id], next_zone
                )
                if step_distance is None or actor_snapshot.movement_remaining < step_distance:
                    break
                from_zone = live.actor_zone[current.entity_id]
                # SRD §Opportunity Attacks — fire BEFORE the mover leaves
                # reach. AoO interrupts the move: if the mover drops to 0
                # HP from any reactor's attack, the remaining steps are
                # cancelled and the move event for this step is suppressed
                # (the mover never completed the step).
                mover_died = _fire_pc_opportunity_attacks_on_move(
                    live,
                    mover_id=current.entity_id,
                    from_zone=from_zone,
                    to_zone=next_zone,
                )
                if mover_died:
                    break
                # Mutate budget + position via model_copy + slot-replace,
                # matching the PC MOVE pattern.
                for idx, c in enumerate(live.initiative):
                    if c.entity_id == current.entity_id:
                        live.initiative[idx] = c.model_copy(
                            update={
                                "movement_remaining": c.movement_remaining - step_distance,
                            }
                        )
                        break
                live.actor_zone[current.entity_id] = next_zone
                _emit(
                    live,
                    ActorMoved(
                        actor_id=current.entity_id,
                        from_zone=from_zone,
                        to_zone=next_zone,
                        distance_ft=step_distance,
                    ),
                )
                # Early-out once we're within attack range.
                if _in_range_with_los(live.topology, next_zone, target_zone, monster_range_ft):
                    break
            # Re-check range after the (possibly partial) move.
            final_zone = live.actor_zone[current.entity_id]
            if not _in_range_with_los(live.topology, final_zone, target_zone, monster_range_ft):
                attack_skipped_due_to_range = True

    # SRD §Opportunity Attacks — if the AoO interrupted the move and dropped
    # the monster, the mover is dead; no attack fires this turn. The turn
    # still advances through the IntentSubmitted(pass) / TurnEnded shape so
    # initiative progresses to the next actor.
    mover_dead_post_aoo = current.entity_id in live.dead_ids
    will_attack = (
        has_action
        and chosen_target is not None
        and not attack_skipped_due_to_range
        and not mover_dead_post_aoo
        and not dashed_this_turn
    )
    intent_type: IntentType = "dash" if dashed_this_turn else ("attack" if will_attack else "pass")
    _emit(
        live,
        IntentSubmitted(
            actor_id=current.entity_id,
            intent_type=intent_type,
            target_id=chosen_target.entity_id if chosen_target is not None else None,
        ),
    )

    if will_attack:
        # Re-read the actor snapshot — the move loop above may have
        # rebuilt the initiative slot with decremented movement_remaining;
        # the resolver runs against the post-move Combatant.
        current = next(c for c in live.initiative if c.entity_id == current.entity_id)
        assert chosen_target is not None  # mypy: narrowed by will_attack
        target_list = [chosen_target]

        # SRD §Reactions — drain the attacked PC's pending ``hit_by_attack``
        # reaction (Shield) BEFORE the sidecar projection below, so the
        # just-applied +5 AC effect folds into THIS attack's hydration
        # payload — the monster-attacker / PC-defender direction. Shield's own
        # resolution draws no dice, so the attack's d20 keeps its seed-stream
        # position.
        _drain_targeted_reactions(
            live,
            trigger="hit_by_attack",
            triggering_actor_id=current.entity_id,
            targets=target_list,
        )

        # The orchestrator owns the per-entity passive sidecars; project them
        # once and hand the two dicts ``build_activity_context`` needs in (it
        # stays pure — no orchestrator import, no double-compute). Mirrors the
        # PC site.
        payload = _build_hydration_payload(live, caster=current)
        pre_event_count = len(live.event_log)
        # Monster magnitudes (save DC = 8 + attack_bonus, mod = attack_bonus)
        # are reproduced by ``build_activity_context``'s ``entity_type ==
        # "Monster"`` branch — no per-call slot/spell parameters apply to a
        # mundane monster attack.
        target_unseen, attacker_unseen_by = _target_visibility_maps(live, current, target_list)
        actx = build_activity_context(
            current,
            target_list,
            rng=live.rng,
            event_emitter=lambda ev: _emit(live, ev),
            slot_level=None,
            base_spell_level=None,
            spellcasting_ability=None,
            concentration=False,
            source_passive_effects=[],
            # Monster/reaction paths don't delegate casts yet — PC-path
            # delegation lives in _build_cast_spell_book; extending it here
            # is a recorded follow-up.
            spell_book={},
            passive_damage_modifiers=payload["passive_damage_modifiers"],
            save_modifiers=payload["save_modifiers"],
            check_modifiers=payload["check_modifiers"],
            d20_test_penalty=payload["d20_test_penalty"],
            target_cover=_target_cover_map(live, current.entity_id, target_list),
            target_distance_ft=_target_distance_map(live, current.entity_id, target_list),
            attacker_grappler_id=_condition_source_entity(live, current, "grappled"),
            target_unseen=target_unseen,
            attacker_unseen_by=attacker_unseen_by,
        )
        for activity in monster_activities:
            # Monster attacks carry their damage on the AttackActivity itself,
            # not a separate Weapon (unlike the PC weapon path).
            resolve_activity(activity, actx, weapon=None)
        # Symmetric concentration writeback for spellcaster monsters
        # (mirrors the PC path; no-op for non-caster monsters).
        _writeback_concentration(live, current, pre_event_count)
        _record_effect_lifecycle_links(live, current, pre_event_count)

    # Advance the turn — the single shared path (F3a); this site used to carry
    # its own copy of the wrap-and-emit block.
    _end_turn_and_advance(live, current.entity_id)


def drain_pending_events(handle: CombatHandle) -> list[CombatEvent]:
    """Non-blocking drain of currently queued events for ``handle``.

    Used by the WS bridge to pump events emitted during a single
    ``submit_player_intent`` / ``advance_monster_turn`` call out to the
    broadcast layer without blocking on ``narration_events`` (which only
    terminates when ``end_combat`` enqueues its sentinel).

    The sentinel ``None`` (enqueued by ``end_combat``) is preserved on the
    queue so an in-flight ``narration_events`` consumer still terminates;
    it is not returned to the caller.
    """
    live = _get_live(handle)
    out: list[CombatEvent] = []
    while True:
        try:
            ev = live.event_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if ev is None:
            # Sentinel — put it back so any active ``narration_events``
            # consumer still sees the terminator and exits cleanly.
            live.event_queue.put_nowait(None)
            break
        out.append(ev)
    return out


async def narration_events(
    handle: CombatHandle,
) -> AsyncIterator[CombatEvent]:
    """Stream the combat's events to the narrator.

    The iterator terminates when ``end_combat`` is called — the closer
    drains a sentinel ``None`` onto the queue and we stop iteration on
    receiving it.
    """
    live = _get_live(handle)
    while True:
        event = await live.event_queue.get()
        if event is None:
            return
        yield event


def _derive_ended_reason(live: _LiveCombat) -> Literal["victory", "defeat_tpk", "flee", "forced"]:
    """SRD §Combat resolution — derive ``ended_reason`` from final tracked state.

    - all encounter members dead → victory
    - all party members dead → defeat_tpk
    - otherwise → forced (caller closed mid-combat)
    """
    all_foes_dead = all(eid in live.dead_ids for eid in live.encounter_ids)
    all_pcs_dead = all(eid in live.dead_ids for eid in live.party_ids)
    if all_foes_dead and live.encounter_ids:
        return "victory"
    if all_pcs_dead and live.party_ids:
        return "defeat_tpk"
    return "forced"


def _project_outcome(live: _LiveCombat) -> CombatOutcome:
    """Fold ``_LiveCombat`` event-derived running state into a ``CombatOutcome``.

    Residual HP / temp HP — from the tracked dicts updated by ``_emit``.
    Carried conditions — every still-active ``ConditionApplied`` for a
    surviving combatant. Carried-effect duration is taken from the most
    recent ``EffectApplied`` (the duration the effect was registered with).
    Deaths — the ordered ``DeathRecord`` list synthesized in ``_emit``.
    XP — SRD §Encounter XP, summed across dead encounter members and divided
    equally among surviving PCs (legacy ``handle_combat_end_victory`` solo
    semantics extend naturally — for solo-PC the survivor takes the full
    total).
    Loot drops — dropped from this seam's projection (loot tables aren't
    plumbed into ``EncounterMemberSpec`` yet); the cutover prompt wires
    monster ``loot_table`` lookups before victory.
    Expended resources — accumulated from ``EffectApplied`` with
    ``is_concentration=True`` during the combat.
    """
    residual_hp = {eid: hp for eid, hp in live.tracked_hp.items() if eid in live.party_ids}
    residual_temp_hp = {
        eid: thp for eid, thp in live.tracked_temp_hp.items() if eid in live.party_ids and thp > 0
    }

    # SRD §Encounter XP: total XP from dead foes ÷ surviving PCs.
    total_xp = sum(
        live.xp_value_by_entity.get(eid, 0) for eid in live.dead_ids if eid in live.encounter_ids
    )
    surviving_pcs = [eid for eid in live.party_ids if eid not in live.dead_ids]
    xp_awarded: dict[str, int] = {}
    if total_xp > 0 and surviving_pcs:
        per_pc = total_xp // len(surviving_pcs)
        if per_pc > 0:
            xp_awarded = {pc: per_pc for pc in surviving_pcs}

    loot_drops: list[LootDrop] = []

    return CombatOutcome(
        handle_id=live.handle_id,
        ended_reason=_derive_ended_reason(live),
        deaths=list(live.deaths_recorded),
        residual_hp=residual_hp,
        residual_temp_hp=residual_temp_hp,
        loot_drops=loot_drops,
        xp_awarded=xp_awarded,
        expended_resources={k: dict(v) for k, v in live.expended_resources.items()},
    )


async def end_combat(handle: CombatHandle) -> EndCombatResult:
    """Close the combat and return the projected outcome.

    Idempotent: calling twice returns the same outcome (with an empty
    ``events`` list on subsequent calls — the close events were only
    emitted once on the first invocation), no re-emission of events, no
    double-removal from the registry.
    """
    live = _get_live(handle)
    surviving = tuple(eff for target_list in live.active_effects.values() for eff in target_list)
    if live.ended and live.final_outcome is not None:
        return EndCombatResult(
            outcome=live.final_outcome,
            events=[],
            final_active_effects=surviving,
        )

    outcome = _project_outcome(live)
    end_events: list[CombatEvent] = []
    live.event_listeners.append(end_events.append)
    try:
        _emit(live, CombatEnded(reason=outcome.ended_reason))
    finally:
        live.event_listeners.remove(end_events.append)
    # Sentinel to terminate any active ``narration_events`` consumers.
    live.event_queue.put_nowait(None)

    live.ended = True
    live.final_outcome = outcome
    # Re-snapshot after CombatEnded emission in case any listener mutated
    # the active_effects registry (e.g. expire handler).
    surviving = tuple(eff for target_list in live.active_effects.values() for eff in target_list)
    return EndCombatResult(
        outcome=outcome,
        events=end_events,
        final_active_effects=surviving,
    )


def _reset_registry_for_tests() -> None:
    """Wipe the in-memory registry. Test-only — no production caller.

    Pytest's per-function isolation runs each test against fresh module
    state by convention, but the registry is module-global by design
    here (the cutover replaces it with host storage). This helper lets boundary
    tests start from a clean slate.
    """
    _REGISTRY.clear()


__all__ = [
    "CombatHandle",
    "CombatSeamError",
    "EncounterMemberSpec",
    "EndCombatResult",
    "IntentRejectedError",
    "LiveCombatView",
    "PartyMemberSpec",
    "PlayerIntent",
    "SceneTopology",
    "StartCombatResult",
    "UnknownHandleError",
    "ZoneEdge",
    "advance_monster_turn",
    "drain_pending_events",
    "end_combat",
    "get_actor_active_effects",
    "get_live",
    "narration_events",
    "start_combat",
    "submit_player_intent",
]


from dnd5e_engine.results import EndCombatResult, StartCombatResult  # noqa: E402

StartCombatResult.model_rebuild()
EndCombatResult.model_rebuild()
