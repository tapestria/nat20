"""Public combat seam — orchestrator.

Per ``docs/agent-prompts/combat/01-boundary-api.md``. This module is the
typed plumbing the rest of the backend (session router, websocket
dispatch, narrator) will eventually call to:

- ``start_combat(...)`` — open a combat, allocate runtime state.
- ``submit_player_intent(...)`` — accept a PC intent for the current
  turn, validate it, emit ``IntentSubmitted``.
- ``narration_events(...)`` — stream the ``CombatEvent`` union out to
  the narrator.
- ``end_combat(...)`` — close the combat and return a ``CombatOutcome``.

Resolution runs through the typed-Activity resolver: ``submit_player_intent``
fetches the typed entity (Spell / Weapon / Item) for the intent from the lib
``BundledAssetLoader`` and walks its activities via the per-kind resolvers
under :mod:`dnd5e_engine.activities`. The prior Avrae-IR evaluator path was
retired in Phase 7b.

Sidecar hydration: every ``submit_player_intent`` call constructs a real
:class:`EffectStore` and projects per-resolution sidecar state from
:class:`_LiveCombat` via :func:`_build_hydration_payload` (passive
save/attack/damage modifiers from the typed change-fold + condition
projections) before resolving the intent's activities.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from dnd5e_srd_data.schema.common import ActivationBlock, AttackActivity, SaveActivity
from dnd5e_srd_data.schema.item import Weapon, WeaponProperty
from dnd5e_srd_data.schema.spell import CastingTimeUnit, Spell, SpellRangeUnits
from pydantic import BaseModel, ConfigDict

from dnd5e_engine.activities.build_context import build_activity_context
from dnd5e_engine.activities.monster_actions import (
    expand_action_to_activities,
    select_typed_monster_action,
)
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.activities.scale import build_scale_values
from dnd5e_engine.build_party import granted_feature_slugs
from dnd5e_engine.death_saves import roll_death_save
from dnd5e_engine.events import (
    ActorMoved,
    AttackFailed,
    AttackRolled,
    CastFailed,
    CombatEnded,
    CombatEvent,
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
    TurnStarted,
)
from dnd5e_engine.lib_loader import get_lib_loader
from dnd5e_engine.outcome import (
    CombatOutcome,
    DeathRecord,
    LootDrop,
)
from dnd5e_engine.rules.conditions import (
    project_passive_check_modifiers,
    project_passive_damage_modifiers,
    project_passive_save_modifiers,
)
from dnd5e_engine.rules.gambits import BehaviorProfile
from dnd5e_engine.spatial import GridTopology, SpatialTopology
from dnd5e_engine.specs import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    SceneTopology,
    ZoneEdge,
)
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectDuration
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
    slot_level: int | None = None
    # SRD §Reactions — surface-only field for the future off-turn intent
    # path. Carries the triggering event marker (e.g. "hit",
    # "targeted_by_magic_missile", "damaged_by_creature"). Unconsumed today;
    # the trigger-machinery probes remain xfailed.
    reaction_trigger: str | None = None
    # SRD §Movement — destination zone id for ``intent_type == "move"``.
    # Resolved by the parser from player free-text ("move to the back of
    # the room") and projected through ``parsed_intent_to_player_intent``
    # from ``ParsedIntent.target_zone_id``.
    target_zone_id: str | None = None
    # SRD §Combat — Dash budget choice. False → Action (default). True → Bonus
    # Action (Rogue Cunning Action). The orchestrator rejects the bonus-action
    # path when the actor is not a Rogue. Carried from
    # ``ParsedIntent.use_bonus_action``.
    use_bonus_action: bool = False


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

    def shortest_path(self, a: str, b: str) -> list[str]:
        """Return the sequence of zones from ``a`` to ``b`` (inclusive), or ``[]``.

        Dijkstra over the undirected weighted zone graph. Returned list
        starts with ``a`` and ends with ``b`` when a path exists; the
        intermediate elements are the zones to traverse in order. Returns
        ``[]`` when either endpoint is unknown or no path connects them.
        For ``a == b`` returns ``[a]`` (degenerate "you're already there").

        Phase-5 monster gambits use this to plan "MOVE toward the target"
        — they walk the returned path step-by-step, paying each edge's
        distance_ft out of the per-turn movement budget.
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
        # the graph itself. Both endpoints known ⇒ line of sight. (Wall/cover
        # modelling is a grid-only follow-up — see BACKLOG.md.)
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
    loader wrapper carried). Only an explicit :class:`AttackActivity` yields a
    finite reach the movement gate should honor:

      * an explicit numeric ``units == "ft"`` range (e.g. a ``"80"`` shortbow
        band) is used verbatim;
      * Foundry melee attacks ship ``units == "self"`` / no value (reach is
        implied), so they fall back to the monster's ``Combatant.melee_reach_ft``
        (5 by default, 10 for reach creatures) — reproducing the old
        ``range_ft == 5`` melee wrappers.

    A non-``AttackActivity`` offensive activity (a :class:`SaveActivity`)
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
    re-applies it against the runtime :class:`Combatant` before selection.
    """
    try:
        profile = BehaviorProfile(monster.behavior_profile)
    except ValueError:
        profile = BehaviorProfile.AGGRESSIVE
    hp_ratio = monster.hp_current / monster.hp_max if monster.hp_max > 0 else 0.0
    flee_threshold = 0.25 if profile == BehaviorProfile.RANGED else 0.10
    return profile != BehaviorProfile.DEFENSIVE and hp_ratio < flee_threshold


def _in_range_with_los(topology: SpatialTopology, a: str, b: str, range_ft: int) -> bool:
    """True iff ``b`` is within ``range_ft`` of ``a`` AND ``a`` has line of sight to ``b``.

    The single range+LoS predicate every attack/cast gate routes through, so a
    future LoS model gates them all consistently. v1 ``has_line_of_sight`` is
    always True ⇒ this is behaviour-identical to a bare ``within_range`` today.
    """
    return topology.within_range(a, b, range_ft) and topology.has_line_of_sight(a, b)


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


def _synthesize_attack_from_weapon(weapon: Weapon) -> AttackActivity:
    """Build a base-weapon :class:`AttackActivity` for a weapon with no
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
    prompt swaps this for the existing Redis-backed combat state in
    ``app/session/manager.py``. Keeping it in-memory here lets the
    boundary surface be exercised standalone without coupling to
    session/Redis fixtures.
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
    # :func:`advance_monster_turn`). Absent for PCs and slug-less NPCs.
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

    Public API for host-side resolvers (e.g. Tapestria's FLEE dispatch path,
    `_handle_consult_codex_dispatch`) that run alongside the engine's own
    dispatch and need to see the same active_effects the engine resolvers
    consume internally. The engine is the single source of truth for in-
    combat effect state; this accessor lets the host fold it into a
    `DispatchContext` without re-implementing the registry.

    Returns an empty tuple if the handle has no live combat (caller
    should treat as out-of-combat — per Phase 6 spec, no effects apply).
    """
    live = _REGISTRY.get(handle.handle_id)
    if live is None:
        return ()
    return tuple(live.active_effects.get(entity_id, []))


def _current_actor(live: _LiveCombat) -> Combatant:
    return live.initiative[live.current_turn_index]


def _find_combatant(live: _LiveCombat, entity_id: str) -> Combatant | None:
    """Locate a combatant in the live initiative by entity id."""
    for c in live.initiative:
        if c.entity_id == entity_id:
            return c
    return None


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

    new_movement = current.movement_remaining + current.base_speed
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
    # forwards through effect_lifecycle to the Redis EffectStore).
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
    so ``end_combat`` can project a populated :class:`CombatOutcome` without
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
        live.active_conditions.setdefault(event.target_id, set()).add(event.condition)
        return

    if isinstance(event, ConditionRemoved):
        live.active_conditions.get(event.target_id, set()).discard(event.condition)
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
                    # SRD §Movement — movement budget refreshes to the
                    # actor's full walking speed at the start of their
                    # own turn. Per-MOVE-intent decrement is the only
                    # writer; this is the only reset.
                    "movement_remaining": c.base_speed,
                }
            )
            break


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
    # failure. No CON modifier projection at the orchestrator boundary
    # today (mirrors ``_emit_concentration_save_probe`` in
    # ``effects/ieffect2.py``); the raw d20 vs. DC determines outcome.
    # Done BEFORE death synthesis so a dropped-conc + slain caster
    # still surface the cascade before the Death event.
    caster_chain = live.concentration_chain.get(event.target_id)
    if caster_chain:
        dc = max(10, event.amount // 2)
        roll_total = live.rng.randint(1, 20)
        succeeded = roll_total >= dc
        _emit(
            live,
            SaveRolled(
                target_id=event.target_id,
                ability="con",
                dc=dc,
                roll_total=roll_total,
                succeeded=succeeded,
            ),
        )
        if not succeeded:
            _drop_concentration(live, event.target_id)
    if (
        new_hp <= 0
        and event.target_id not in live.party_ids
        and event.target_id not in live.dead_ids
    ):
        # Synthesize a Death(damage) for the non-PC. Recursion guard:
        # _emit re-enters here for the Death, but the dead_ids set blocks
        # double-recording, and Death's only running-state effect is to
        # record the death (no further HP arithmetic).
        killer = live.current_actor_id
        death_event = Death(target_id=event.target_id, reason="damage")
        _record_death(live, death_event, killer_id=killer)
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
    for idx, c in enumerate(live.initiative):
        if c.entity_id == event.target_id:
            heal_update: dict[str, Any] = {"hp_current": new_hp}
            if revived:
                heal_update["is_alive"] = True
                heal_update["death_saves"] = {}
                heal_update["conditions"] = [
                    cond for cond in c.conditions if cond.condition != "unconscious"
                ]
            live.initiative[idx] = c.model_copy(update=heal_update)
            break


def _emit_apply_temp_hp(live: _LiveCombat, event: TempHpApplied) -> None:
    """Fold a ``TempHpApplied`` into running state: max-not-additive temp-HP
    tracking + initiative slot sync."""
    # SRD §Temporary Hit Points — new amount replaces existing if higher,
    # not additive (Avrae/Open5e canonical behavior).
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
        # Codex Phase 6 review iter-8 P1: also clear the status from
        # live.active_conditions (orchestrator_bridge reads this when
        # mirroring combatant conditions back to Redis). Without this,
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
    :func:`app.combat.death_saves.roll_death_save`, emit the returned events
    through ``_emit`` (so ws_projection picks them up), and apply the
    returned ``Combatant`` mutation back into the live initiative slot.

    The death-save state machine in :mod:`app.rules.combat_helpers` owns
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
    # PC can act on their next turn.
    if result.outcome == "critical_success":
        live.tracked_hp[actor.entity_id] = result.combatant.hp_current


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
# surfaces hung off ``ctx.effect_store`` — passive damage modifiers, save /
# check modifiers, existing temp-HP, counter pools, narrative text sink,
# spell book, available slots, active concentration, IEffect graph. The
# orchestrator projects from ``_LiveCombat`` (the in-memory combat state)
# and hands the payload to :meth:`EffectStore.set_sidecar_state` immediately
# before invoking the evaluator. ``set_sidecar_state`` resets ``_text_sink``
# each call, so the per-evaluation narrative bag is fresh.
#
# Follow-ups (NOT in scope here; see PR body):
#   * passive damage / save / check modifiers projection requires reading
#     active effect modifiers, which is async (EffectStore.read). Today we
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

# Foundry-native melee-weapon damage-bonus change key (Rage's Rage Damage rides
# here). Melee-weapon-scoped: folded into the ``passive_melee_damage_bonus``
# sidecar and consumed only on a melee weapon swing.
_FOUNDRY_MELEE_DAMAGE_KEY = "system.bonuses.mwak.damage"


def _fold_active_effect_changes(
    active: Sequence[ActiveEffect],
    per_target_dmg: dict[str, Any],
    per_target_entry: dict[str, Any],
) -> bool:
    """Fold each live effect's Foundry-shaped ``changes`` into the per-target
    ``per_target_dmg`` (attack/damage sidecar) and ``per_target_entry`` (save/ac
    sidecar) dicts in place. Returns whether ``per_target_dmg`` was mutated
    (``dmg_dirty``) so the caller knows to re-store it.

    Pure projection over the passed dicts — no ``live`` mutation.
    """
    dmg_dirty = False
    for active_effect in active:
        # Phase 6 codex iter-6 P1: equipped enchantments and other
        # ActiveEffects carry mechanically-relevant `changes` entries
        # (Foundry-shaped: attack.roll.bonus / damage.bonus /
        # ac.bonus / save.bonus / save.<ability>.bonus). Fold their
        # int-valued mode=add changes into the engine's attack and
        # save sidecar surfaces so the resolvers see them on
        # monster-driven turns. Dice formulas ("1d4") pass through as
        # additive strings — the handler's existing parser already
        # handles them.
        #
        # Codex iter-7 P1: when an effect carries an
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
            if change.mode != "add":
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
            # iter-14 P1 (corrects iter-7 over-filter).
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
            elif key == _FOUNDRY_MELEE_DAMAGE_KEY:
                # Rage's ``system.bonuses.mwak.damage`` (melee weapon
                # attack damage). Normalize into the melee-only
                # damage-bonus sidecar; attack.py applies it to a melee
                # weapon swing only (NOT ranged / spell).
                existing = per_target_dmg.get("passive_melee_damage_bonus")
                per_target_dmg["passive_melee_damage_bonus"] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
                continue
            elif key == "system.bonuses.abilities.save":
                key = "save.bonus"
            if key == "attack.roll.bonus":
                field = "passive_weapon_to_hit_bonus" if weapon_only else "passive_to_hit_bonus"
                existing = per_target_dmg.get(field)
                per_target_dmg[field] = (
                    f"{existing} {signed_str}" if existing else signed_str.lstrip("+")
                )
                dmg_dirty = True
            elif key == "save.bonus":
                # Codex Phase 6 review iter-13 P2: project ONLY the
                # generic save.bonus into the action-agnostic
                # sidecar. Per-ability buckets (save.wisdom.bonus,
                # save.dexterity.bonus) would silently leak into
                # every saving throw via passive_save_bonus.
                # combat.saving_throw and resolve_check read
                # per-ability buckets directly from active_effects
                # via apply_changes_to_check (iter-6), so the
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
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Project one combatant's per-target save/check entries, folding SRD
    conditions, per-creature resistances/immunities, and active-effect changes.

    Mutates ``passive_damage_modifiers[c.entity_id]`` in place (the damage
    projection lands there directly). Returns ``(save_entry, check_entry)``
    where ``check_entry`` is ``None`` when the SRD check projection is empty.
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
    if any(damage_proj.values()):
        passive_damage_modifiers[c.entity_id] = dict(damage_proj)
    # Per-target ``saves`` ability-code → modifier projection. SRD
    # 5e: ability modifier = floor((score - 10) / 2). The combat
    # scaffold's ``Combatant`` only carries the DEX score today
    # (other ability scores are owned by the character sheet /
    # monster template projection and not yet threaded into
    # ``_LiveCombat``); we project DEX from ``c.dexterity`` and
    # leave the other abilities at 0 until that projection lands.
    # save.py reads ``entry["saves"][ability]`` so the per-target
    # +4 DEX from a 18-score goblin is observable on the IR's
    # lower-case ability key.
    per_target_entry: dict[str, Any] = dict(save_proj)
    per_target_entry["saves"] = {"dex": (int(c.dexterity) - 10) // 2}

    # Active-effect projection: fold each live effect's Foundry-shaped
    # ``changes`` (Bless +1d4 save, Bane −1d4 save, +1 weapon, etc.) into
    # the per-target save_modifiers and attack-side
    # passive_damage_modifiers. The canonical store is
    # ``live.active_effects[entity_id]`` (event-log-derived). The typed
    # change-fold below is the sole source of these passive modifiers;
    # condition-derived save adv/dis comes from the SRD-condition
    # projection (``project_passive_save_modifiers``).
    active = live.active_effects.get(c.entity_id, [])
    if active:
        per_target_dmg = passive_damage_modifiers.get(c.entity_id, dict(damage_proj))
        dmg_dirty = _fold_active_effect_changes(active, per_target_dmg, per_target_entry)
        if dmg_dirty:
            passive_damage_modifiers[c.entity_id] = per_target_dmg

    check_entry = dict(check_proj) if any(check_proj.values()) else None
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
    # live ``cast``-delegation seam keys spells by Foundry uuid, so no
    # corpus scenario consumes this projection yet (build_activity_context
    # is called with spell_book={} today) — it is kept for the eventual
    # uuid→Spell delegation wiring and as a per-caster known-spells view.
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
    """Project ``EffectStore.set_sidecar_state`` kwargs from live combat state.

    Two projection scopes:

    * **Per-combatant** (keyed by ``entity_id``): ``existing_temp_hp``,
      ``passive_damage_modifiers``, ``save_modifiers``, ``check_modifiers``,
      ``existing_concentration``. Derived from canonical
      :class:`app.models.session.Combatant` fields (``temp_hp``,
      ``conditions``, ``concentration_effect_id``) plus the SRD-condition
      projection in :mod:`app.rules.conditions`.

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
    :attr:`_LiveCombat.active_effects` row by reading the effects'
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
        if check_entry is not None:
            check_modifiers[c.entity_id] = check_entry

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
# the typed activity alone is the AoE discriminator — no Avrae-wrapper read.

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
    :func:`_activity_has_measured_template`):

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


