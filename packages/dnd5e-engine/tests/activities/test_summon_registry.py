"""The roster-summon registry and its pure evaluators (C21).

SRD 5.2 Summon Dragon seats a Draconic Spirit whose numbers read the spell:
"AC 14 + the spell's level", "HP 50 + 10 for each spell level above 5", "PB
equals your Proficiency Bonus", Rend's "Bonus equals your spell attack
modifier" and "1d6 + 4 + the spell's level Piercing damage", and "a number of
Rend attacks equal to half the spell's level (round down)". The registry names
the stat block, a typed roll-data carrier feeds one evaluator that walks the
parsed formula (never ``eval``), and the resolver turns the allowlisted
``SummonActivity`` into a ``SummonRequest``.
"""

from __future__ import annotations

import logging
import random
import typing
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import SummonActivity, SummonBonusesBlock, SummonMatchBlock
from dnd5e_srd_data.schema.monster import Monster

from dnd5e_engine.activities.conjuration import (
    CONJURATION_ALLOWLIST,
    SUMMONS,
    ConjurationCarrier,
    ConjurationKind,
    StatBlockMagnitudes,
    SummonRequest,
    SummonRollData,
    evaluate_summon_formula,
    summon_attack_count,
    summon_magnitudes,
)
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import CombatEvent
from dnd5e_engine.types.combat import Combatant

LOADER = BundledAssetLoader()


def _monster(slug: str) -> Monster:
    monster = LOADER.get_monster(slug)
    assert monster is not None, slug
    return monster


def _summon_dragon_activity() -> SummonActivity:
    spell = LOADER.get_spell("summon-dragon")
    assert spell is not None
    [activity] = spell.activities
    assert isinstance(activity, SummonActivity)
    return activity


SPIRIT = _monster("draconic-spirit")
SUMMON = _summon_dragon_activity()
SPIRIT_SCORES = {"str": 19, "dex": 14, "con": 17, "int": 10, "wis": 14, "cha": 14}


# ── The registry ─────────────────────────────────────────────────────────────


def test_summon_dragon_is_the_one_allowlisted_summon() -> None:
    assert "summon" in typing.get_args(ConjurationKind)
    assert CONJURATION_ALLOWLIST["summon-dragon"] == "summon"
    assert {slug for slug, kind in CONJURATION_ALLOWLIST.items() if kind == "summon"} == set(
        SUMMONS
    )
    assert SUMMONS["summon-dragon"].stat_block_slug == "draconic-spirit"


@pytest.mark.parametrize("spell_id", sorted(SUMMONS))
def test_every_summon_spell_seats_a_loadable_stat_block(spell_id: str) -> None:
    spell = LOADER.get_spell(spell_id)
    assert spell is not None
    assert sum(isinstance(a, SummonActivity) for a in spell.activities) == 1
    monster = LOADER.get_monster(SUMMONS[spell_id].stat_block_slug)
    assert monster is not None
    assert monster.ac is not None


def test_summon_dragons_activity_carries_the_draconic_spirits_bonuses() -> None:
    """The numbers the seat reads come from the spell's own activity."""
    assert SUMMON.bonuses == SummonBonusesBlock(
        ac="@item.level", hp="10 * (@item.level - 5)", attack_damage="@item.level"
    )
    assert (SUMMON.match.attacks, SUMMON.match.proficiency) == (True, True)


# ── The formula evaluator ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("expr", "level", "mod", "value"),
    [
        ("", 5, 4, 0),
        ("  ", 9, 4, 0),
        ("@item.level", 5, 4, 5),
        ("@item.level", 8, 4, 8),
        ("10 * (@item.level - 5)", 5, 4, 0),
        ("10 * (@item.level - 5)", 6, 4, 10),
        ("10 * (@item.level - 5)", 7, 4, 20),
        ("10 * (@item.level - 5)", 8, 4, 30),
        ("10 * (@item.level - 5)", 9, 4, 40),
        ("floor(@flags.dnd5e.summon.level / 2)", 5, 4, 2),
        ("floor(@flags.dnd5e.summon.level / 2)", 6, 4, 3),
        ("floor(@flags.dnd5e.summon.level / 2)", 7, 4, 3),
        ("floor(@flags.dnd5e.summon.level / 2)", 8, 4, 4),
        ("floor(@flags.dnd5e.summon.level / 2)", 9, 4, 4),
        ("@flags.dnd5e.summon.mod", 5, 3, 3),
        ("@flags.dnd5e.summon.mod", 5, -1, -1),
        ("-(1 + 2) * 3", 5, 4, -9),
        ("@item.level / 2", 6, 4, 3),
    ],
)
def test_summon_formulas_evaluate_at_the_roll_data(
    expr: str, level: int, mod: int, value: int
) -> None:
    assert evaluate_summon_formula(expr, SummonRollData(level=level, mod=mod)) == value


