"""Keeps ``docs/capabilities.md`` honest.

The capability matrix publishes hard counts ("108 of 339 spells resolve to
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

CAPABILITIES_MD = Path(__file__).resolve().parents[3] / "docs" / "capabilities.md"

#: Activity kinds the resolver actually turns into ``CombatEvent``s. A
#: ``utility`` activity counts only when it carries effect riders — mirrors
#: ``dnd5e_engine.activities.resolver.resolve_activity``.
MECHANICAL_KINDS = frozenset({"attack", "damage", "save", "heal", "check", "cast"})


def _resolves(activity: dict[str, Any]) -> bool:
    kind = activity.get("kind")
    if kind in MECHANICAL_KINDS:
        return True
    return kind == "utility" and bool(activity.get("effects"))


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
        if not any(_resolves(a) for a in spell.get("activities", [])):
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
        "spiritual-weapon",
        "wall-of-force",
        "silent-image",
        "globe-of-invulnerability",
        "expeditious-retreat",
    ):
        spell = json.loads((canonical_dir / "spells" / f"{slug}.json").read_text())
        assert spell.get("concentration"), f"{slug} is no longer a concentration spell"
        assert not any(_resolves(a) for a in spell.get("activities", [])), (
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


def test_legendary_and_lair_actions_are_still_unconsumed() -> None:
    """If someone implements these, this test fails and the page must be updated."""
    import dnd5e_engine.activities.monster_actions as module

    source = Path(module.__file__).read_text()
    body = source.split('"""', 2)[-1]  # skip the module docstring
    for field in ("legendary_actions", "lair_actions", "special_abilities"):
        assert field not in body, (
            f"{field} is now read by the engine — update docs/capabilities.md "
            "and BACKLOG.md, then relax this test"
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
    # F2c/C13: the damage-triggered concentration save emits the dedicated
    # event; row text no longer quotes the event name, so this probe now
    # pins the row's status instead.
    "Concentration, incl. damage-triggered saves": (
        lambda: "ConcentrationCheck(" in _src("orchestrator.py"),
        "✅",
    ),
    # C12 landed the enforced rows (the Incapacitated action gate is the
    # cheapest witness), but three SRD rows are still unenforced (a fourth,
    # Incapacitated's concentration break, closed with C13) — the
    # Frightened line-of-sight gate is the one this probe watches, because
    # ``rules/conditions.py`` names it explicitly as not modelled. While both
    # halves hold, the row is ⚠️ Partial; implementing the gate (which means
    # deleting that sentence) flips the probe and forces the row up to ✅.
    "Conditions (the 15 SRD conditions)": (
        lambda: (
            '"actor_incapacitated"' in _src("orchestrator.py")
            and "line-of-sight gate is not modelled" in _src("rules/conditions.py")
        ),
        "⚠️ Partial",
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
    # C16: AoE spells enumerate template cells instead of zone equality.
    "AoE templates (sphere / cone / line / cube / cylinder)": (
        lambda: "cells_in_template(" in _src("orchestrator.py"),
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
    # D8: the zone graph is deprecated (warning raised in _resolve_topology).
    "Zone-graph topology": (
        lambda: "DeprecationWarning" in _src("orchestrator.py"),
        "Deprecated",
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
    # C14 Task 8: a seeded incapacitated-implying status also imposes
    # Disadvantage on the engine-rolled Initiative roll.
    "Incapacitated's initiative disadvantage": (
        lambda: "seeded_incapacitated" in _src("orchestrator.py"),
        "closed via C14 Task 8",
    ),
    # C14 Task 9: opportunity attacks roll through the same d20-test
    # primitive as every other attack, picking up condition/Exhaustion
    # sources — still no visibility gate (BACKLOG.md).
    "| Opportunity attacks |": (
        lambda: "roll_d20_test" in _src("orchestrator.py"),
        "✅",
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
