"""C17 — Spell slots & rests.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 17
(specs/catalog-v2/c17.md). Most scenarios are pure derivation/rest
questions (no combat handle needed, per the C09-S01/S02 convention);
C17-S05/S06 drive a live combat to pin an upcast/reaction gap against the
real bundled corpus.
"""

from __future__ import annotations

import random

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import DamageApplied, ReactionTriggered
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.rest import HitDicePool
from dnd5e_engine.specs import EncounterMemberSpec, GridScene, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async


def test_c17_s01_wizard_full_caster_slot_table_has_no_engine_derivation():
    """C17-S01: SRD 5.2 — "a level 3 Wizard has four level 1 spell slots
    and two level 2 slots." (packs/_source/content24/chapter-7/spells.yml:503-517,
    "Spell Level" -> "Spell Slots"); Foundry's ``SPELL_SLOT_TABLE`` full-
    caster row for level 5 -> ``[4, 3, 2]`` (config.mjs:3027-3047). No
    function reads a class's ``spellcasting.progression`` to project a
    level -> slot-table row today; a host must hand-compute the flat
    ``spell_slots`` dict itself.
    """
    from dnd5e_engine.build_spec import derive_spell_slots  # API delta (C17)

    slots = derive_spell_slots(class_slug="wizard", progression="full", level=5)

    assert slots == {1: 4, 2: 3, 3: 2}


def test_c17_s02_pact_magic_has_no_separate_pool_and_recovers_on_short_rest():
    """C17-S02: SRD 5.2 — "You regain all expended Pact Magic spell slots
    when you finish a Short or Long Rest. ... when you're a level 5
    Warlock, you have two level 3 spell slots."
    (packs/_source/classes24/warlock/class-features/pact-magic.yml:27-34).
    ``resolve_short_rest``'s signature carries no ``pact_slots``/
    ``pact_slot_max`` parameter at all today — Pact Magic is the ONLY
    slot pool the SRD recovers on a Short Rest, and there is no seam to
    exercise that at all.
    """
    from dnd5e_engine.rest import resolve_short_rest

    pool = HitDicePool(hit_die_size=8, dice_remaining=5, dice_total=5)

    outcome = resolve_short_rest(
        pool,
        dice_to_spend=0,
        con_modifier=3,
        rng=random.Random(1),
        pact_slots={3: 0},
        pact_slot_max={3: 2},
    )

    assert outcome.pact_slots == {3: 2}


def test_c17_s03_multiclass_paladin_wizard_has_no_per_class_level_input():
    """C17-S03: SRD 5.2 — "You determine your available spell slots by
    adding together the following: All your levels in the Bard, Cleric,
    Druid, Sorcerer, and Wizard classes; Half your levels (round up) in
    the Paladin and Ranger classes."
    (packs/_source/content24/chapter-2/character-creation.yml:784,
    "Multiclassing" -> "Spellcasting" -> "Spell Slots"). Paladin 2 (half,
    round UP) -> 1, Wizard 3 (full) -> 3, combined caster level 4 ->
    ``{1: 4, 2: 3}``. ``CharacterBuildSpec`` carries exactly ONE
    ``class_slug``/``level`` pair (``extra="forbid"``) — a second class
    is structurally unrepresentable today.
    """
    from dnd5e_engine.build_spec import CharacterBuildSpec, derive_multiclass_slots

    spec = CharacterBuildSpec(
        species_slug="human", classes={"paladin": 2, "wizard": 3}
    )  # API delta (C17/C19)
    slots = derive_multiclass_slots(spec.classes)

    assert slots == {1: 4, 2: 3}


def test_c17_s04_long_rest_restores_slots_and_reduces_exhaustion():
    """C17-S04: SRD 5.2 §Long Rest — "Exhaustion Reduced. If you have the
    Exhaustion condition, its level decreases by 1."
    (packs/_source/content24/appendices/rules-glossary.yml:3978-4020,
    rule "Long Rest"); spell slots — "Finishing a Long Rest restores any
    expended spell slots." (packs/_source/content24/chapter-7/spells.yml:517).
    ``resolve_long_rest``'s full signature is
    ``(pool, hp_current, hp_max) -> RestOutcome`` — no ``spell_slots``/
    ``exhaustion_level`` parameter exists, and ``RestOutcome`` has no
    field to report either.
    """
    from dnd5e_engine.rest import resolve_long_rest

    pool = HitDicePool(hit_die_size=6, dice_remaining=1, dice_total=3)

    outcome = resolve_long_rest(
        pool,
        hp_current=8,
        hp_max=20,
        spell_slots={1: 0, 2: 0},
        spell_slot_max={1: 4, 2: 2},
        exhaustion_level=2,
    )

    assert outcome.hp_current == 20
    assert outcome.spell_slots == {1: 4, 2: 2}
    assert outcome.exhaustion_level == 1


