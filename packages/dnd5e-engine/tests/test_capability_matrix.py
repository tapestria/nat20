"""Keeps ``docs/capabilities.md`` honest.

The capability matrix publishes hard counts ("105 of 339 spells resolve to
nothing"). A published number that drifts is worse than no number, so the counts
are recomputed from the shipped corpus here and compared against what the page
claims. Change the behaviour, and this test tells you which sentence to update.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.conjuration import CONJURATION_ALLOWLIST

CAPABILITIES_MD = Path(__file__).resolve().parents[3] / "docs" / "capabilities.md"

#: Activity kinds the resolver actually turns into ``CombatEvent``s. A
#: ``utility`` activity counts only when it carries effect riders — mirrors
#: ``dnd5e_engine.activities.resolver.resolve_activity``; an allowlisted
#: conjuration (``_CONJURED_SPELLS``) resolves too.
MECHANICAL_KINDS = frozenset({"attack", "damage", "save", "heal", "check", "cast"})


def _resolves(activity: dict[str, Any]) -> bool:
    kind = activity.get("kind")
    if kind in MECHANICAL_KINDS:
        return True
    return kind == "utility" and bool(activity.get("effects"))


#: Spells whose ``summon`` / ``enchant`` activity the engine resolves (C21):
#: the conjuration allowlist's construct, enchant and summon entries — never
#: any kind wholesale. Polymorph's form rides its ``save`` activity, which
#: already counts, and Wild Shape is a feature.
_CONJURED_SPELLS = frozenset(
    slug
    for slug, kind in CONJURATION_ALLOWLIST.items()
    if kind in {"construct", "enchant", "summon"}
)


def _spell_resolves(spell: dict[str, Any]) -> bool:
    return spell.get("slug") in _CONJURED_SPELLS or any(
        _resolves(a) for a in spell.get("activities", [])
    )


@pytest.fixture(scope="module")
def canonical_dir() -> Path:
    import dnd5e_srd_data

    return Path(dnd5e_srd_data.__file__).parent / "canonical"


@pytest.fixture(scope="module")
def spell_stats(canonical_dir: Path) -> dict[str, int]:
    total = inert = inert_concentration = 0
    for path in sorted((canonical_dir / "spells").glob("*.json")):
        spell = json.loads(path.read_text())
        total += 1
        if not _spell_resolves(spell):
            inert += 1
            if spell.get("concentration"):
                inert_concentration += 1
    return {
        "total": total,
        "inert": inert,
        "resolving": total - inert,
        "inert_concentration": inert_concentration,
    }


@pytest.fixture(scope="module")
def matrix_text() -> str:
    assert CAPABILITIES_MD.is_file(), f"missing {CAPABILITIES_MD}"
    return CAPABILITIES_MD.read_text()


def test_published_spell_counts_match_the_corpus(
    spell_stats: dict[str, int], matrix_text: str
) -> None:
    for label, key in (
        ("Spells in the corpus", "total"),
        ("Resolve to at least one mechanical activity", "resolving"),
        ("Load but resolve to nothing", "inert"),
    ):
        match = re.search(rf"{re.escape(label)}.*?\*\*(\d+)\*\*", matrix_text)
        assert match, f"capabilities.md no longer publishes a count for {label!r}"
        assert int(match.group(1)) == spell_stats[key], (
            f"capabilities.md says {match.group(1)} for {label!r}, corpus says {spell_stats[key]}"
        )

    conc = re.search(r"of which are concentration spells.*?\*\*(\d+)\*\*", matrix_text)
    assert conc, "capabilities.md no longer publishes the inert-concentration count"
    assert int(conc.group(1)) == spell_stats["inert_concentration"]


def test_named_inert_concentration_spells_really_are_inert(canonical_dir: Path) -> None:
    """The page names specific staples as inert; verify each actually is."""
    for slug in (
        "blur",
        "darkness",
        "fog-cloud",
        "wall-of-force",
        "silent-image",
        "globe-of-invulnerability",
        "expeditious-retreat",
    ):
        spell = json.loads((canonical_dir / "spells" / f"{slug}.json").read_text())
        assert spell.get("concentration"), f"{slug} is no longer a concentration spell"
        assert not _spell_resolves(spell), (
            f"{slug} now resolves — remove it from the inert list in capabilities.md"
        )


def test_published_legendary_action_count_matches_the_corpus(
    canonical_dir: Path, matrix_text: str
) -> None:
    with_legendary = sum(
        1
        for path in (canonical_dir / "monsters").glob("*.json")
        if json.loads(path.read_text()).get("legendary_actions")
    )
    match = re.search(r"(\d+) monsters carry them in the data", matrix_text)
    assert match, "capabilities.md no longer publishes the legendary-action count"
    assert int(match.group(1)) == with_legendary


def test_legendary_actions_and_traits_are_consumed() -> None:
    """If these regress to unconsumed again, this test fails and the page must
    be updated (mirrors the intent of the probe this replaces: pin the gap by
    design so an implementation forces a docs update, just in the other
    direction now that C18 has consumed them)."""
    import dnd5e_engine.activities.monster_actions as monster_actions_module
    import dnd5e_engine.orchestrator as orchestrator_module

    orchestrator_source = Path(orchestrator_module.__file__).read_text()
    assert "legendary_actions_remaining" in orchestrator_source, (
        "legendary actions are no longer tracked by the engine — "
        "update docs/capabilities.md and BACKLOG.md, then update this test"
    )
    monster_actions_source = Path(monster_actions_module.__file__).read_text()
    assert "rank_monster_actions" in monster_actions_source, (
        "recharge/limited-use ranking is no longer in monster_actions.py — "
        "update docs/capabilities.md and BACKLOG.md, then update this test"
    )


# ── status-row probes ────────────────────────────────────────────────────────
#
# The counts above are pinned; the ✅/⚠️/❌ status rows were not, and drifted
# (see BACKLOG.md "Documentation drift"). Each probe below is a cheap,
# grep-level fact about the shipped source that the corresponding row claims.
# The test asserts the row and the probe agree in BOTH directions: a row that
# claims a capability the code lost fails, and so does a row still claiming a
# gap the code has since closed.


def _src(rel: str) -> str:
    """Source text of an engine module, by path relative to the package root."""
    import dnd5e_engine

    return (Path(dnd5e_engine.__file__).parent / rel).read_text()


def _event_class_body(name: str) -> str:
    """The body of one ``events.py`` event class, up to the next ``class``."""
    source = _src("events.py")
    head = source.split(f"\nclass {name}(", 1)
    assert len(head) == 2, f"events.py no longer defines {name}"
    return head[1].split("\nclass ", 1)[0]


def _canonical_spell(slug: str) -> dict[str, Any]:
    """One shipped spell's canonical JSON."""
    import dnd5e_srd_data

    path = Path(dnd5e_srd_data.__file__).parent / "canonical" / "spells" / f"{slug}.json"
    return dict(json.loads(path.read_text()))


