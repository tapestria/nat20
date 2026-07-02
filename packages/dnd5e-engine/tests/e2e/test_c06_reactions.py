"""C06 — Reactions & off-turn intents.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 6.

Governing constraint (cluster preamble): reactions are pre-armed
auto-fire. A combatant declares the reaction + trigger condition via a
normal ON-TURN intent (``intent_type="ready"`` — already a member of the
``IntentType`` literal, currently accepted and handled as a safe
Action-consuming no-op with zero reaction bookkeeping). When the trigger
condition is later satisfied by ANY combatant's submitted intent, the
engine is expected to auto-resolve the pending reaction and emit its
events BEFORE the triggering intent's own activities resolve — entirely
inside whichever of ``submit_player_intent``/``advance_monster_turn``
processes the trigger; there is no mid-resolution host round-trip.

Per this cluster's task brief, the enemy caster in C06-S01/S02 is modeled
as a second PC (``PartyMemberSpec``) rather than a monster — monster
spellcasting is not constructible via the public turn-taking seam today
(``select_typed_monster_action`` never selects a ``CastActivity``-only
action) — by documented decision, not a substitution error.

C06-S01/S02 transcribe SRD 5.2 (2024) Counterspell — an unconditional
Constitution saving throw against the counterspeller's own spell save DC
(``packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/counterspell.json``,
activity ``dnd5eactivity000``, ``kind: "save"``, ``save.ability: ["con"]``,
``save.dc.calculation: "spellcasting"``) — NOT the 2014/SRD 5.1
ability-check/DC-10-plus-level mechanic a prior draft of this cluster (and
the current, stale BACKLOG.md wording) encoded.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    ActorMoved,
    AttackRolled,
    CastFailed,
    CheckRolled,
    DamageApplied,
    EffectApplied,
    EffectExpired,
    IntentSubmitted,
    ReactionTriggered,
    SaveRolled,
    TurnEnded,
    TurnStarted,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    get_live,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec, SceneTopology, ZoneEdge
from tests.e2e.harness import events_of, run_async, xfail_cluster


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s01_prearmed_counterspell_forces_con_save_two_seeds():
    """C06-S01: A pre-armed Counterspell forces the enemy caster's
    Constitution saving throw against the counterspeller's own spell save
    DC; both outcomes pinned across two seeds.

    SRD 5.2 §Reactions (appendix-d-rule-references.yml, journal page
    2VqLyxMyMxgXe2wC: "A Reaction is a special action taken in response to
    a trigger defined in the Reaction's description. You can take a
    Reaction on another creature's turn... Once you take a Reaction, you
    can't take another one until the start of your next turn."); §Actions
    in Combat, Ready (chapter-1/actions.yml: "Ready — Prepare to take an
    action in response to a trigger you define."); Counterspell's own
    canonical text (authoritative — see module docstring): "You attempt to
    interrupt a creature in the process of casting a spell. The creature
    makes a Constitution saving throw. On a failed save, the spell
    dissipates with no effect, and the action, Bonus Action, or Reaction
    used to cast it is wasted. If that spell was cast with a spell slot,
    the slot isn't expended." DC formula:
    packages/dnd5e-engine/src/dnd5e_engine/activities/save.py::_resolve_dc,
    "spellcasting" branch = 8 + caster_proficiency_bonus +
    ability_mod(spellcasting_ability) — INT 18 (+4) + proficiency +3 at
    character_level 5 = dc 15, once the compounding
    build_context.py::_save_dc/_caster_mod legacy-flat-approximation bug
    (also required for this scenario) is closed.

    Seed derivation (per the catalog): the natural d20 draws pinned here
    (roll_total=15 at rng_seed=9, roll_total=5 at rng_seed=1) were
    empirically observed by exercising the real, seeded, per-combat
    SaveActivity resolver directly (casting counterspell on-turn against
    the same stat blocks) — reapplying the SRD-correct dc=15 to those same
    natural rolls yields succeeded=True (15 >= 15) and succeeded=False
    (5 < 15) respectively. Placing the drained Counterspell save as the
    FIRST rng draw following the enemy caster's cast_spell submission is a
    documented assumption (the "ready" step itself draws zero dice today).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:wiz_reactor",
                name="Reactor",
                initiative=20,
                hp_current=20,
                hp_max=20,
                intelligence=18,
                class_slug="wizard",
                character_level=5,
                spells_known=["counterspell"],
                spell_slots={3: 1},
                zone_id="zone:a",
            ),
            PartyMemberSpec(
                entity_id="char:enemy_caster",
                name="EnemyCaster",
                initiative=15,
                hp_current=20,
                hp_max=20,
                constitution=10,
                spells_known=["fireball"],
                spell_slots={3: 1},
                zone_id="zone:a",
            ),
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:target",
                entity_type="Monster",
                name="Target",
                initiative=1,
                hp_current=50,
                hp_max=50,
                ac=13,
                zone_id="zone:b",
            )
        ]

    async def _run(rng_seed: int):
        start = await start_combat(
            session_id=f"e2e-c06-s01-seed{rng_seed}",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(
                zones=["zone:a", "zone:b"],
                edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=30)],
            ),
            rng_seed=rng_seed,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz_reactor",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:enemy_caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="fireball",
                slot_level=3,
                target_id="mon:target",
            ),
        )
        return live

    # rng_seed=9 — S_a, the Constitution save succeeds; Fireball resolves
    # normally against mon:target.
    live_a = run_async(_run(9))
    assert not events_of(live_a, CheckRolled)  # SRD 5.2 Counterspell has no check branch
    con_saves_a = [e for e in events_of(live_a, SaveRolled) if e.ability == "con"]
    assert con_saves_a
    save_a = con_saves_a[0]
    assert save_a.target_id == "char:enemy_caster"
    assert save_a.dc == 15
    assert save_a.roll_total == 15
    assert save_a.succeeded is True
    reactions_a = [
        e
        for e in events_of(live_a, ReactionTriggered)
        if e.actor_id == "char:wiz_reactor" and e.reaction_name == "counterspell"
    ]
    assert reactions_a
    assert not events_of(live_a, CastFailed)
    fireball_saves_a = [e for e in events_of(live_a, SaveRolled) if e.target_id == "mon:target"]
    assert fireball_saves_a
    assert [e for e in events_of(live_a, DamageApplied) if e.target_id == "mon:target"]

    # rng_seed=1 — S_b, the Constitution save fails; Fireball is countered.
    live_b = run_async(_run(1))
    assert not events_of(live_b, CheckRolled)
    con_saves_b = [e for e in events_of(live_b, SaveRolled) if e.ability == "con"]
    assert con_saves_b
    save_b = con_saves_b[0]
    assert save_b.target_id == "char:enemy_caster"
    assert save_b.dc == 15
    assert save_b.roll_total == 5
    assert save_b.succeeded is False
    failed_b = events_of(live_b, CastFailed)
    assert failed_b
    assert failed_b[0].actor_id == "char:enemy_caster"
    assert failed_b[0].spell_id == "fireball"
    assert failed_b[0].reason == "countered"
    # Fireball's own save-or-damage activity never runs.
    assert not [e for e in events_of(live_b, SaveRolled) if e.target_id == "mon:target"]
    assert not events_of(live_b, DamageApplied)


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s02_countered_cast_preserves_slot_and_wastes_action():
    """C06-S02: A countered, slot-cast Counterspell target does not expend
    its spell slot; the interrupted caster's action is wasted (turn
    advances with no further action).

    Counterspell's own canonical text (authoritative): "...the action,
    Bonus Action, or Reaction used to cast it is wasted. If that spell was
    cast with a spell slot, the slot isn't expended."
    (packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/counterspell.json,
    description). Engine:
    packages/dnd5e-engine/src/dnd5e_engine/orchestrator.py::_consume_spell_slot
    decrements the CASTER's own spell-slot pool unconditionally at
    cast_spell intent-submission time, strictly before
    _resolve_intent_activities ever runs — no slot-refund path exists in
    src/ today, so the slot is spent whether or not the cast is later
    interrupted. The sibling no_slot branch of the same function already
    calls _advance_turn(live, actor_id) directly after a CastFailed
    emission — the existing, shipped precedent this scenario's "action
    wasted" assertion reuses. State exposure:
    packages/dnd5e-engine/src/dnd5e_engine/views.py::LiveCombatView.spell_slots_by_entity
    (read via orchestrator.get_live).

    Reuses C06-S01's rng_seed=1 (S_b, save-fails/countered) branch; the
    save-succeeds branch spends the slot normally like any uninterrupted
    cast and is not retested here.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c06-s02",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz_reactor",
                    name="Reactor",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    intelligence=18,
                    class_slug="wizard",
                    character_level=5,
                    spells_known=["counterspell"],
                    spell_slots={3: 1},
                    zone_id="zone:a",
                ),
                PartyMemberSpec(
                    entity_id="char:enemy_caster",
                    name="EnemyCaster",
                    initiative=15,
                    hp_current=20,
                    hp_max=20,
                    constitution=10,
                    spells_known=["fireball"],
                    spell_slots={3: 1},
                    zone_id="zone:a",
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:target",
                    entity_type="Monster",
                    name="Target",
                    initiative=1,
                    hp_current=50,
                    hp_max=50,
                    ac=13,
                    zone_id="zone:b",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a", "zone:b"],
                edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=30)],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz_reactor",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="counterspell",
                slot_level=3,
                reaction_trigger="cast_spell",
            ),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:enemy_caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="fireball",
                slot_level=3,
                target_id="mon:target",
            ),
        )
        view = get_live(start.handle)
        return live, view

    live, view = run_async(_run())

    # Slot preserved: unchanged from its pre-cast value {3: 1}.
    assert view.spell_slots_by_entity["char:enemy_caster"][3] == 1

    failed = events_of(live, CastFailed)
    assert failed
    assert failed[0].actor_id == "char:enemy_caster"
    assert failed[0].spell_id == "fireball"
    assert failed[0].reason == "countered"

    # Action wasted: the tail after CastFailed shows TurnEnded(enemy_caster)
    # -> TurnStarted(<next actor>), no further activity events this turn —
    # mirrors the shipped no_slot/no_action_economy CastFailed branches'
    # own _advance_turn call.
    failed_idx = live.event_log.index(failed[0])
    tail = live.event_log[failed_idx + 1 :]
    # No further activity events for char:enemy_caster this turn — TurnEnded
    # must be the very next event after CastFailed, with a TurnStarted for
    # the next actor following it.
    assert tail
    assert isinstance(tail[0], TurnEnded)
    assert tail[0].actor_id == "char:enemy_caster"
    assert any(isinstance(e, TurnStarted) for e in tail[1:])


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s03_prearmed_shield_raises_ac_by_5_expires_next_turn():
    """C06-S03: A pre-armed Shield raises effective AC by 5 against the
    triggering attack (same-seed A/B: identical roll hits base AC, misses
    AC+5) and expires by the reactor's next turn start.

    SRD 5.2 §Spell Descriptions (Shield: canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/shield.json,
    description: "An imperceptible barrier of magical force protects you.
    Until the start of your next turn, you have a +5 bonus to AC,
    including against the triggering attack, and you take no damage from
    Magic Missile."); engine:
    packages/dnd5e-engine/src/dnd5e_engine/activities/attack.py
    (_resolve_hit_outcome reads target.ac raw, zero active-effect
    consultation); orchestrator.py::_fold_active_effect_changes's existing
    "ac.bonus" branch never matches Shield's own
    "system.attributes.ac.bonus" key; ActivityResolutionContext has no
    passive_ac_bonus field at all — three independent, compounding drop
    points per the catalog.

    rng_seed=7 both runs — verified empirically that this seed's
    goblin-scimitar attack resolves to roll_total=11 deterministically
    regardless of which non-dice-consuming intent the hero submits first.
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                ac=10,
                class_slug="wizard",
                spells_known=["shield"],
                spell_slots={1: 2},
                zone_id="zone:a",
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:goblin",
                entity_type="Monster",
                name="Goblin",
                initiative=1,
                hp_current=7,
                hp_max=7,
                ac=13,
                monster_template_slug="goblin-warrior",
                zone_id="zone:a",
            )
        ]

    async def _run(hero_intent: PlayerIntent):
        start = await start_combat(
            session_id="e2e-c06-s03",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:a"], edges=[]),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await submit_player_intent(start.handle, actor_id="char:hero", intent=hero_intent)
        await advance_monster_turn(start.handle)
        return live

    # Run A: no Shield readied.
    live_a = run_async(_run(PlayerIntent(intent_type="pass")))
    attacks_a = [e for e in events_of(live_a, AttackRolled) if e.target_id == "char:hero"]
    assert attacks_a
    rolled_a = attacks_a[0]
    assert rolled_a.roll_total == 11
    assert rolled_a.is_hit is True
    damage_a = [e for e in events_of(live_a, DamageApplied) if e.target_id == "char:hero"]
    assert damage_a
    assert damage_a[0].damage_type == "slashing"

    # Run B: Shield readied.
    live_b = run_async(
        _run(
            PlayerIntent(
                intent_type="ready",
                spell_id="shield",
                slot_level=1,
                reaction_trigger="hit_by_attack",
            )
        )
    )
    attacks_b = [e for e in events_of(live_b, AttackRolled) if e.target_id == "char:hero"]
    assert attacks_b
    rolled_b = attacks_b[0]
    assert rolled_b.roll_total == 11  # identical natural roll — Shield never touches it
    assert rolled_b.is_hit is False  # 11 < 10 + 5
    assert not [e for e in events_of(live_b, DamageApplied) if e.target_id == "char:hero"]

    reactions_b = [
        e
        for e in events_of(live_b, ReactionTriggered)
        if e.actor_id == "char:hero" and e.reaction_name == "shield"
    ]
    assert reactions_b
    applied_b = [e for e in events_of(live_b, EffectApplied) if e.effect.target_id == "char:hero"]
    assert applied_b

    reaction_idx = live_b.event_log.index(reactions_b[0])
    effect_idx = live_b.event_log.index(applied_b[0])
    attack_idx = live_b.event_log.index(rolled_b)
    assert reaction_idx < effect_idx < attack_idx

    # Expiry: still present through the rest of the current round; expires
    # at (not before) the START of char:hero's own next turn — the SECOND
    # TurnStarted(char:hero), not the goblin's TurnEnded right after the hit.
    hero_turn_starts_b = [e for e in events_of(live_b, TurnStarted) if e.actor_id == "char:hero"]
    assert len(hero_turn_starts_b) >= 2
    round2_start_idx = live_b.event_log.index(hero_turn_starts_b[1])
    expired_b = events_of(live_b, EffectExpired)
    expired_before_round2 = [e for e in expired_b if live_b.event_log.index(e) < round2_start_idx]
    assert not expired_before_round2
    assert expired_b
    assert live_b.event_log.index(expired_b[0]) >= round2_start_idx


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s04_shield_vs_magic_missile_zero_force_damage():
    """C06-S04: Shield vs Magic Missile: the reactor takes zero force
    damage from the triggering cast.

    SRD 5.2 §Spell Descriptions (Shield, same canonical text as C06-S03:
    "...and you take no damage from Magic Missile."); Magic Missile:
    canonical
    packages/dnd5e-srd-data/src/dnd5e_srd_data/canonical/spells/magic-missile.json
    (single damage-kind activity, 1d4+1 force per the engine's per-target
    DamageApplied event, target.affects.count "2 + @item.level"); engine:
    exhaustive grep for "force"/"magic_missile"/"immun" across
    packages/dnd5e-engine/src/ finds no per-spell damage-immunity hook of
    any kind — independent of, and compounding on top of, C06-S03's AC gap
    (Magic Missile has no attack roll at all).
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:target",
                name="Target",
                initiative=20,
                hp_current=20,
                hp_max=20,
                class_slug="wizard",
                spells_known=["shield"],
                spell_slots={1: 2},
                zone_id="zone:a",
            ),
            PartyMemberSpec(
                entity_id="char:caster",
                name="Caster",
                initiative=15,
                hp_current=20,
                hp_max=20,
                spells_known=["magic-missile"],
                spell_slots={1: 2},
                zone_id="zone:a",
            ),
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:bystander",
                entity_type="Monster",
                name="Bystander",
                initiative=1,
                hp_current=200,
                hp_max=200,
                ac=99,
                zone_id="zone:b",
            )
        ]

    async def _run(target_intent: PlayerIntent):
        start = await start_combat(
            session_id="e2e-c06-s04",
            party=_party(),
            encounter=_encounter(),
            scene_zones=SceneTopology(zones=["zone:a", "zone:b"], edges=[]),
            rng_seed=3,
        )
        live = _get_live(start.handle)
        await submit_player_intent(start.handle, actor_id="char:target", intent=target_intent)
        await submit_player_intent(
            start.handle,
            actor_id="char:caster",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                slot_level=1,
                target_id="char:target",
            ),
        )
        return live

    # Run A: no Shield readied.
    live_a = run_async(_run(PlayerIntent(intent_type="pass")))
    unshielded_total = sum(
        e.amount
        for e in events_of(live_a, DamageApplied)
        if e.target_id == "char:target" and e.damage_type == "force"
    )
    assert 2 <= unshielded_total <= 5

    # Run B: Shield readied against the Magic Missile trigger.
    live_b = run_async(
        _run(
            PlayerIntent(
                intent_type="ready",
                spell_id="shield",
                slot_level=1,
                reaction_trigger="targeted_by_magic_missile",
            )
        )
    )
    shielded_total = sum(
        e.amount
        for e in events_of(live_b, DamageApplied)
        if e.target_id == "char:target" and e.damage_type == "force"
    )
    assert shielded_total == 0

    reactions_b = [
        e
        for e in events_of(live_b, ReactionTriggered)
        if e.actor_id == "char:target" and e.reaction_name == "shield"
    ]
    assert reactions_b
    # Catalog: ReactionTriggered fires before the damage activity resolves; the
    # resolution may emit no DamageApplied at all or one with amount == 0.
    force_events_b = [
        e
        for e in events_of(live_b, DamageApplied)
        if e.target_id == "char:target" and e.damage_type == "force"
    ]
    if force_events_b:
        assert live_b.event_log.index(reactions_b[0]) < live_b.event_log.index(force_events_b[0])


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s05_monster_reactor_opportunity_attack_on_pc_move():
    """C06-S05: A monster reactor makes an opportunity attack when a PC
    leaves its reach without Disengage (mirror of the shipped PC-reactor
    path).

    SRD 5.2 §Opportunity Attacks (chapter-1/combat.yml: "You can make an
    Opportunity Attack when a creature that you can see leaves your reach.
    To make the attack, take a Reaction to make one melee attack with a
    weapon or an Unarmed Strike against that creature. The attack occurs
    right before it leaves your reach."); engine: the ONLY shipped AoO path
    is orchestrator.py::_fire_pc_opportunity_attacks_on_move, called only
    from advance_monster_turn's movement loop — the PC move handler,
    _handle_move, has zero opportunity-attack logic of any kind. The
    goblin's reaction_available defaults True — no arming/readying needed,
    mirroring the shipped PC-reactor path's own "always-on if
    reaction_available" shape.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c06-s05",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    ac=10,
                    base_speed=30,
                    zone_id="zone:a",
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:goblin",
                    entity_type="Monster",
                    name="Goblin",
                    initiative=1,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    monster_template_slug="goblin-warrior",
                    zone_id="zone:a",
                )
            ],
            scene_zones=SceneTopology(
                zones=["zone:a", "zone:b"],
                edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=10)],
            ),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id="zone:b"),
        )
        return live

    live = run_async(_run())

    reaction_intents = [
        e
        for e in events_of(live, IntentSubmitted)
        if e.actor_id == "mon:goblin" and e.intent_type == "reaction"
    ]
    assert reaction_intents
    assert reaction_intents[0].target_id == "char:hero"

    attacks = [
        e
        for e in events_of(live, AttackRolled)
        if e.attacker_id == "mon:goblin" and e.target_id == "char:hero"
    ]
    assert attacks
    assert attacks[0].is_opportunity_attack is True

    moved = [e for e in events_of(live, ActorMoved) if e.actor_id == "char:hero"]
    assert moved
    assert moved[-1].from_zone == "zone:a"
    assert moved[-1].to_zone == "zone:b"
    assert moved[-1].distance_ft == 10

    # "The attack occurs right before it leaves your reach" — the AoO
    # precedes the move landing.
    reaction_idx = live.event_log.index(reaction_intents[0])
    move_idx = live.event_log.index(moved[-1])
    assert reaction_idx < move_idx

    # Reaction is spent on use, regardless of hit/miss.
    goblin = next(c for c in live.initiative if c.entity_id == "mon:goblin")
    assert goblin.reaction_available is False


