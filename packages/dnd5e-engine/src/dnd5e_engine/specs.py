"""Combat boundary spec types.

Value-typed payloads the host adapter passes into start_combat. Owned
by the library so a standalone consumer can construct combat-ready
inputs without depending on Tapestria-specific session/world types.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dnd5e_engine.activities.passive_stats import CombatantSenses


class PartyMemberSpec(BaseModel):
    """One PC entering combat.

    The seam takes the projected wire-level shape; building a real
    ``Combatant`` from this happens in ``start_combat``. Combat stats
    (hp_max, ac, attack_bonus, …) are looked up from the session/world
    layer by the cutover prompt — the seam keeps them on this spec so
    the additive surface can be exercised standalone.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    initiative: int
    hp_current: int
    hp_max: int
    ac: int = 10
    attack_bonus: int = 0
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    zone_id: str
    # SRD §Spellcasting — caster spell-slot pool, ``{slot_level: count_remaining}``.
    # Tracked on ``_LiveCombat.spell_slots_by_entity[caster_id]``; the
    # orchestrator's slot gate decrements it and emits ``CastFailed`` when no
    # slot remains rather than resolving the spell. Empty dict for non-casters.
    spell_slots: dict[int, int] = Field(default_factory=dict)
    # SRD §Spells Known — list of spell slugs the caster has prepared/known.
    # The orchestrator resolves each slug to a typed ``Spell`` via
    # ``get_lib_loader().get_spell`` and routes its activities through the typed
    # resolver. Unknown slugs are skipped (with no warning — the caster simply
    # cannot cast that spell at runtime).
    spells_known: list[str] = Field(default_factory=list)
    # Custom limited-use counters (class features, item charges, etc.),
    # ``{name: {"value": int, "max": int}}``. Carried onto the live combat
    # state for the caster.
    custom_counters: dict[str, dict[str, int]] = Field(default_factory=dict)
    # SRD §Concentration — ``effect_id`` the caster is currently concentrating
    # on, or ``None``. Carried across to the live ``Combatant`` so the
    # single-concentration rule sees it on the first turn after combat opens.
    concentration_effect_id: str | None = None
    # SRD §Creatures — creature_type. PCs default to ``None``; the
    # character-sheet projection (race → creature_type) lands in the
    # session-side cutover. The condition-predicate evaluator reads this
    # via ``target.creature_type`` / ``caster.creature_type``.
    creature_type: str | None = None
    # SRD §Damage Resistance / §Damage Immunity — per-PC type lists. Empty by
    # default; populated from the character sheet projection when wired.
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    # SRD §Senses — special senses in feet. Populated by ``build_party_member``
    # from the PC's species senses + always-on feature passive_effects, and
    # copied onto the live ``Combatant`` at start_combat. Empty (all ``None``)
    # by default.
    senses: CombatantSenses = Field(default_factory=CombatantSenses)
    # SRD §Cantrips / §Character Advancement — character level (1..20).
    # Drives cantrip scaling tiers (1/5/11/17) for dice-count cantrips
    # (Sacred Flame, Fire Bolt → 1d8/2d8/3d8/4d8) and beam-count cantrips
    # (Eldritch Blast → 1/2/3/4 beams). Carried onto the live ``Combatant`` and
    # surfaced as ``ActivityResolutionContext.caster_level`` for the typed
    # resolver's dice-scaling. (Multi-instance beam/dart count is a recorded
    # data-layer follow-up — see Phase-7b deferred findings.)
    character_level: int = Field(ge=1, le=20, default=1)
    # SRD §Movement — walking speed in feet. Defaults to 30 (the SRD
    # baseline for medium humanoids). Projected onto ``Combatant.base_speed``
    # at start_combat; resets ``movement_remaining`` on each of the actor's
    # turns. Character race / monster speed projection threads through here.
    base_speed: int = 30
    # SRD §Classes — character class slug (e.g. ``"rogue"``, ``"barbarian"``).
    # Drives class-feature gating on the orchestrator seam — today only Cunning
    # Action (Rogue) Dash uses it (``class_slug == "rogue"`` ⇒ the
    # bonus-action-Dash path is legal). ``None`` for non-classed entities and
    # fixtures that don't project class info.
    class_slug: str | None = None
    # SRD §Subclasses — subclass slug (e.g. ``"berserker"``). Carried across to
    # the live ``Combatant`` so subclass-feature activities (piece 4) can gate
    # on it. ``None`` for non-classed entities, fixtures, and graph PCs without
    # a persistent subclass source.
    subclass_slug: str | None = None
    # SRD §Species — species slug (e.g. ``"orc"``, ``"dragonborn"``). Carried
    # across to the live ``Combatant`` so species-feature activities resolve
    # through the USE_FEATURE repertoire gate and species @scale tables resolve.
    # ``None`` for non-species entities, fixtures, and graph PCs without a
    # persistent species source.
    species_slug: str | None = None
    # Build-seam equipment carrier — a reference-slug list of item slugs the PC
    # carries. The build-spec (char-creation / factory) owns equipment selection;
    # ``build_party_member`` threads it through here so a built PC's equipment
    # reaches the spec. Empty for graph PCs (their mechanical equipment crosses
    # via the session-side enchantment projection, not this slug list).
    equipment: tuple[str, ...] = ()