#: row substring → (probe over the shipped source, substring the row must carry
#: iff the probe is True).
_PROBES: dict[str, tuple[Any, str]] = {
    # F1c/F1d: every save path adds a real ability + proficiency modifier.
    "Saving throws, half-on-save": (
        lambda: "save_modifier(" in _src("orchestrator.py"),
        "✅",
    ),
    # F2b: activity attacks build typed AdvantageSources instead of the old
    # hard-coded ``mode: AdvantageMode = "normal"`` parameter.
    "Attack rolls, crits": (
        lambda: 'mode: AdvantageMode = "normal"' not in _src("activities/attack.py"),
        "Advantage/disadvantage is rolled on",
    ),
    # C14 Task 3: Dodge sets a live ``dodging`` flag consumed by the attack
    # and save resolvers; the intent branch owns this exact literal.
    "Dodge": (
        lambda: 'if intent.intent_type == "dodge":' in _src("orchestrator.py"),
        "✅",
    ),
    # C16b: Dodge's "if you can see the attacker" conjunct is applied at every
    # attack context build site (``_combatant_can_see(live, t, current)``);
    # since C24 an opportunity attack resolves through those sites too.
    'if you can see the attacker" is now enforced (C16b': (
        lambda: "_combatant_can_see(live, t, current)" in _src("orchestrator.py"),
        'if you can see the attacker" is now enforced (C16b',
    ),
    # C14 Task 4: Help (assist-an-attack-roll flavor) has a live handler —
    # the intent branch owns this exact literal.
    "| Help |": (
        lambda: 'if intent.intent_type == "help":' in _src("orchestrator.py"),
        "✅",
    ),
    # Closed (C14 Task 5): Hide has a dispatch handler.
    "| Hide |": (
        lambda: 'if intent.intent_type == "hide"' in _src("orchestrator.py"),
        "✅",
    ),
    # C16b (plan ruling R1): Hide's "out of any enemy's line of sight"
    # conjunct scans hostiles via the composite predicate, skipped only when
    # the hider's own cell already carries Three-Quarters/Total cover.
    "out of every living, non-Incapacitated hostile's line of sight (C16b": (
        lambda: "_combatant_can_see(live, hostile, current)" in _src("orchestrator.py"),
        "out of every living, non-Incapacitated hostile's line of sight (C16b",
    ),
    # C27: Poisoned / Frightened reach the two checks the engine rolls outside
    # an activity — Hide's Stealth and escaping a grapple.
    "rolls the check at Disadvantage (C27)": (
        lambda: _src("orchestrator.py").count("_condition_check_sources(live, current)") == 2,
        "rolls the check at Disadvantage (C27)",
    ),
    # C16b (Hide Task 4): a dark cell satisfies "Heavily Obscured" via the
    # new ``SpatialTopology.light_on_cell`` seam.
    "`GridTopology.light_on_cell`": (
        lambda: "def light_on_cell(" in _src("spatial.py"),
        "`GridTopology.light_on_cell`",
    ),
    # F2c/C13: the damage-triggered concentration save emits the dedicated
    # event; row text no longer quotes the event name, so this probe now
    # pins the row's status instead.
    "Concentration, incl. damage-triggered saves": (
        lambda: "ConcentrationCheck(" in _src("orchestrator.py"),
        "✅",
    ),
    # C12 landed the enforced rows (the Incapacitated action gate is the
    # cheapest witness). One SRD row still unenforced is the engine-rolled
    # Initiative's: it reads Surprise and a seeded Incapacitated status only,
    # never a Poisoned, Frightened or Invisible one — the line this probe
    # watches. While both hold, the row is ⚠️ Partial; giving Initiative its
    # condition rows changes that line, flips the probe and forces the row to
    # be revisited.
    "Conditions (the 15 SRD conditions)": (
        lambda: (
            '"actor_incapacitated"' in _src("orchestrator.py")
            and "disadvantage = spec.is_surprised or spec.entity_id in seeded_incapacitated"
            in _src("orchestrator.py")
        ),
        "⚠️ Partial",
    ),
    # C16b: Frightened's attack-roll line-of-sight gate and the "can't
    # willingly move closer" movement rule are now enforced (the residual
    # unenforced half is the ability-check gate the probe above still pins).
    "now gated on line of sight to a known, living, tracked fear source (C16b": (
        lambda: (
            "_fear_source_in_sight(" in _src("orchestrator.py")
            and '"frightened",' in _event_class_body("MoveFailed")
        ),
        "now gated on line of sight to a known, living, tracked fear source (C16b",
    ),
    # C27: SRD 5.2 Petrified resists Poison damage and grants Immunity to
    # the Poisoned condition.
    "Petrified's Resistance to all damage, Poison included (C27)": (
        lambda: (
            'out["immunities"].append("poison")' not in _src("rules/conditions.py")
            and "CONDITION_GRANTED_IMMUNITIES" in _src("rules/conditions.py")
        ),
        "Petrified's Resistance to all damage, Poison included (C27)",
    ),
    # C12: the SRD 5.2 exhaustion penalty is a real projection, not prose.
    "| Exhaustion |": (
        lambda: "def d20_test_penalty(" in _src("rules/conditions.py"),
        "✅",
    ),
    # C12: massive damage kills outright rather than only decorating the event.
    "Instant death (massive damage)": (
        lambda: '"instant_kill"' in _src("orchestrator.py"),
        "✅",
    ),
    # F2c: the d20 breakdown is carried on the roll events.
    "carry the roll breakdown": (
        lambda: "natural:" in _event_class_body("AttackRolled"),
        "`natural`",
    ),
    # C16: the PC move handler paths through shortest_path and reports unreachable.
    "Multi-cell movement in one intent": (
        lambda: (
            '"unreachable"' in _src("orchestrator.py")
            and "shortest_path(" in _src("orchestrator.py")
        ),
        "✅",
    ),
    # C16: areas enumerate template cells; C26a: for every intent kind, with
    # "of your choice" exclusions and a reported AreaTargeted; C26b: monsters
    # aim their own.
    "AoE templates (sphere / cone / line / cube / cylinder)": (
        lambda: (
            "cells_in_template(" in _src("areas.py")
            and "AreaTargeted(" in _src("orchestrator.py")
            and "excluded_target_ids" in _src("orchestrator.py")
            and "best_aim(" in _src("orchestrator.py")
        ),
        "✅",
    ),
    # C16: the forced-movement primitive emits CombatantMoved.
    "Forced movement (push)": (
        lambda: "CombatantMoved(" in _src("orchestrator.py"),
        "✅",
    ),
    # C16b: the visibility predicate feeds the attack resolver.
    "Vision and light (darkness": (
        lambda: (
            "can_see(" in _src("orchestrator.py") and '"unseen"' in _src("activities/attack.py")
        ),
        "⚠️ Partial",
    ),
    # C16b (plan ruling R4): the composite predicate folding Blinded/
    # Invisible/blindsight/truesight on top of the scene vision model.
    "composite `_combatant_can_see` predicate": (
        lambda: "def _combatant_can_see(" in _src("orchestrator.py"),
        "composite `_combatant_can_see` predicate",
    ),
    # C27: a templated foe takes its stat block's senses.
    "a templated monster sees with its stat block's senses": (
        lambda: (
            "senses = _monster_senses(monster)" in _src("orchestrator.py")
            and "senses: CombatantSenses | None = None" in _src("specs.py")
        ),
        "a templated monster sees with its stat block's senses",
    ),
    # C22: Magic Resistance is read from the hydrated trait list.
    "`special_abilities`": (
        lambda: (
            "trait_mechanics" in _src("orchestrator.py")
            and "MAGIC_RESISTANCE" in _src("activities/save_primitive.py")
        ),
        "Magic Resistance",
    ),
    # C22: magical damage bypasses nonmagical-only B/P/S resistance.
    "resistances/immunities/vulnerabilities": (
        lambda: "physical_resistances_nonmagical_only" in _src("activities/apply.py"),
        "overcome resistance",
    ),
    # C22: Sacred Flame's save carve-out is honoured.
    "Cover (half / three-quarters / total)": (
        lambda: "ignore_cover" in _src("activities/save_primitive.py"),
        "ignore_cover",
    ),
    # C13: the voluntary drop intent and its orchestrator call site are the
    # cheapest witnesses that the concentration lifecycle (one-at-a-time,
    # death/Incapacitated drop, timed expiry) is wired up end to end.
    "and cascade drop": (
        lambda: (
            '"drop_concentration",' in _src("events.py")
            and "_drop_concentration(live, event.target_id)" in _src("orchestrator.py")
        ),
        "✅",
    ),
    # C14 Task 1/2: Extra Attack's per-Action counter and the Light-property
    # off-hand Bonus Action window are both live.
    "Action economy": (
        lambda: (
            "_attacks_per_action(" in _src("orchestrator.py")
            and "_twf_window_open(" in _src("orchestrator.py")
        ),
        "modelled (C14)",
    ),
    # C14 Task 6/7: Grapple/Shove resolve via the shared Unarmed Strike save.
    "Grapple / Shove": (
        lambda: "_roll_unarmed_option_save(" in _src("orchestrator.py"),
        "⚠️ Partial",
    ),
    # C27: the shared immunity predicate gates Grapple and Shove's Prone.
    "but the condition never lands (C27)": (
        lambda: (
            'is_condition_immune(target, "grappled")' in _src("orchestrator.py")
            and '_emit_condition_applied(live, target, "prone")' in _src("orchestrator.py")
        ),
        "but the condition never lands (C27)",
    ),
    # C14 Task 2: the Light-property off-hand Bonus Action window.
    "Two-weapon fighting": (
        lambda: "_twf_window_open(" in _src("orchestrator.py"),
        "✅",
    ),
    # C14 Task 8: Surprise imposes Disadvantage on the engine-rolled Initiative.
    "| Surprise |": (
        lambda: "spec.is_surprised" in _src("orchestrator.py"),
        "✅",
    ),
    # C14 Task 8: initiative=None draws an engine d20 + DEX modifier roll.
    "Initiative order, rounds, turns": (
        lambda: "def _resolve_initiative(" in _src("orchestrator.py"),
        "✅",
    ),
    # C29: a CombatInstance passes initiative=None through build_party_member.
    "`CombatInstance.initiative` takes `None` too": (
        lambda: "initiative: int | None = 0" in _src("build_spec.py"),
        "`CombatInstance.initiative` takes `None` too",
    ),
    # C14 Task 8: a seeded incapacitated-implying status also imposes
    # Disadvantage on the engine-rolled Initiative roll.
    "Incapacitated's initiative disadvantage": (
        lambda: "seeded_incapacitated" in _src("orchestrator.py"),
        "closed via C14 Task 8",
    ),
    # C24: an opportunity attack resolves through the activity context,
    # flagged on its context.
    "| Opportunity attacks |": (
        lambda: "def _opportunity_attack_of(" in _src("orchestrator.py"),
        "✅",
    ),
    # C15 Tasks 2/3: the long-range disadvantage tier and the Ranged
    # Attacks in Close Combat gate both append their own AdvantageSource
    # (previously the row called both "still inert").
    "long-range disadvantage": (
        lambda: (
            '"range:long"' in _src("activities/attack.py")
            and '"ranged_in_melee"' in _src("activities/attack.py")
        ),
        "long-range disadvantage",
    ),
    # C15 Task 3: the Heavy-property Strength gate.
    "Heavy weapon (raw Strength": (
        lambda: "def _weapon_heavy_disadvantage(" in _src("activities/attack.py"),
        "Heavy weapon (raw Strength",
    ),
    # C15 Task 4: DamageApplied gains source_id / is_crit for weapon damage.
    "DamageApplied` now carries `source_id`": (
        lambda: (
            "source_id: str | None = None" in _event_class_body("DamageApplied")
            and "is_crit: bool = False" in _event_class_body("DamageApplied")
        ),
        "DamageApplied` now carries `source_id`",
    ),
    # C15 Task 7: Push weapon mastery wired into the same forced-movement
    # primitive as Thunderwave / Shove.
    "Push weapon mastery (C15": (
        lambda: 'elif mastery_slug == "push":' in _src("orchestrator.py"),
        "Push weapon mastery (C15",
    ),
    # C15 Task 6: Topple's prone rider is gated by the shared
    # is_condition_immune helper (previously an ungated emit site).
    "Weapon-mastery Topple honors condition immunity": (
        lambda: 'is_condition_immune(target, "prone")' in _src("activities/mastery.py"),
        "Weapon-mastery Topple honors condition immunity",
    ),
    # C17: Long Rest reduces Exhaustion by 1, floored at 0, via an additive
    # kwarg on ``resolve_long_rest``.
    "Long Rest reduces the level by 1": (
        lambda: "exhaustion_level" in _src("rest.py"),
        "Long Rest reduces the level by 1",
    ),
    # C17 Task 4 (R4): Counterspell's reaction-drain eligibility check is
    # threaded through ``_pop_pending_reaction``'s ``eligible=`` predicate —
    # an ineligible reactor's armed reaction is skipped, not popped.
    "slot-gated at the readied level and 60 ft range/LoS-gated at drain time": (
        lambda: "eligible=" in _src("orchestrator.py"),
        "slot-gated at the readied level and 60 ft range/LoS-gated at drain time",
    ),
    # C17 Task 4 (R4): a readied leveled spell (Shield) is gated on slot
    # availability at drain time via its own ``_readied_cast_eligible``
    # predicate (distinct from Counterspell's inline ``_eligible`` above).
    "an unexpended slot at its readied level": (
        lambda: "def _readied_cast_eligible(" in _src("orchestrator.py"),
        "an unexpended slot at its readied level",
    ),
    # C17 Task 1: per-class/multiclass/Pact slot tables are derived
    # engine-side rather than accepted as a host-precomputed flat dict.
    "derive_spell_slots`, `derive_multiclass_slots`, `derive_pact_slots": (
        lambda: "def derive_multiclass_slots(" in _src("build_spec.py"),
        "derive_spell_slots`, `derive_multiclass_slots`, `derive_pact_slots",
    ),
    # C17 Task 1: the multiclass carrier itself (``classes: dict[str, int]``)
    # is the field this row names — distinct from the derivation function
    # probed above.
    "`CharacterBuildSpec.classes` carrier": (
        lambda: "classes: dict[str, int]" in _src("build_spec.py"),
        "`CharacterBuildSpec.classes` carrier",
    ),
    # C17 Task 6 (R8): a Ritual-tagged spell resolves out-of-combat only,
    # through the pure ``resolve_ritual_cast`` host seam; an in-combat
    # ``as_ritual`` cast is rejected before any slot logic.
    "Out-of-combat via `resolve_ritual_cast`": (
        lambda: "def resolve_ritual_cast(" in _src("spellcasting.py"),
        "Out-of-combat via `resolve_ritual_cast`",
    ),
    # C17 Task 6: component/material metadata now rides on every PC-path
    # cast via the ``SpellCast`` event, but nothing gates on it.
    "Metadata on `SpellCast`, not enforced": (
        lambda: "class SpellCast(" in _src("events.py"),
        "Metadata on `SpellCast`, not enforced",
    ),
    # C15: all eight 2024 weapon masteries are live. F6 — this used to be a
    # bare substring grep for each mastery slug over mastery.py, which
    # passed on COMMENT text alone: cleave and nick are documented there
    # ("resolved elsewhere entirely") but never dispatched from that file,
    # so the probe couldn't fail even if either mastery regressed. Probe
    # each mastery's actual dispatch/resolution site instead: graze/topple
    # resolve in mastery.py itself; vex/sap/slow/push report through the
    # ``ctx.mastery_procs`` writeback (their proc-append call sites);
    # cleave's chained attack lives in attack.py; Nick is pure action
    # economy, gated in orchestrator.py's off-hand consume helper.
    "All eight (C15)": (
        lambda: (
            "_resolve_graze(" in _src("activities/mastery.py")
            and "_resolve_topple(" in _src("activities/mastery.py")
            and "ctx.mastery_procs.append((_VEX" in _src("activities/mastery.py")
            and "ctx.mastery_procs.append((_SAP" in _src("activities/mastery.py")
            and "ctx.mastery_procs.append((_SLOW" in _src("activities/mastery.py")
            and "ctx.mastery_procs.append((_PUSH" in _src("activities/mastery.py")
            and "_resolve_cleave_chain(" in _src("activities/attack.py")
            and 'weapon.mastery == "nick"' in _src("orchestrator.py")
        ),
        "All eight (C15)",
    ),
    # C19: engine-side character derivation.
    "HP, AC, hit dice, skill/save proficiencies": (
        lambda: "def derive_sheet(" in _src("build_spec.py"),
        "✅ Resolved",
    ),
    "| Background |": (
        lambda: "background_slug: str | None" in _src("build_spec.py"),
        "⚠️ Partial",
    ),
    # C28: the background's Origin feat reaches the sheet.
    "its Origin feat joins `DerivedSheet.feats` (C28)": (
        lambda: "def _background_feats(" in _src("build_spec.py"),
        "its Origin feat joins `DerivedSheet.feats` (C28)",
    ),
    "Class, subclass, level 1–20, species": (
        lambda: "def subclass_gate_level(" in _src("rules/character.py"),
        "✅ Resolved",
    ),
    "`CheckSpec.jack_of_all_trades` / `reliable_talent`": (
        lambda: "reliable_talent: bool = False" in _src("check.py"),
        "(C19)",
    ),
    # C20: Rage's extension check is a registered ``turn_end`` hook.
    "Rage's end-of-turn extension check (C20)": (
        lambda: "engine:rage-extension" in _src("orchestrator.py"),
        "Rage's end-of-turn extension check (C20)",
    ),
    # C20: Action Surge's extra action is counted on the live turn view.
    "Action Surge's extra action (C20": (
        lambda: "extra_actions_remaining" in _src("views.py"),
        "Action Surge's extra action (C20",
    ),
    # C20: the Bonus-Action Dash/Disengage read the Cunning Action feature,
    # not the class slug.
    "| Dash, Disengage |": (
        lambda: (
            "_CUNNING_ACTION not in _granted_feature_slugs(current)" in _src("orchestrator.py")
            and 'class_slug != "rogue"' not in _src("orchestrator.py")
        ),
        "Cunning Action",
    ),
    # C20: every corpus ``uses.max`` shape evaluates, and ``@scaling``
    # resolves for an amount-scaled feature activity (Lay on Hands' Heal).
    "Class/species feature activities": (
        lambda: (
            "def evaluate_uses_formula(" in _src("rules/uses.py")
            and "scaling_value" in _src("activities/formula.py")
        ),
        "(C20)",
    ),
    # C20: the four SRD 5.2 Fighting Style feats, each at its own seam.
    "| Fighting Style feats |": (
        lambda: (
            "def defense_ac_bonus(" in _src("rules/character.py")
            and "_fighting_style_attack_bonus(" in _src("activities/attack.py")
            and "_great_weapon_fighting_floor(" in _src("activities/attack.py")
            and '"two-weapon-fighting"' in _src("orchestrator.py")
        ),
        "✅ Resolved",
    ),
    # C20: Martial Arts and the Flurry of Blows strikes.
    "| Martial Arts and Monk's Focus |": (
        lambda: (
            "def _martial_arts_active(" in _src("orchestrator.py")
            and "flurry_strikes_remaining" in _src("types/combat.py")
        ),
        "(C20)",
    ),
    # C20: Rage ends unless extended (and on Incapacitated).
    "| Rage |": (
        lambda: (
            '"not_extended"' in _src("events.py")
            and "engine:rage-extension" in _src("orchestrator.py")
        ),
        "(C20)",
    ),
    # C20: a Bardic Inspiration die is redeemed on a failed attack roll.
    "| Bardic Inspiration |": (
        lambda: (
            '"no_granted_die"' in _event_class_body("AttackFailed")
            and "granted_die" in _src("activities/context.py")
        ),
        "(C20)",
    ),
    # C20: per-class levels reach live combat through one owner walk.
    "live combat reads `PartyMemberSpec.classes` (C20)": (
        lambda: "def feature_owners(" in _src("activities/scale.py"),
        "live combat reads `PartyMemberSpec.classes` (C20)",
    ),
    # C20: the Fighting Style feats apply.
    "| Feats |": (
        lambda: "def styles_from_feats(" in _src("rules/character.py"),
        "Fighting Style feats apply (C20",
    ),
    # C28: repeats and the Epic Boon floor on the sheet; Alert, Savage
    # Attacker, Grappler and Magic Initiate in combat.
    "takes a feat once unless it is repeatable": (
        lambda: (
            "def _check_repeats(" in _src("build_spec.py")
            and "_EPIC_BOON_LEVEL" in _src("build_spec.py")
        ),
        "takes a feat once unless it is repeatable",
    ),
    "Alert adds the Proficiency Bonus to an engine-rolled Initiative": (
        lambda: "def _initiative_bonus(" in _src("orchestrator.py"),
        "Alert adds the Proficiency Bonus to an engine-rolled Initiative",
    ),
    "Savage Attacker rolls a weapon's damage dice twice": (
        lambda: (
            "def _savage_attacker_applies(" in _src("activities/attack.py")
            and "def _record_savage_attacker_spent(" in _src("orchestrator.py")
        ),
        "Savage Attacker rolls a weapon's damage dice twice",
    ),
    "a Grappler has Advantage on attack rolls against a creature it grapples": (
        lambda: "def _grappled_by_map(" in _src("orchestrator.py"),
        "a Grappler has Advantage on attack rolls against a creature it grapples",
    ),
    "gives its level 1 spell one cast per Long Rest without a slot": (
        lambda: "def _pay_for_cast(" in _src("orchestrator.py"),
        "gives its level 1 spell one cast per Long Rest without a slot",
    ),
    "unless `PartyMemberSpec.spell_abilities` names one for the spell (C28)": (
        lambda: "def _spellcasting_ability_for(" in _src("orchestrator.py"),
        "unless `PartyMemberSpec.spell_abilities` names one for the spell (C28)",
    ),
    "`recover_slotless_casts` restores": (
        lambda: "def recover_slotless_casts(" in _src("rest.py"),
        "`recover_slotless_casts` restores",
    ),
    # C21: every concentration spell concentrates — a caster-held anchor for
    # one that applies no concentration effect of its own.
    "concentration spell concentrates (C21)": (
        lambda: "def _apply_concentration_anchor(" in _src("orchestrator.py"),
        "concentration spell concentrates (C21)",
    ),
    "| Concentration |": (
        lambda: "def _apply_concentration_anchor(" in _src("orchestrator.py"),
        "(C13, C21",
    ),
    # C21: the conjuration allowlist resolves five SRD 5.2 sources, Summon
    # Dragon's creature through the summon registry; every other summon,
    # transform and enchant stays narrative, so the row is Partial.
    "Summoning / polymorph / enchant-a-weapon": (
        lambda: (
            "CONJURATION_ALLOWLIST" in _src("activities/conjuration.py")
            and "SUMMONS" in _src("activities/conjuration.py")
        ),
        "⚠️ Partial",
    ),
    # C21: Wild Shape's form gate reads the Beast Shapes table.
    "| Wild Shape |": (
        lambda: (
            "def _wild_shape_failure(" in _src("orchestrator.py")
            and "WILD_SHAPE_TIERS" in _src("activities/conjuration.py")
        ),
        "(C21)",
    ),
    # C21: one swing of an attack action on the actor's current stat block.
    "| Stat-block attack commands |": (
        lambda: "def _stat_block_attack_failure(" in _src("orchestrator.py"),
        "(C21)",
    ),
    # C23: every status row carries a probe (``test_every_status_row_has_a_probe``).
    # Each fact below is the cheapest witness of the row's claim; a ❌ row's
    # probe is True while the mechanic is still absent.
    "Effect durations (`rounds`, `turns`, `seconds`": (
        lambda: (
            'key="engine:timed-effect-expiry"' in _src("orchestrator.py")
            and "until_end_of_next_turn_of" in _src("orchestrator.py")
        ),
        "✅",
    ),
    "Death saves, stabilization": (
        lambda: (
            "def roll_death_save(" in _src("death_saves.py")
            and "Stabilized(" in _src("death_saves.py")
        ),
        "✅",
    ),
    "Temporary HP, healing": (
        lambda: (
            "TempHpApplied(" in _src("activities/heal.py")
            and "HealingApplied(" in _src("activities/heal.py")
        ),
        "✅",
    ),
    "| Cover, line of sight |": (
        lambda: (
            "def cover_on_cell(" in _src("spatial.py")
            and "def has_line_of_sight(" in _src("spatial.py")
        ),
        "✅",
    ),
    # Flanking is an optional variant, not an SRD 5.2 rule: nothing names it.
    "| Flanking |": (
        lambda: "flank" not in _src("orchestrator.py").lower(),
        "❌",
    ),
    "2-D grid, Chebyshev distance": (
        lambda: "def _chebyshev(" in _src("spatial.py"),
        "✅",
    ),
    "Blocked cells, difficult terrain": (
        lambda: "difficult_terrain_cells" in _src("spatial.py"),
        "✅",
    ),
    "| Walls / line of sight |": (
        lambda: "def has_line_of_sight(" in _src("spatial.py"),
        "✅",
    ),
    "Elevation / flying altitude": (
        lambda: not re.search("elevation|altitude", _src("spatial.py"), re.IGNORECASE),
        "❌",
    ),
    # A footprint needs a creature size, which the combatant model lacks.
    "Multi-tile (Large+) creature footprints": (
        lambda: not re.search(r"^    size\b", _src("types/combat.py"), re.MULTILINE),
        "❌",
    ),
    # Every move's route is a fewest-squares BFS (``shortest_path``); only
    # the flee planner's reachability search prices routes by cost.
    "Threat-aware or cost-aware pathfinding": (
        lambda: "deque([a])" in _src("spatial.py"),
        "❌",
    ),
    "Spell attack rolls & save DCs": (
        lambda: "def _resolve_dc(" in _src("activities/save.py"),
        "✅",
    ),
    # Partial because the interactions are named special cases, not data.
    "Counterspell, Shield, Hellish Rebuke, Magic Missile interactions": (
        lambda: "def _apply_magic_missile_shield_carveout(" in _src("orchestrator.py"),
        "⚠️ Partial",
    ),
    "| Dispel Magic |": (
        lambda: not _spell_resolves(_canonical_spell("dispel-magic")),
        "❌",
    ),
    # C26b: the AI aims an area, and an unaimable one is no option.
    "Typed action selection + built-in AI": (
        lambda: (
            "def rank_monster_actions(" in _src("activities/monster_actions.py")
            and "def best_aim(" in _src("areas.py")
            and "_monster_area_unaimable(" in _src("orchestrator.py")
        ),
        "✅",
    ),
    # C26b: a fallback repeats only an attack its clause names.
    "| Multiattack fan-out |": (
        lambda: (
            "_ANY_COMBINATION_RE" in _src("activities/monster_actions.py")
            and "def _clause_siblings(" in _src("activities/monster_actions.py")
        ),
        "⚠️ Partial",
    ),
    "| Monster spellcasting |": (
        lambda: "def _resolve_monster_cast(" in _src("orchestrator.py"),
        "✅",
    ),
    # C24: the grid flee planner ranks the cells ``reachable_cells`` finds.
    "Flee / retreat behaviour": (
        lambda: (
            "def _plan_flee_route(" in _src("orchestrator.py")
            and "def reachable_cells(" in _src("spatial.py")
            and "has_fled" in _src("types/combat.py")
        ),
        "✅",
    ),
    "**Legendary actions**": (
        lambda: "LegendaryActionUsed(" in _src("orchestrator.py"),
        "✅",
    ),
    "**Lair actions**": (
        lambda: "lair" not in _src("orchestrator.py").lower(),
        "❌",
    ),
    "Recharge (5–6) abilities": (
        lambda: "RechargeRolled(" in _src("orchestrator.py"),
        "✅",
    ),
    "| Regeneration |": (
        lambda: "MonsterTraitMechanic.REGENERATION" in _src("orchestrator.py"),
        "✅",
    ),
    "Dataset categories `conditions/` + `traits/`": (
        lambda: (
            hasattr(BundledAssetLoader, "get_condition")
            and hasattr(BundledAssetLoader, "get_trait")
        ),
        "✅",
    ),
    "Ability scores, proficiency, expertise": (
        lambda: "ability_score_method" in _src("build_spec.py"),
        "⚠️ Partial",
    ),
    "| Sneak Attack |": (
        lambda: "def sneak_attack_triggers(" in _src("activities/attack.py"),
        "✅",
    ),
    "Short/long rest, hit dice, feature & item recharge": (
        lambda: (
            "def resolve_long_rest(" in _src("rest.py")
            and "def recover_item_uses(" in _src("rest.py")
        ),
        "✅",
    ),
    # C24: one step trigger serves every walk, whoever drives the mover.
    "| Opportunity attack |": (
        lambda: (
            "def _fire_opportunity_attacks_on_step(" in _src("orchestrator.py")
            and "def _opportunity_attackers(" in _src("orchestrator.py")
        ),
        "✅",
    ),
    # C26b: a monster's save action leaves a readied Shield readied.
    "Shield (incl. vs. Magic Missile)": (
        lambda: (
            "def _apply_magic_missile_shield_carveout(" in _src("orchestrator.py")
            and "if any(isinstance(a, AttackActivity) for a in activities):"
            in _src("orchestrator.py")
        ),
        "✅",
    ),
    # A readied reaction fires only on one of the engine's named triggers.
    "Ready an action with a custom trigger": (
        lambda: (
            'ReactionTrigger = Literal["cast_spell", "hit_by_attack", "targeted_by_magic_missile"]'
            in _src("orchestrator.py")
        ),
        "❌",
    ),
}


