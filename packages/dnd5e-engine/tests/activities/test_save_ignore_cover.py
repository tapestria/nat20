"""C22 seam: ``SaveBlock.ignore_cover`` (Sacred Flame — "The target gains no
benefit from Half Cover or Three-Quarters Cover for this save"). The engine
reads it via getattr so it works before and after the dataset field lands."""

from __future__ import annotations

import random

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.save_primitive import roll_save
from dnd5e_engine.types.combat import Combatant


def _ctx(seed: int = 1, cover: str | None = "half") -> tuple[ActivityResolutionContext, Combatant]:
    caster = Combatant(
        entity_id="c", entity_type="Character", name="C", initiative=10, hp_current=10, hp_max=10
    )
    target = Combatant(
        entity_id="t", entity_type="Monster", name="T", initiative=1, hp_current=10, hp_max=10
    )
    ctx = ActivityResolutionContext(
        rng=random.Random(seed),
        caster=caster,
        targets=[target],
        event_emitter=lambda e: None,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        target_cover={"t": cover} if cover else {},
    )
    return ctx, target


def test_dex_save_adds_cover_bonus_by_default() -> None:
    ctx, target = _ctx()
    covered = roll_save(ctx, target, "dex", 10).total
    ctx2, target2 = _ctx(cover=None)
    assert covered == roll_save(ctx2, target2, "dex", 10).total + 2


def test_ignore_cover_skips_the_cover_bonus() -> None:
    ctx, target = _ctx()
    assert roll_save(ctx, target, "dex", 10, ignore_cover=True).modifier == 0
