"""C13 — Concentration lifecycle.

Transcribed from specs/e2e-scenario-catalog.md, Cluster 13
(specs/catalog-v2/c13.md). Grid-only setups; all assertions are
RNG-robust (presence/shape/bounds/same-seed A-B deltas, never exact roll
values). Concentration-chain reads go through the sanctioned
``dnd5e_engine.testing.registry`` seam — ``LiveCombatView`` has no
concentration projection today.
"""

from __future__ import annotations

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import (
    ConcentrationCheck,
    ConcentrationDropped,
    DamageApplied,
    Death,
    EffectExpired,
    Unconscious,
)
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


def test_c13_s01_second_concentration_spell_ends_the_first():
    """C13-S01: SRD 5.2 — "You lose Concentration on an effect the moment
    you start casting a spell that requires Concentration or activate
    another effect that requires Concentration."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml:5258-5261).
    ``existing_concentration`` is built in the orchestrator but nothing
    consumes it before ``_record_effect_lifecycle_links`` appends to
    ``concentration_chain`` — the caster's chain grows unbounded instead
    of dropping the prior effect.

    Script repair (assertions untouched): Bless is an Action cast and ends
    the turn, so the second cast happens on the cleric's round-2 turn
    (fighter passes, foe acts from out of reach) — recorded in
    docs/migration/v0.5-to-v0.6.md.
    """
    from dnd5e_engine.testing import registry

    async def _run():
        start = await start_combat(
            session_id="e2e-c13-s01",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    spell_slots={1: 2},
                    spells_known=["bless", "shield-of-faith"],
                    wisdom=16,
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:fighter",
                    name="Fighter",
                    initiative=15,
                    hp_current=20,
                    hp_max=20,
                    ac=15,
                    zone_id=cell(1, 0),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=12,
                    zone_id=cell(9, 9),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=7,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="bless", target_id="char:fighter"
            ),
        )
        chain_after_bless = list(
            registry[start.handle.handle_id].concentration_chain.get("char:cleric") or []
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:fighter",
            intent=PlayerIntent(intent_type="pass"),
        )
        await advance_monster_turn(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="shield-of-faith", target_id="char:cleric"
            ),
        )
        chain_after_shield = list(
            registry[start.handle.handle_id].concentration_chain.get("char:cleric") or []
        )
        return live, chain_after_bless, chain_after_shield

    live, chain_after_bless, chain_after_shield = run_async(_run())

    assert len(chain_after_bless) == 1
    # After the second concentration cast, the chain must hold exactly the
    # Shield of Faith entry — never both.
    assert len(chain_after_shield) == 1
    assert events_of(live, ConcentrationDropped)
    assert [e for e in events_of(live, EffectExpired) if e.reason == "concentration_drop"]


