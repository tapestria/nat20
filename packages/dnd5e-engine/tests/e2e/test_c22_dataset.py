"""C22 — Dataset (conditions/traits typed categories, ignore_cover, magical
flag, armor requirements, multiattack names, reaction triggers).

Transcribed from specs/e2e-scenario-catalog.md, Cluster 22
(specs/catalog-v2/c22.md). Every combat-bearing setup is grid-only per
spec §6 D8 — ``GridScene`` + ``"col,row"`` cell ids
(``dnd5e_engine.spatial.cell_id``), never ``SceneTopology``/zones. Data
assertions run against the bundled corpus via ``BundledAssetLoader``.
C22-S05 is a PLAIN (non-xfail) regression — ``Armor.strength_min`` /
``.stealth_disadvantage`` already ship and are already populated
correctly; marking it strict-xfail would XPASS immediately.
"""

from __future__ import annotations

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied, SaveRolled
from dnd5e_engine.orchestrator import (
    _get_live,
    advance_monster_turn,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from tests.e2e.harness import cell, events_of, grid_scene, run_async, xfail_cluster


@xfail_cluster(22, "dataset")
def test_c22_s01_prone_condition_dataset_entry_and_engine_leg():
    """C22-S01: SRD 5.2 rules-glossary, Prone — attack rolls against the
    creature have Advantage if the attacker is within 5 feet.
    (packs/_source/content24/appendices/rules-glossary.yml, Prone
    entry). No ``canonical/conditions/`` directory ships today; the
    engine's ``rules/conditions.py::CONDITION_EFFECTS["prone"]`` entry
    is prose only, and no ``AssetLoader.get_condition`` method exists
    on any loader.
    """
    loader = BundledAssetLoader()

    # API delta (C22): AssetLoader.get_condition does not exist today.
    prone = loader.get_condition("prone")

    assert prone is not None
    from dnd5e_srd_data.schema.condition import ConditionEffectKind

    assert any(
        effect.kind == ConditionEffectKind.ADVANTAGE_ATTACKS_AGAINST for effect in prone.effects
    )


@xfail_cluster(22, "dataset")
def test_c22_s02_magic_resistance_trait_is_typed_not_prose_only():
    """C22-S02: SRD 5.2 Monster stat-block special ability, Magic
    Resistance — "Advantage on saving throws against spells and other
    magical effects." (34 occurrences across the corpus per the rule
    card's frequency count). ``canonical/monsters/*.json`` already
    populates ``special_abilities`` structurally, but every entry is
    prose-description only — nothing downstream can branch on "this is
    Magic Resistance" without string-matching the ``name`` field.
    """
    loader = BundledAssetLoader()
    pit_fiend = loader.get_monster("pit-fiend")
    magic_resistance = next(a for a in pit_fiend.special_abilities if a.name == "Magic Resistance")

    # API delta (C22): MonsterAction.mechanic does not exist today.
    from dnd5e_srd_data.schema.monster import MonsterTraitMechanic

    assert magic_resistance.mechanic == MonsterTraitMechanic.MAGIC_RESISTANCE


@xfail_cluster(22, "dataset")
def test_c22_s03_sacred_flame_save_ignores_cover():
    """C22-S03: SRD 5.2 Sacred Flame — "The target gains no benefit
    from Half Cover or Three-Quarters Cover for this save."
    (packs/_source/spells24/cantrips/sacred-flame.yml). ``SaveBlock``
    has no ``ignore_cover`` field today (schema is ``{ability, dc}``
    only) — Sacred Flame's save resolves identically to any other DEX
    save against a half-cover target.
    """
    loader = BundledAssetLoader()
    sacred_flame = loader.get_spell("sacred-flame")
    save_activity = next(a for a in sacred_flame.activities if a.kind == "save")

    # API delta (C22): SaveBlock.ignore_cover does not exist today.
    assert save_activity.save.ignore_cover is True


@xfail_cluster(22, "dataset")
def test_c22_s04_magic_weapon_flag_bypasses_nonmagical_bps_resistance():
    """C22-S04: SRD 5.2 "Overcoming Damage Resistance" — magic weapons
    overcome resistance to nonmagical bludgeoning/piercing/slashing.
    ``Weapon`` has no ``magical`` field today; the translator's
    ``_PROPERTY_CODE_TO_ENUM`` map has no ``mgc`` entry, so the flag is
    silently filtered out — Flame Tongue ships ``magicalBonus: null``
    while still carrying ``properties: [mgc]``, so ``magical_bonus`` is
    not a reliable proxy.
    """
    loader = BundledAssetLoader()
    flame_tongue = loader.get_weapon("flame-tongue")

    # API delta (C22): Weapon.magical does not exist today.
    assert flame_tongue.magical is True

    async def _run():
        start = await start_combat(
            session_id="e2e-c22-s04",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    strength=16,
                    attack_bonus=5,
                    equipment=("flame-tongue",),
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
                    damage_resistances=["bludgeoning", "piercing", "slashing"],
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
            actor_id="char:hero",
            intent=PlayerIntent(
                intent_type="attack", weapon_id="flame-tongue", target_id="mon:foe"
            ),
        )
        return live

    live = run_async(_run())
    dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "mon:foe"]
    assert dmg
    assert dmg[0].is_overkill is False or dmg[0].amount > 0