def _expand_aoe_target_list(
    live: _LiveCombat,
    caster: Combatant,
    named_target_id: str | None,
) -> list[Combatant]:
    """Build the AoE candidate list for the spell's resolved IR.

    Per SRD §Fireball / §Burning Hands / §Areas of Effect — the sphere /
    cone hits every creature in range, including allies and the caster.
    With zone-graph occupancy the projection is: every alive combatant
    whose zone matches the targeted zone. The targeted zone is the
    named target's zone (``intent.target_id``) when one is named, else
    the caster's zone (self-centered AoE like Burning Hands).
    """
    anchor_zone: str | None = None
    if named_target_id:
        anchor_zone = live.actor_zone.get(named_target_id)
    if anchor_zone is None:
        anchor_zone = live.actor_zone.get(caster.entity_id)
    if anchor_zone is None:
        # No zone info — fall back to caster + named target only.
        return [c for c in live.initiative if c.entity_id in {caster.entity_id, named_target_id}]
    return [
        c
        for c in live.initiative
        if c.is_alive
        and c.entity_id not in live.dead_ids
        and live.actor_zone.get(c.entity_id) == anchor_zone
    ]


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

    Codex Phase 6 review iter-6 P1 introduced the tick; iter-7 P1
    refined it to the caster-keyed semantics. Pre-Phase-6 the host's
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
            should_tick = False
            origin = eff.origin or ""
            if origin.startswith("cast:"):
                parts = origin.split(":", 2)
                caster_id = parts[2] if len(parts) == 3 else ""
                if caster_id == actor_id:
                    should_tick = True
            else:
                # Item / environment / non-spell origins: fall back to
                # ticking at the target's turn-end so they still expire.
                if target_id == actor_id:
                    should_tick = True
            if not should_tick:
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

    No save modifier projected — mirrors ``_emit_concentration_save_probe``
    and the boundary-level save handling: the orchestrator's d20 is the
    raw roll. The IR-level Save handler does project per-target save
    modifiers via the sidecar; once a Combatant carries non-DEX ability
    scores the end-of-turn save can hydrate them through the same
    projection. Today WIS/CHA/etc. modifiers project as 0.
    """
    # Collect every repeat-save spec keyed on the actor_id-prefixed
    # identity tuples. Identity is (target_id, effect.id, effect.origin)
    # post-Phase-6 rekey.
    pending_keys = [k for k in live.repeat_save_on_turn_end if k[0] == actor_id]
    if not pending_keys:
        return
    for identity in pending_keys:
        target_id, effect_id, origin = identity
        specs = live.repeat_save_on_turn_end.get(identity, [])
        surviving: list[dict[str, Any]] = []
        for spec in specs:
            ability = spec["ability"]
            dc = int(spec["dc"])
            condition = str(spec["condition"])
            caster_id = str(spec["caster_id"])
            roll_total = live.rng.randint(1, 20)
            succeeded = roll_total >= dc
            _emit(
                live,
                SaveRolled(
                    target_id=actor_id,
                    ability=ability,
                    dc=dc,
                    roll_total=roll_total,
                    succeeded=succeeded,
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


def _build_pc_combatants(
    party: list[PartyMemberSpec],
    combatants: list[Combatant],
    actor_zone: dict[str, str],
    tracked_hp: dict[str, int],
    spell_slots_by_entity: dict[str, dict[int, int]],
    spells_known_by_entity: dict[str, list[str]],
    custom_counters_by_entity: dict[str, dict[str, dict[str, int]]],
) -> None:
    """Append a :class:`Combatant` per party member and populate the passed
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
                senses=pc.senses,
                character_level=pc.character_level,
                base_speed=pc.base_speed,
                movement_remaining=pc.base_speed,
                class_slug=pc.class_slug,
                subclass_slug=pc.subclass_slug,
                species_slug=pc.species_slug,
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
    """Append a :class:`Combatant` per encounter foe and populate the passed
    accumulator dicts (actor_zone, tracked_hp, monster_slug, xp_value) in
    place. Mutation-only helper — returns ``None``.
    """
    for foe in encounter:
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
                dexterity=foe.dexterity,
                creature_type=foe.creature_type,
                damage_resistances=list(foe.damage_resistances),
                damage_immunities=list(foe.damage_immunities),
                base_speed=foe.base_speed,
                movement_remaining=foe.base_speed,
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
    """Select the combat's :class:`SpatialTopology` (grid vs. zone graph),
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
                # Codex Phase 6 review iter-13 P2: also write the caster's
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

        # Conditions-by-effect: every status the effect imposes is
        # attributed to (target_id, id, origin), so expire/concentration
        # cascade can find them.
        if eff.statuses:
            key = (eff.target_id, eff.id, eff.origin)
            existing = live.conditions_by_effect.get(key)
            if existing is None:
                live.conditions_by_effect[key] = list(eff.statuses)
            else:
                for status in eff.statuses:
                    if status not in existing:
                        existing.append(status)

        if not eff.statuses:
            continue
        # Also project into live.active_conditions so orchestrator_bridge's
        # project_combat_state_to_redis sees the seeded statuses on the next
        # mirror tick. Without this, statuses only land on initiative[*]
        # .conditions (set below) and are silently dropped when the bridge
        # rebuilds Redis conditions from active_conditions. Codex Phase 6
        # iter-5 P2.
        live.active_conditions.setdefault(eff.target_id, set()).update(eff.statuses)
        for idx, c in enumerate(live.initiative):
            if c.entity_id != eff.target_id:
                continue
            current_conditions = c.conditions
            existing_keys = {(ac.condition, ac.source_effect_id) for ac in current_conditions}
            new_conditions = list(current_conditions)
            dirty = False
            for status in eff.statuses:
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

    Returns a :class:`StartCombatResult` envelope wrapping the ``CombatHandle``
    the caller threads through subsequent seam calls and the events emitted
    during open (round-start + first turn-start).
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

    # Phase 6 — seed _LiveCombat.active_effects from the caller. The hook
    # is live today for equipped-magic-item enchantments (Tapestria-side
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

    # Emit the round-start + first turn-start so a consumer of
    # ``narration_events`` sees combat actually open. The evaluator
    # itself is invoked only from inside ``submit_player_intent`` once
    # an intent arrives — this matches the scaffold's
    # "RuntimeContext per evaluation" frozen-context model.
    start_events: list[CombatEvent] = []
    live.event_listeners.append(start_events.append)
    try:
        _emit(live, RoundStarted(round_number=live.round_number))
        _emit(live, TurnStarted(actor_id=_current_actor(live).entity_id))
        _maybe_roll_death_save(live)
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
    ``None`` from :func:`_resolve_feature_invocation` and spends nothing.
    """

    activities: list[Any]
    passive_effects: list[Any]
    is_bonus_action: bool