@xfail_cluster(6, "Reactions & off-turn intents")
def test_c06_s06_disengage_suppresses_opportunity_attack():
    """C06-S06: Disengage lets a PC leave a monster's reach with identical
    movement and provokes no opportunity attack.

    SRD 5.2 §Actions in Combat, Disengage (chapter-1/actions.yml: "Your
    movement doesn't provoke Opportunity Attacks for the rest of the
    turn."); §Opportunity Attacks, Avoiding: "You can avoid provoking an
    Opportunity Attack by taking the Disengage action."; engine:
    "disengage" is an IntentType Literal member (events.py) with zero
    handling code, zero tests, anywhere, today.

    Hard cross-entry dependency: this scenario is only meaningful once
    C06-S05 lands (there is otherwise no monster-reactor AoO to suppress).
    Both halves of the Setup/Script below mirror C06-S05's exactly.

    Today, verified (not asserted below — see the catalog entry): Run B's
    disengage-then-move sequence is CONSTRUCTIVELY IMPOSSIBLE today, not
    merely unimplemented for suppression purposes. "disengage" is not one
    of the turn-non-ending early-return intents ("move"/"move_mark"/
    "dash"), so submitting it alone unconditionally advances the turn
    (IntentSubmitted(disengage) -> TurnEnded(char:hero) ->
    TurnStarted(mon:goblin)); the follow-up "move" call then raises
    IntentRejectedError(reason="not_actor_turn", ...) because it is no
    longer char:hero's turn. The Script below is transcribed as the
    catalog's FUTURE script (Disengage must become a fourth
    turn-non-ending early-return branch); today it fails via that raised
    IntentRejectedError, which is what pins this scenario strict-xfail.
    """

    def _party():
        return [
            PartyMemberSpec(
                entity_id="char:hero",
                name="Hero",
                initiative=20,
                hp_current=20,
                hp_max=20,
                ac=10,
                base_speed=30,
                zone_id="zone:a",
            )
        ]

    def _encounter():
        return [
            EncounterMemberSpec(
                entity_id="mon:goblin",
                entity_type="Monster",
                name="Goblin",
                initiative=1,
                hp_current=7,
                hp_max=7,
                ac=13,
                monster_template_slug="goblin-warrior",
                zone_id="zone:a",
            )
        ]

    def _scene():
        return SceneTopology(
            zones=["zone:a", "zone:b"],
            edges=[ZoneEdge(a="zone:a", b="zone:b", distance_ft=10)],
        )

    async def _run_a():
        # Run A: no Disengage — C06-S05's own script, reused as the baseline.
        start = await start_combat(
            session_id="e2e-c06-s06-a",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id="zone:b"),
        )
        return live

    async def _run_b():
        # Run B: Disengage then move, same turn (post-fix Script).
        start = await start_combat(
            session_id="e2e-c06-s06-b",
            party=_party(),
            encounter=_encounter(),
            scene_zones=_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="disengage"),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="move", target_zone_id="zone:b"),
        )
        return live

    live_a = run_async(_run_a())
    reaction_intents_a = [
        e
        for e in events_of(live_a, IntentSubmitted)
        if e.actor_id == "mon:goblin" and e.intent_type == "reaction"
    ]
    assert reaction_intents_a
    attacks_a = [e for e in events_of(live_a, AttackRolled) if e.is_opportunity_attack]
    assert attacks_a

    live_b = run_async(_run_b())

    disengage_intents = [
        e
        for e in events_of(live_b, IntentSubmitted)
        if e.actor_id == "char:hero" and e.intent_type == "disengage"
    ]
    assert disengage_intents

    moved_b = [e for e in events_of(live_b, ActorMoved) if e.actor_id == "char:hero"]
    assert moved_b
    assert moved_b[-1].from_zone == "zone:a"
    assert moved_b[-1].to_zone == "zone:b"
    assert moved_b[-1].distance_ft == 10

    assert not [e for e in events_of(live_b, AttackRolled) if e.is_opportunity_attack]
    goblin_b = next(c for c in live_b.initiative if c.entity_id == "mon:goblin")
    assert goblin_b.reaction_available is True