def test_c13_s02_damage_triggers_concentration_check_with_con_modifier():
    """C13-S02: SRD 5.2 — "If you take damage, you must succeed on a
    Constitution saving throw to maintain Concentration. The DC equals 10
    or half the damage taken (round down), whichever number is higher, up
    to a maximum DC of 30."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml:5261-5266).
    F1c gave ``_emit_apply_damage`` the real CON modifier and F2c emits the
    harmonised ``ConcentrationCheck`` (alongside the legacy ``SaveRolled``
    until v0.7); F1c also added ``PartyMemberSpec.save_proficiencies``, so a
    CON-save-proficient caster IS expressible now (set below). The residual gap
    this scenario still pins is the DC: it is not capped at the SRD maximum
    of 30.
    """

    def _foe():
        return EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=1,
            hp_current=30,
            hp_max=30,
            ac=8,
            attack_bonus=10,
            damage_dice="8d6",
            damage_type="fire",
            zone_id=cell(1, 0),
        )

    def _cleric_kwargs(constitution: int, proficient: bool) -> dict:
        kwargs: dict = dict(
            entity_id="char:cleric",
            name="Cleric",
            initiative=20,
            hp_current=40,
            hp_max=40,
            constitution=constitution,
            spell_slots={1: 1},
            spells_known=["bless"],
            zone_id=cell(0, 0),
        )
        if proficient:
            # F1c added this field; before it, ConfigDict(extra="forbid")
            # rejected the kwarg and a CON-save-proficient caster was
            # inexpressible. The scenario's residual gap is the missing DC 30
            # cap, not this.
            kwargs["save_proficiencies"] = ("con",)
        return kwargs

    def _run(constitution: int, proficient: bool):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c13-s02",
                party=[PartyMemberSpec(**_cleric_kwargs(constitution, proficient))],
                encounter=[_foe()],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=42,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:cleric",
                intent=PlayerIntent(
                    intent_type="cast_spell", spell_id="bless", target_id="char:cleric"
                ),
            )
            await advance_monster_turn(start.handle)
            return live

        return run_async(_inner())

    live_a = _run(10, False)
    live_b = _run(20, True)

    damage_a = [e for e in events_of(live_a, DamageApplied) if e.target_id == "char:cleric"]
    damage_b = [e for e in events_of(live_b, DamageApplied) if e.target_id == "char:cleric"]
    assert len(damage_a) == 1
    assert len(damage_b) == 1

    checks_a = events_of(live_a, ConcentrationCheck)
    checks_b = events_of(live_b, ConcentrationCheck)
    assert len(checks_a) == 1
    assert len(checks_b) == 1

    check_a, check_b = checks_a[0], checks_b[0]
    assert check_a.dc == max(10, min(30, damage_a[0].amount // 2))
    assert check_b.dc == max(10, min(30, damage_b[0].amount // 2))
    # The real CON modifier + proficiency thread means Run B's roll strictly
    # beats Run A's for the identical d20 draw under the same seed.
    assert check_b.roll_total > check_a.roll_total


def test_c13_s03_caster_reduced_to_zero_hp_ends_concentration():
    """C13-S03: SRD 5.2 — "Your Concentration ends if you have the
    Incapacitated condition or you die."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml:5266-5268).
    ``_drop_concentration`` has exactly one call site (the failed CON-save
    path) — death/unconscious never calls it.
    """
    from dnd5e_engine.testing import registry

    async def _run():
        start = await start_combat(
            session_id="e2e-c13-s03",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=1,
                    hp_max=20,
                    ac=1,
                    spell_slots={1: 1},
                    spells_known=["bless"],
                    zone_id=cell(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=12,
                    attack_bonus=15,
                    damage_dice="2d6",
                    damage_type="slashing",
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=5,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="bless", target_id="char:cleric"
            ),
        )
        await advance_monster_turn(start.handle)
        chain = list(registry[start.handle.handle_id].concentration_chain.get("char:cleric") or [])
        return live, chain

    live, chain = run_async(_run())

    death_or_unconscious = events_of(live, Death) + events_of(live, Unconscious)
    assert death_or_unconscious
    assert events_of(live, ConcentrationDropped)
    assert [e for e in events_of(live, EffectExpired) if e.reason == "concentration_drop"]
    assert chain == []


@xfail_cluster(13, "concentration lifecycle")
def test_c13_s04_voluntary_drop_costs_no_action():
    """C13-S04: SRD 5.2 — "The creator can end Concentration at any time
    (no action required)."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml:5255-5257).
    There is no ``drop_concentration`` ``IntentType`` member and no public
    entry point that calls ``_drop_concentration`` outside the failed
    CON-save path.
    """
    from dnd5e_engine.events import AttackRolled
    from dnd5e_engine.testing import registry

    async def _run():
        start = await start_combat(
            session_id="e2e-c13-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:cleric",
                    name="Cleric",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    spell_slots={1: 1},
                    spells_known=["bless"],
                    zone_id=cell(0, 0),
                ),
                PartyMemberSpec(
                    entity_id="char:fighter",
                    name="Fighter",
                    initiative=15,
                    hp_current=20,
                    hp_max=20,
                    ac=15,
                    zone_id=cell(1, 0),
                ),
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=30,
                    hp_max=30,
                    ac=15,
                    zone_id=cell(4, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=9,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(
                intent_type="cast_spell", spell_id="bless", target_id="char:fighter"
            ),
        )
        # API delta (C13): "drop_concentration" is not a member of
        # IntentType today — PlayerIntent's Literal validation rejects it.
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(intent_type="drop_concentration"),
        )
        await submit_player_intent(
            start.handle,
            actor_id="char:cleric",
            intent=PlayerIntent(intent_type="attack", weapon_id="mace", target_id="mon:foe"),
        )
        chain = list(registry[start.handle.handle_id].concentration_chain.get("char:cleric") or [])
        return live, chain

    live, chain = run_async(_run())

    assert events_of(live, ConcentrationDropped)
    assert [e for e in events_of(live, EffectExpired) if e.reason == "concentration_drop"]
    assert chain == []
    attacks = [e for e in events_of(live, AttackRolled) if e.attacker_id == "char:cleric"]
    assert attacks


def test_c13_s05_concentration_dc_caps_at_30():
    """C13-S05: SRD 5.2 — "...up to a maximum DC of 30."
    (packs/_source/content24/appendices/appendix-d-rule-references.yml:5261-5266).
    ``orchestrator.py`` computes ``dc = max(10, event.amount // 2)`` with
    no upper clamp — a large damage roll can push the DC well past 30.
    """

    def _cleric():
        return PartyMemberSpec(
            entity_id="char:cleric",
            name="Cleric",
            initiative=20,
            hp_current=200,
            hp_max=200,
            constitution=10,
            spell_slots={1: 1},
            spells_known=["bless"],
            zone_id=cell(0, 0),
        )

    def _run(damage_dice: str):
        async def _inner():
            start = await start_combat(
                session_id="e2e-c13-s05",
                party=[_cleric()],
                encounter=[
                    EncounterMemberSpec(
                        entity_id="mon:foe",
                        entity_type="Monster",
                        name="Foe",
                        initiative=1,
                        hp_current=30,
                        hp_max=30,
                        ac=8,
                        attack_bonus=10,
                        damage_dice=damage_dice,
                        damage_type="fire",
                        zone_id=cell(1, 0),
                    )
                ],
                scene_zones=None,
                grid_scene=grid_scene(),
                rng_seed=13,
            )
            live = _get_live(start.handle)
            await submit_player_intent(
                start.handle,
                actor_id="char:cleric",
                intent=PlayerIntent(
                    intent_type="cast_spell", spell_id="bless", target_id="char:cleric"
                ),
            )
            await advance_monster_turn(start.handle)
            return live

        return run_async(_inner())

    live_a = _run("4d6")
    live_b = _run("20d6")

    checks_a = events_of(live_a, ConcentrationCheck)
    checks_b = events_of(live_b, ConcentrationCheck)
    assert len(checks_a) == 1
    assert len(checks_b) == 1
    assert 10 <= checks_a[0].dc <= 12
    assert checks_b[0].dc <= 30