def _resolve_feature_invocation(caster: Combatant, feature_id: str) -> _FeatureInvocation | None:
    """Resolve a USE_FEATURE intent to its single concrete activity, or ``None``.

    Applies the REPERTOIRE GATE (class / subclass / species ``granted_features``
    at/below the caster's level) and the SINGLE-ACTIVITY contract. Returns
    ``None`` — after a loud, tracked warning — when the feature is out of
    repertoire, absent from the lib, has no typed activities, or is a
    multi-activity repertoire-of-alternatives needing an ``activity_id`` the
    parser does not yet supply. Returning ``None`` lets the caller reject the
    invocation BEFORE any action-economy budget is consumed.

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
        # SINGLE-ACTIVITY contract — a multi-activity feature is a repertoire of
        # ALTERNATIVES (Channel Divinity: Turn Undead vs Divine Spark). Firing
        # all of them is wrong; selecting one needs an ``activity_id`` the parser
        # does not yet supply. Defer with a loud, tracked no-op.
        _LOGGER.warning(
            "feature_multi_activity_selection_deferred feature_id=%s count=%d",
            feature_id,
            len(feature_activities),
        )
        return None
    is_bonus = getattr(feature_activities[0].activation, "type", None) == "bonus"
    # Rage's mwak buff + resistances ride a PassiveEffect on the feature; thread
    # them so its UtilityActivity's effect rider (``effects[].id``) resolves to a
    # runtime ActiveEffect.
    return _FeatureInvocation(
        activities=feature_activities,
        passive_effects=list(feature.passive_effects) if feature else [],
        is_bonus_action=is_bonus,
    )


def _advance_turn(live: _LiveCombat, actor_id: str) -> None:
    """SRD §Action Economy — end ``actor_id``'s turn and start the next.

    Ticks effect durations at turn end, emits ``TurnEnded``, advances
    ``current_turn_index`` (wrapping to the next round with a ``RoundStarted``
    on wrap), emits ``TurnStarted`` for the new current actor, and rolls any
    pending death save. This is the shared epilogue used by both spell-slot
    reject paths and the normal post-resolution path.
    """
    _tick_durations_at_turn_end(live, actor_id)
    _emit(live, TurnEnded(actor_id=actor_id))
    live.current_turn_index += 1
    if live.current_turn_index >= len(live.initiative):
        live.current_turn_index = 0
        live.round_number += 1
        _emit(live, RoundStarted(round_number=live.round_number))
    _emit(live, TurnStarted(actor_id=_current_actor(live).entity_id))
    _maybe_roll_death_save(live)


def _validate_intent_preconditions(
    live: _LiveCombat, handle: CombatHandle, actor_id: str
) -> Combatant:
    """Validate that combat is live, ``actor_id`` is in initiative, and it is
    currently ``actor_id``'s turn. Raises :class:`IntentRejectedError` on any
    failure; returns the current actor's :class:`Combatant` on success."""
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
    return current