class EncounterMemberSpec(BaseModel):
    """One hostile (monster or NPC) entering combat."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: Literal["Monster", "NPC"]
    name: str
    initiative: int
    hp_current: int
    hp_max: int
    ac: int = 10
    attack_bonus: int = 0
    damage_dice: str = "1d4"
    damage_type: str = "bludgeoning"
    behavior_profile: str = "AGGRESSIVE"
    dexterity: int = 10
    zone_id: str
    # SRD monster template slug — the orchestrator's monster-turn resolver uses
    # this to look up the monster's typed action repertoire via
    # ``get_lib_loader().get_monster(slug)``. ``None`` (for NPCs without a
    # template, or test fixtures) falls back to the legacy damage_dice /
    # damage_type single-attack heuristic — the monster has no typed actions and
    # ``advance_monster_turn`` records a no-op turn.
    monster_template_slug: str | None = None
    # SRD §Encounter XP value awarded when this monster dies. The orchestrator's
    # outcome projection sums xp_value across dead encounter members and divides
    # equally among surviving PCs (legacy ``handle_combat_end_victory`` semantics
    # for solo; SRD-correct for multi-PC).
    xp_value: int = 0
    # SRD §Creatures — creature_type ("humanoid", "undead", "fey", ...).
    # Populated from MonsterTemplate.creature_type on Neo4j; ``None`` for
    # NPCs without a template. Drives type-gated spell semantics (Hold
    # Person targets humanoids; Sleep autopasses undead/elves; etc.).
    creature_type: str | None = None
    # SRD §Damage Resistance / §Damage Immunity — per-monster type lists,
    # populated from MonsterTemplate (via CombatMonster / CombatNPC). Empty
    # by default for fixtures that don't specify.
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    # SRD §Movement — walking speed in feet. See PartyMemberSpec.base_speed.
    # Defaults to 30; monster speed lookup at the session layer threads
    # MonsterTemplate.speed["walk"] in here.
    base_speed: int = 30


class ZoneEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    distance_ft: int = Field(ge=0)


class SceneTopology(BaseModel):
    """Wire-level shape for the zone graph the engine resolves over.

    The orchestrator converts this to a concrete ``ZoneTopology`` (the
    Protocol the scaffold's ``RuntimeContext`` requires) at
    ``start_combat`` time. Per
    ``docs/agent-prompts/combat/00-evaluator-scaffold.md``, the scaffold
    keeps ``ZoneTopology`` as a structural Protocol; concrete graph
    implementations belong here at the seam.
    """

    model_config = ConfigDict(extra="forbid")

    zones: list[str]
    edges: list[ZoneEdge] = Field(default_factory=list)


class GridScene(BaseModel):
    """Wire-level shape for a 2-D grid battlefield.

    The grid backend resolves combat over Chebyshev (8-direction, one cell =
    ``cell_size_ft``) distance. Combatant positions reuse the existing
    ``zone_id`` string on the party/encounter specs, encoded as ``"col,row"``
    (see ``dnd5e_engine.spatial.cell_id``). ``blocked_cells`` are impassable
    squares (movement may not enter them); line-of-sight / cover / AoE
    templates over wall geometry are deferred (see ``BACKLOG.md``).
    """

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    cell_size_ft: int = Field(default=5, ge=1)
    blocked_cells: list[str] = Field(default_factory=list)


__all__ = [
    "EncounterMemberSpec",
    "GridScene",
    "PartyMemberSpec",
    "SceneTopology",
    "ZoneEdge",
]