@pytest.mark.parametrize(
    "expr",
    [
        "@prof",  # a token the summon roll data does not carry
        "@item.level / 2",  # 5 / 2: not a whole number
        "max(1, 2)",  # only floor() is a function
        "__import__('os')",
        "1d6",  # dice are not a summon formula
        "1 / (@item.level - 5)",  # a zero divisor at level 5
    ],
)
def test_anything_else_fails_loudly(expr: str) -> None:
    with pytest.raises(ValueError, match="summon"):
        evaluate_summon_formula(expr, SummonRollData(level=5, mod=4))


@pytest.mark.parametrize(("level", "count"), [(5, 2), (6, 3), (7, 3), (8, 4), (9, 4)])
def test_the_draconic_spirit_makes_half_the_spell_level_in_rends(level: int, count: int) -> None:
    assert summon_attack_count(SPIRIT, SummonRollData(level=level, mod=4)) == count


def test_a_multiattack_without_summon_roll_data_has_no_summon_count() -> None:
    assert summon_attack_count(_monster("hill-giant"), SummonRollData(level=9, mod=4)) is None


# ── The magnitudes ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("match", "proficiency_bonus", "attack_bonus"),
    [
        (SummonMatchBlock(attacks=True, proficiency=True), 4, 8),
        (SummonMatchBlock(attacks=True), 2, 8),
        (SummonMatchBlock(proficiency=True), 4, None),
        (SummonMatchBlock(), 2, None),
    ],
)
def test_summon_magnitudes_follow_the_match_flags(
    match: SummonMatchBlock, proficiency_bonus: int, attack_bonus: int | None
) -> None:
    """The spirit's own scores always; the summoner's PB only under
    ``match.proficiency`` (else the stat block's PB 2); the summoner's spell
    attack as a flat to-hit only under ``match.attacks``."""
    magnitudes = summon_magnitudes(
        SPIRIT, match, spell_attack_bonus=8, proficiency_bonus=4, attack_damage_bonus=5
    )
    assert magnitudes == StatBlockMagnitudes(
        ability_scores=SPIRIT_SCORES,
        proficiency_bonus=proficiency_bonus,
        attack_bonus=attack_bonus,
        attack_damage_bonus=5,
    )


def test_stat_block_magnitudes_default_to_a_transforms_numbers() -> None:
    magnitudes = StatBlockMagnitudes(ability_scores=SPIRIT_SCORES, proficiency_bonus=2)
    assert (magnitudes.attack_bonus, magnitudes.attack_damage_bonus) == (None, 0)


# ── The resolver ─────────────────────────────────────────────────────────────


def _ctx(**fields: Any) -> tuple[ActivityResolutionContext, list[CombatEvent]]:
    emitted: list[CombatEvent] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=Combatant(
            entity_id="char:summoner",
            entity_type="Character",
            name="Summoner",
            initiative=20,
            hp_current=40,
            hp_max=40,
        ),
        targets=[],
        event_emitter=emitted.append,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 18, "wis": 10, "cha": 10},
        **fields,
    )
    return ctx, emitted


@pytest.mark.parametrize(("slot_level", "cast_level"), [(None, 5), (7, 7)])
def test_summon_dragon_requests_a_summon(slot_level: int | None, cast_level: int) -> None:
    ctx, emitted = _ctx(
        slot_level=slot_level,
        base_spell_level=5,
        conjuration=ConjurationCarrier(source_slug="summon-dragon", cell="0,1"),
    )
    resolve_activity(SUMMON, ctx)
    assert emitted == []
    assert ctx.summon_requests == [
        SummonRequest(
            spell_id="summon-dragon",
            owner_id="char:summoner",
            cell="0,1",
            slot_level=cast_level,
            bonuses=SUMMON.bonuses,
            match=SUMMON.match,
        )
    ]
    assert (ctx.construct_requests, ctx.transform_requests) == ([], [])


@pytest.mark.parametrize(
    "carrier", [None, ConjurationCarrier(source_slug="summon-dragon")], ids=["none", "no-cell"]
)
def test_summon_dragon_without_a_space_stays_narrative(
    carrier: ConjurationCarrier | None, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, emitted = _ctx(slot_level=5, base_spell_level=5, conjuration=carrier)
    with caplog.at_level(logging.INFO, logger="dnd5e_engine.activities.resolver"):
        resolve_activity(SUMMON, ctx)
    assert emitted == []
    assert ctx.summon_requests == []
    assert any("activity_kind_narrative" in r.getMessage() for r in caplog.records)