def _handle_move(live: _LiveCombat, current: Combatant, intent: PlayerIntent) -> None:
    """SRD §Movement — phase-2 zone-shift primitive. The actor steps to an
    adjacent zone, paying the edge's distance_ft from their per-turn movement
    budget. Movement does NOT end the turn; the actor keeps initiative.

    Rejections (no target_zone_id, not adjacent, insufficient budget) emit
    ``MoveFailed`` and return without mutating budget or position.
    """
    actor_id = current.entity_id
    target_zone_id = intent.target_zone_id
    current_zone = live.actor_zone.get(actor_id)
    if (
        target_zone_id is None
        or current_zone is None
        or not live.topology.is_adjacent(current_zone, target_zone_id)
    ):
        _emit(live, MoveFailed(actor_id=actor_id, reason="not_adjacent"))
        return
    distance_ft = live.topology.edge_distance(current_zone, target_zone_id)
    # edge_distance returns int when is_adjacent is True; mypy needs the cast.
    assert distance_ft is not None
    if current.movement_remaining < distance_ft:
        _emit(live, MoveFailed(actor_id=actor_id, reason="insufficient_movement"))
        return
    # Decrement budget + update position. model_copy + slot-replace
    # mirrors the C-1 action-economy mutation pattern.
    for idx, c in enumerate(live.initiative):
        if c.entity_id == actor_id:
            live.initiative[idx] = c.model_copy(
                update={"movement_remaining": c.movement_remaining - distance_ft}
            )
            break
    live.actor_zone[actor_id] = target_zone_id
    _emit(
        live,
        ActorMoved(
            actor_id=actor_id,
            from_zone=current_zone,
            to_zone=target_zone_id,
            distance_ft=distance_ft,
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
    # turn — the very flow Task 4 exercises. ``feature_invocation`` is already
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


def _hellish_rebuke_target_invalid(current: Combatant, intent: PlayerIntent) -> bool:
    """SRD §Hellish Rebuke — return ``True`` if this is a Hellish Rebuke cast
    whose target is not the most-recent damager tracked on the caster."""
    return (
        intent.intent_type == "cast_spell"
        and intent.spell_id == "hellish-rebuke"
        and (current.last_damaged_by is None or intent.target_id != current.last_damaged_by)
    )


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
        _advance_turn(live, actor_id)
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
            _advance_turn(live, actor_id)
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


def _resolve_intent_activities(
    intent: PlayerIntent, feature_invocation: _FeatureInvocation | None
) -> _ResolvedActivities:
    """Fetch the typed entity for the intent's kind from the lib loader and
    collect the activities the resolver will walk. This is the sole PC
    resolution path; the old Avrae IR path was retired in Phase 7b."""
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
            # The OLD path used a uniform caster ``mod`` regardless of the
            # spell's real spellcasting ability; ``build_activity_context``
            # makes every ability yield that same mod, so the ability name
            # here only selects which (equal) mod the resolver reads.
            spellcasting_ability = "int"
    elif intent.intent_type == "use_item" and intent.item_id:
        # Parity with the OLD resolver's ``use_item`` branch: an item (potion,
        # scroll, wand) may carry its own activities — most often a
        # ``CastActivity`` that delegates to a referenced spell. Fetch the
        # typed item and resolve its activities directly. ``get_item`` spans
        # Item/Weapon/Armor/MagicItem, all of which inherit ``activities``.
        fetched_item = get_lib_loader().get_item(intent.item_id)
        if fetched_item is not None:
            activities = list(fetched_item.activities)
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


def _resolve_targets(
    live: _LiveCombat,
    current: Combatant,
    intent: PlayerIntent,
    activities: list[Any],
    cast_spell: Spell | None,
) -> list[Combatant]:
    """SRD §Areas of Effect / §Range: Self — resolve the target list. An AoE
    cast broadcasts to every creature in the targeted zone; otherwise the named
    target is used, defaulting to the caster for an effect-bearing self/
    targetless buff or a self-targeting feature."""
    targets: list[Combatant]
    if intent.intent_type == "cast_spell" and _typed_spell_broadcasts(activities):
        targets = _expand_aoe_target_list(live, current, intent.target_id)
    else:
        targets = [c for c in live.initiative if c.entity_id == intent.target_id]
        # SRD §Range: Self — an effect-bearing self/targetless buff (Shield,
        # Mirror Image, Disguise Self) names no foe, so the named-target filter
        # above yields []. Its riders would then apply to nobody and the buff
        # would silently do nothing. Default the target to the caster. AoE
        # (handled above) and single-target casts (target_id present) are
        # untouched.
        if (
            not targets
            and intent.intent_type == "cast_spell"
            and _activities_bear_effects(activities)
            and _spell_is_self_or_targetless(cast_spell, intent.target_id)
        ) or (
            not targets and intent.feature_id and activities and _activities_target_self(activities)
        ):
            targets = [current]
    return targets


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
    resolvers under :mod:`dnd5e_engine.activities`, emitting the resulting
    ``CombatEvent`` stream.
    """
    live = _get_live(handle)
    current = _validate_intent_preconditions(live, handle, actor_id)

    # SRD §Hunter's Mark — *"If the target drops to 0 Hit Points before
    # this spell ends, you can take a Bonus Action to move the mark to
    # a new creature you can see within range."* The ``move_mark``
    # intent is its own narrow seam (no IR evaluation, no spell slot
    # consumption, no concentration re-check). Validates:
    #   1. caster currently concentrating on hunters-mark
    #   2. the old marked target is dead
    #   3. the new target is alive and in range
    # On success: emit EffectExpired on the old target, EffectApplied
    # on the new target, consume the bonus action, keep the caster on
    # turn. The persistent ``concentration_chain`` map is also
    # re-pointed so subsequent rider-damage projection finds the new
    # marked target.
    if intent.intent_type == "move_mark":
        await _handle_move_mark(live, current, intent)
        return

    # SRD §Movement — phase-2 zone-shift primitive. The actor steps to an
    # adjacent zone, paying the edge's distance_ft from their per-turn
    # movement budget. Movement does NOT end the turn (SRD §Action
    # Economy: movement is interleaved with Actions / Bonus Actions);
    # the actor keeps initiative and may follow with anything else.
    # Rejections (no target_zone_id, not adjacent, insufficient budget)
    # emit ``MoveFailed`` and return without mutating budget or position.
    if intent.intent_type == "move":
        _handle_move(live, current, intent)
        return

    # SRD §Combat — Dash. Spend the Action (default) or, for Rogues with the
    # Cunning Action class feature, the Bonus Action. Either way the effect is
    # the same: ``movement_remaining += base_speed`` (additive, so a Rogue who
    # spends both budgets in one turn reaches 3× base speed). Dash does NOT
    # advance the turn — the actor keeps initiative and may follow with MOVE /
    # attack / etc. Rejections raise ``IntentRejectedError("no_action_economy")``:
    #   * use_bonus_action=True + actor is not a Rogue
    #   * use_bonus_action=True + bonus_action_available=False
    #   * use_bonus_action=False + action_available=False
    if intent.intent_type == "dash":
        _handle_dash(live, current, intent)
        return

    # USE_FEATURE — resolve the feature to its single concrete activity BEFORE
    # any action-economy budget is consumed. A gate-rejected or multi-activity
    # no-op feature returns ``None`` (after a loud, tracked warning) and the turn
    # stays untouched: no Bonus Action / Action spent, no IntentSubmitted emitted,
    # turn preserved. This ordering is the fix for the economy bug where a
    # rejected feature still spent the Bonus Action.
    feature_invocation: _FeatureInvocation | None = None
    if intent.feature_id:
        feature_invocation = _resolve_feature_invocation(current, intent.feature_id)
        if feature_invocation is None:
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

    # SRD §Spell Range — out-of-range casts are a no-op: they consume
    # neither budget nor slot. Validate BEFORE budget consumption. The
    # typed ``Spell.range`` carries the band: feet-valued ranges gate at their
    # distance, and ``touch`` gates at 5ft (the caster must be adjacent — the
    # old wrapper carried ``range_ft=5`` for touch spells). ``self``/``special``
    # carry no metric distance and skip the gate. ``_ZoneGraph.within_range`` is
    # the canonical distance oracle keyed off ``live.actor_zone``.
    if _spell_out_of_range(live, actor_id, intent, cast_spell_for_timing):
        _emit(
            live,
            CastFailed(
                actor_id=actor_id,
                spell_id=intent.spell_id or "",
                reason="out_of_range",
            ),
        )
        return

    # SRD §Weapon Reach / Range — out-of-reach melee attacks (and beyond-
    # normal-range ranged attacks) reject pre-resolution: no action budget
    # consumed, turn preserved. ``_pc_attack_out_of_range`` resolves the
    # weapon's reach / normal range from the typed ``Weapon.range`` (via
    # ``get_lib_loader().get_weapon``) and projects the distance over
    # ``_ZoneGraph.within_range``. Long-range disadvantage is a follow-up;
    # only the hard reject is enforced here.
    if intent.intent_type == "attack" and _pc_attack_out_of_range(live, actor_id, intent):
        _emit(
            live,
            AttackFailed(
                actor_id=actor_id,
                target_id=intent.target_id,
                reason="out_of_range",
            ),
        )
        return

    # SRD §Hellish Rebuke — *"the creature that damaged you"*. The legal
    # target is the most-recent damager tracked on the caster as
    # ``last_damaged_by``. Hard-coded for HR until a general trigger
    # system lands. Reject BEFORE budget/slot consumption.
    if _hellish_rebuke_target_invalid(current, intent):
        _emit(
            live,
            CastFailed(
                actor_id=actor_id,
                spell_id=intent.spell_id,
                reason="target_invalid",
            ),
        )
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

    # SRD §Spellcasting — Spell Slots. Gate + decrement live on the
    # orchestrator; a rejected cast emits ``CastFailed`` + advances the turn
    # and signals the caller to return.
    if _consume_spell_slot(live, current, actor_id, intent):
        return

    # ── Typed-Activity resolution (Foundry cutover, Task 5) ─────────────
    #
    # Fetch the typed entity for the intent's kind from the lib loader and
    # collect the activities the resolver will walk. This is the sole PC
    # resolution path; the old Avrae IR path was retired in Phase 7b.
    resolved = _resolve_intent_activities(intent, feature_invocation)
    activities = resolved.activities
    cast_spell = resolved.cast_spell
    fetched_weapon = resolved.fetched_weapon
    spellcasting_ability = resolved.spellcasting_ability
    feature_passive_effects = resolved.feature_passive_effects

    # SRD §Areas of Effect — fireball / burning-hands hit every creature in
    # the targeted zone. The AoE discriminator is the typed activity's measured
    # ``target.template`` (Task 9-A): the lib's converter now surfaces Foundry's
    # measured-template block onto each creature-targeting activity, so a spell
    # whose resolving activity carries a template shape (Fireball sphere/20,
    # Burning Hands cone/15) broadcasts to the zone, while a template-less spell
    # (Sacred Flame, Cure Wounds, Magic Missile, Detect Thoughts' single save)
    # stays single-target. No Avrae-wrapper read.
    targets = _resolve_targets(live, current, intent, activities, cast_spell)

    # The orchestrator already owns the per-entity passive sidecars; project
    # them once and hand the two dicts ``build_activity_context`` needs in
    # (it stays pure — no orchestrator import, no double-compute).
    payload = _build_hydration_payload(live, caster=current)

    pre_event_count = len(live.event_log)

    if not activities:
        # Slug absent from the lib (e.g. a wrapper-only spell) or a non-
        # resolving intent kind. Emit nothing, but log the loss — never a
        # silent no-op. The divergence triage (Task 9) classifies these.
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
            # Empty: ``spell_book`` is the Foundry-uuid → Spell map a
            # ``CastActivity`` delegates through (scroll/wand casting a
            # referenced spell). No uuid flows through live combat state today,
            # and no live scenario exercises cast delegation, so the
            # uuid→Spell plumbing is a recorded deferred follow-up — NOT built
            # here. A miss is not silent: ``resolve_cast`` (activities/cast.py)
            # logs ``cast_spell_unresolved uuid=...`` at WARNING and returns.
            spell_book={},
            passive_damage_modifiers=payload["passive_damage_modifiers"],
            save_modifiers=payload["save_modifiers"],
            scale_values=scale_values,
            class_levels=class_levels,
            # A FEATURE invocation must not inherit the blanket spell
            # save_dc_override; its save activity computes its own ability+PB DC.
            is_feature_invocation=bool(intent.feature_id),
        )
        for activity in activities:
            resolve_activity(activity, actx, weapon=fetched_weapon)

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
    # the target repeats the save."* Roll any pending repeat saves for the
    # actor whose turn just resolved BEFORE emitting TurnEnded so the
    # ``SaveRolled`` events surface on the same turn boundary the SRD
    # specifies. PC self-cast concentration spells (Bless / Bane) don't
    # register repeat-save specs (no condition + failed-save pairing), so
    # this is a no-op for self-buff casters.
    _run_end_of_turn_saves(live, actor_id)

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
    _advance_turn(live, actor_id)


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
    ``docs/BACKLOG.md`` [combat] entry).

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

    Validation mirrors :func:`submit_player_intent`:

      - combat must not have ended
      - the current actor must be a non-Character entity (Monster /
        NPC); calling on a PC turn raises ``IntentRejectedError`` so
        the WS-side dispatch can branch on it

    Selection: :func:`dnd5e_engine.activities.monster_actions.select_typed_monster_action`
    picks an action from the typed ``Monster.actions`` (fetched from the lib
    loader by ``monster_template_slug``); ``expand_action_to_activities`` fans
    multiattack out into its sub-attacks. Targeting: lowest-HP alive PC in
    initiative order (the legacy gambit's ``target_priority="lowest_hp"``
    semantics). Resolution: each returned ``Activity`` runs through
    :func:`dnd5e_engine.activities.resolver.resolve_activity` against a context
    built by :func:`build_activity_context` — the same typed path as the PC
    turn (Task 5/6 of the Foundry cutover).

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
        not current.is_alive or current.hp_current <= 0 or _monster_is_fleeing(current)
    )

    # Build alive-PC target list (lowest_hp priority — the legacy
    # gambit's target rule). Empty targets degrades to pass.
    alive_pcs: list[Combatant] = [
        c
        for c in live.initiative
        if c.entity_id in live.party_ids and c.is_alive and c.hp_current > 0
    ]
    if not alive_pcs:
        skip_to_record_pass = True

    chosen_target: Combatant | None = (
        min(alive_pcs, key=lambda c: c.hp_current) if alive_pcs else None
    )

    # ── Typed-Activity monster resolution (Foundry cutover, Task 6) ─────────
    #
    # Fetch the typed ``Monster`` from the lib loader, pick its action, and fan
    # out multiattack. This is the sole monster-turn path; the old Avrae IR
    # path was retired in Phase 7b.
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
                monster_activities = expand_action_to_activities(monster, monster_action)
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
    )
    intent_type: IntentType = "attack" if will_attack else "pass"
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
            spell_book={},
            passive_damage_modifiers=payload["passive_damage_modifiers"],
            save_modifiers=payload["save_modifiers"],
        )
        for activity in monster_activities:
            # Monster attacks carry their damage on the AttackActivity itself,
            # not a separate Weapon (unlike the PC weapon path).
            resolve_activity(activity, actx, weapon=None)
        # Symmetric concentration writeback for spellcaster monsters
        # (mirrors the PC path; no-op for non-caster monsters).
        _writeback_concentration(live, current, pre_event_count)
        _record_effect_lifecycle_links(live, current, pre_event_count)

    # SRD §Hold Person / §Hold Monster repeat-save — runs whether or not
    # the monster had an action this turn (a paralyzed goblin with no
    # gambit still takes its turn-end save). Symmetric with the PC path
    # in ``submit_player_intent``.
    _run_end_of_turn_saves(live, current.entity_id)

    # Advance the turn (same wrap-and-emit shape as submit_player_intent).
    _tick_durations_at_turn_end(live, current.entity_id)
    _emit(live, TurnEnded(actor_id=current.entity_id))
    live.current_turn_index += 1
    if live.current_turn_index >= len(live.initiative):
        live.current_turn_index = 0
        live.round_number += 1
        _emit(live, RoundStarted(round_number=live.round_number))
    _emit(live, TurnStarted(actor_id=_current_actor(live).entity_id))
    _maybe_roll_death_save(live)


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
    """Fold ``_LiveCombat`` event-derived running state into a :class:`CombatOutcome`.

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
    here (the cutover replaces it with Redis). This helper lets boundary
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