def test_c17_s05_magic_missile_upcast_at_slot_3_should_fire_5_darts():
    """C17-S05: Magic Missile — "You create three glowing darts of
    magical force. ... Using a Higher-Level Spell Slot. The spell
    creates one more dart for each spell slot level above 1."
    (packs/_source/spells24/1st-level/magic-missile.yml:5-11). At
    ``slot_level=3``, ``target.affects.count == "2 + @item.level"``
    resolves to 5 darts. Today exactly 1 ``DamageApplied`` fires
    regardless of ``slot_level`` — ``activities/dice.py``'s scaling
    machinery reads only ``DamagePart.scaling``, never a target's
    ``affects.count`` field, and ``PlayerIntent.target_id`` is a single
    ``str | None`` with no multi-target/dart-count shape to route through.
    """

    async def _run():
        start = await start_combat(
            session_id="e2e-c17-s05",
            party=[
                PartyMemberSpec(
                    entity_id="char:wizard",
                    name="Wizard",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    intelligence=16,
                    class_slug="wizard",
                    character_level=5,
                    spells_known=["magic-missile"],
                    spell_slots={3: 1},
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=100,
                    hp_max=100,
                    ac=1,
                    zone_id=cell(6, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=1,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wizard",
            intent=PlayerIntent(
                intent_type="cast_spell",
                spell_id="magic-missile",
                target_id="mon:foe",
                slot_level=3,
            ),
        )
        return live

    live = run_async(_run())
    darts = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]

    assert len(darts) == 5
    for dart in darts:
        assert dart.damage_type == "force"
        assert 2 <= dart.amount <= 5


def test_c17_s06_counterspell_with_empty_slot_pool_or_out_of_range_still_fires_for_free():
    """C17-S06: two independent, co-located gates in
    ``_drain_counterspell_reaction`` — "No-slot readied reactions fire for
    free." AND "Counterspell range ungated at drain time." (both
    BACKLOG.md, "Reactions" section).

    Branch A (no slot): general Spell Slots rule — "When you cast a spell,
    you expend a slot of that spell's level or higher"
    (packs/_source/content24/chapter-7/spells.yml:503-517); no slot-gated
    cast should resolve without an available slot.
    ``_drain_counterspell_reaction`` contains ``if reactor_slots.get(cs_level, 0)
    > 0: ...`` with NO ``else`` branch — an EMPTY 3rd-level pool still
    lets the reaction fire and resolve for free today.

    Branch B (out of range): Counterspell's own typed data —
    ``range.value: '60'``, ``range.units: ft`` (confirmed:
    ``BundledAssetLoader().get_spell("counterspell").range ==
    RangeSpec(units=ft, value=60)``). ``_drain_counterspell_reaction``
    never checks range/LoS at all — a reactor 90 ft away (beyond the 60 ft
    Counterspell range) still drains its reaction and resolves today.

    Seed choice: ``rng_seed=9`` matches the catalog's own choice
    (inherited from C06-S01's seed-9 branch, which this scenario
    deliberately mirrors for the reactor/enemy-caster pairing) — kept
    unchanged per the task brief's binding note; the asserted relationship
    (a ``ReactionTriggered`` firing today despite the empty pool / the out-
    of-range separation) is what's under test, not the specific seed
    value. Initiative is set so the enemy caster's turn immediately
    follows the reactor's ``ready`` turn (``mon:target``'s initiative is
    kept BELOW the enemy caster's, unlike a naive numeric ordering, so the
    scripted second ``submit_player_intent`` lands on the enemy caster's
    own turn rather than raising ``not_actor_turn``) — empirically
    verified against the real engine for both branches below.
    """

    def _run(*, reactor_slots: dict, enemy_col: int, target_col: int):
        async def _inner():
            start = await start_combat(
                session_id=f"e2e-c17-s06-{enemy_col}",
                party=[
                    PartyMemberSpec(
                        entity_id="char:reactor",
                        name="Reactor",
                        initiative=20,
                        hp_current=30,
                        hp_max=30,
                        intelligence=18,
                        class_slug="wizard",
                        character_level=5,
                        spells_known=["counterspell"],
                        spell_slots=reactor_slots,
                        zone_id=cell(0, 0),
                    ),
                    PartyMemberSpec(
                        entity_id="char:enemy_caster",
                        name="Enemy Caster",
                        initiative=15,
                        hp_current=30,
                        hp_max=30,
                        intelligence=16,
                        class_slug="wizard",
                        character_level=5,
                        spells_known=["fireball"],
                        spell_slots={3: 1},
                        zone_id=cell(enemy_col, 0),
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
                        ac=10,
                        zone_id=cell(target_col, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=GridScene(width=30, height=10, cell_size_ft=5),
                rng_seed=9,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:reactor",
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

        return run_async(_inner())

    # Branch A — empty slot pool, well within range (1 cell / 5 ft).
    live_a = _run(reactor_slots={3: 0}, enemy_col=1, target_col=2)
    assert not events_of(live_a, ReactionTriggered)

    # Branch B — a real slot available, but 90 ft (18 cells) separation,
    # beyond Counterspell's 60 ft range.
    live_b = _run(reactor_slots={3: 1}, enemy_col=18, target_col=19)
    assert not events_of(live_b, ReactionTriggered)