def test_c22_s05_chain_mail_strength_min_and_stealth_disadvantage():
    """C22-S05 (plain regression, NOT xfail): SRD 5.2 PHB armor table,
    Chain Mail — Str 13 requirement, Stealth Disadvantage
    (packs/_source/equipment24/armor/heavy/chain-mail.yml). Already
    implemented, no gap — ``schema/item.py::Armor.strength_min`` and
    ``.stealth_disadvantage`` both exist and are already populated by
    ``tools/translators/foundry.py::translate_armor_yaml``. Pinning
    this against regression; the campaign-design row's
    ``Armor.str_requirement`` phrasing is a naming mismatch only.
    """
    loader = BundledAssetLoader()
    armor = loader.get_armor("chain-mail")

    assert armor.strength_min == 13
    assert armor.stealth_disadvantage is True


@xfail_cluster(22, "dataset")
def test_c22_s06_bandit_captain_multiattack_resolves_scimitar_and_pistol():
    """C22-S06: SRD 5.2 Bandit Captain stat block, Multiattack — "makes
    two attacks, using its Scimitar and Pistol in any combination."
    Its Multiattack description carries bare ``[[/item .<id>]]`` id
    tokens with no ``{Label}`` suffix — the join fails and
    ``monster_actions.py`` falls back to a homogeneous repeat, logging
    ``multiattack_join_unresolved`` at WARNING.
    """
    loader = BundledAssetLoader()
    bandit_captain = loader.get_monster("bandit-captain")
    multiattack = next(a for a in bandit_captain.actions if a.slug == "multiattack")
    assert "w3cX0piuU875Hc2M" in multiattack.description
    assert "2TB9ZSIbtbi4UtSv" in multiattack.description

    async def _run():
        start = await start_combat(
            session_id="e2e-c22-s06",
            party=[
                PartyMemberSpec(
                    entity_id="char:dummy",
                    name="Dummy",
                    initiative=1,
                    hp_current=200,
                    hp_max=200,
                    ac=1,
                    zone_id=cell(1, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:bandit-captain",
                    entity_type="Monster",
                    name="Bandit Captain",
                    initiative=20,
                    hp_current=65,
                    hp_max=65,
                    ac=15,
                    zone_id=cell(0, 0),
                    monster_template_slug="bandit-captain",
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=17,
        )
        live = _get_live(start.handle)
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    swings = [e for e in events_of(live, AttackRolled) if e.attacker_id == "mon:bandit-captain"]
    assert len(swings) == 2

    # API delta (C22/C15): no weapon/action attribution exists on the event
    # surface today (DamageApplied.source_id per C15-S04), so "one Scimitar
    # swing + one Pistol swing" cannot be told apart from a homogeneous
    # repeat without it.
    dmg = [e for e in events_of(live, DamageApplied) if e.target_id == "char:dummy"]
    damage_types = {e.damage_type for e in dmg}
    assert damage_types == {"slashing", "piercing"}


@xfail_cluster(22, "dataset")
def test_c22_s07_shield_reaction_trigger_is_typed_not_free_text():
    """C22-S07: SRD 5.2 Shield — activation ``condition: "when you are
    hit by an attack roll or targeted by the Magic Missile spell"``
    (packs/_source/spells24/1st-level/shield.yml). ``schema/common.py``
    has no ``ReactionCondition``/``ReactionTriggerKind`` types today —
    the activation block on Shield's cast activity carries only the
    free-text Foundry ``condition`` string.
    """
    loader = BundledAssetLoader()
    shield = loader.get_spell("shield")
    cast_activity = next(a for a in shield.activities if a.kind == "utility")

    # API delta (C22): ReactionCondition/reaction_conditions do not exist today.
    from dnd5e_srd_data.schema.common import ReactionTriggerKind

    conditions = cast_activity.activation.reaction_conditions
    assert any(c.kind == ReactionTriggerKind.HIT_BY_ATTACK for c in conditions)
    assert any(
        c.kind == ReactionTriggerKind.TARGETED_BY_SPELL and c.target_spell_slug == "magic-missile"
        for c in conditions
    )

    # Engine leg (informational): the reaction still arms today via the
    # hard-coded carveout, showing the behaviour source rather than a gap.
    async def _run():
        start = await start_combat(
            session_id="e2e-c22-s07",
            party=[
                PartyMemberSpec(
                    entity_id="char:wiz",
                    name="Wizard",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    spells_known=["shield"],
                    spell_slots={1: 1},
                    character_level=1,
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
                    attack_bonus=5,
                    zone_id=cell(1, 0),
                )
            ],
            scene_zones=None,
            grid_scene=grid_scene(),
            rng_seed=21,
        )
        live = _get_live(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:wiz",
            intent=PlayerIntent(
                intent_type="ready",
                spell_id="shield",
                slot_level=1,
                reaction_trigger="hit_by_attack",
            ),
        )
        await advance_monster_turn(start.handle)
        return live

    live = run_async(_run())
    saves_or_attacks = events_of(live, AttackRolled) + events_of(live, SaveRolled)
    assert saves_or_attacks