@pytest.mark.parametrize("row", sorted(_PROBES))
def test_status_rows_match_code_probes(row: str, matrix_text: str) -> None:
    probe, status_if_true = _PROBES[row]
    lines = [line for line in matrix_text.splitlines() if row in line]
    assert len(lines) == 1, f"capabilities.md has {len(lines)} lines containing {row!r}, want 1"
    assert (status_if_true in lines[0]) == probe(), (
        f"capabilities.md row {row!r} disagrees with the code: the page "
        f"{'claims' if status_if_true in lines[0] else 'does not claim'} "
        f"{status_if_true!r}, the source says {probe()}"
    )


_STATUS_MARKS = ("✅", "⚠️", "❌")


def _status_rows(text: str) -> list[str]:
    """Every table row whose status (second) cell opens with a status mark."""
    rows = []
    for line in text.splitlines():
        cells = line.strip().strip("|").split("|")
        if line.startswith("|") and len(cells) > 1 and cells[1].strip().startswith(_STATUS_MARKS):
            rows.append(line)
    return rows


def test_every_status_row_has_a_probe(matrix_text: str) -> None:
    """A status row with no probe can drift from the code unnoticed, as ten
    once did: every ✅/⚠️/❌ row must contain a ``_PROBES`` key."""
    rows = _status_rows(matrix_text)
    assert len(rows) > 70
    unprobed = [row[:70] for row in rows if not any(key in row for key in _PROBES)]
    assert unprobed == []
