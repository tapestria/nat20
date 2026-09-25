"""Carrier-gated routing of the allowlisted conjurations (C21).

An allowlisted ``summon`` / ``enchant`` / ``transform`` activity resolves only
when the orchestrator hands the context a pre-validated ``ConjurationCarrier``
that names its source and the input its kind needs. Everything else keeps the
narrative branch: no event, no request, one ``activity_kind_narrative`` log.
"""

from __future__ import annotations

import logging
import random
import typing
from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.common import Activity

from dnd5e_engine.activities.conjuration import (
    CONJURATION_ALLOWLIST,
    ENCHANTED_WEAPON_FLAG,
    ConjurationCarrier,
    ConstructRequest,
    TransformRequest,
    TransformSource,
)
from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.effects import passive_effect_to_active_effect
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import CombatEvent, EffectApplied
from dnd5e_engine.types.combat import Combatant

LOADER = BundledAssetLoader()


def _spell(slug: str) -> Any:
    spell = LOADER.get_spell(slug)
    assert spell is not None
    return spell


MAGIC_WEAPON = _spell("magic-weapon")
SPIRITUAL_WEAPON = _spell("spiritual-weapon")
WILD_SHAPE = LOADER.get_feature("wild-shape")
assert WILD_SHAPE is not None


def _combatant(entity_id: str) -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Character" if entity_id.startswith("char:") else "Monster",
        name=entity_id,
        initiative=10,
        hp_current=10,
        hp_max=10,
    )


def _ctx(
    *, targets: tuple[str, ...] = ("char:hero",), **fields: Any
) -> tuple[ActivityResolutionContext, list[CombatEvent]]:
    emitted: list[CombatEvent] = []
    ctx = ActivityResolutionContext(
        rng=random.Random(1),
        caster=_combatant("char:hero"),
        targets=[_combatant(t) for t in targets],
        event_emitter=emitted.append,
        caster_abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        **fields,
    )
    return ctx, emitted


def _only(activities: list[Activity]) -> Activity:
    [activity] = activities
    return activity


# ── Magic Weapon: the enchant ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("slot_level", "name", "bonus"),
    [(2, "Magic Weapon +1", "1"), (4, "Magic Weapon +2", "2"), (6, "Magic Weapon +3", "3")],
)
def test_magic_weapon_enchants_the_named_weapon_at_its_tier(
    slot_level: int, name: str, bonus: str
) -> None:
    """SRD 5.2: "that weapon becomes a magic weapon with a +1 bonus to attack
    rolls and damage rolls. ... The bonus increases to +2 with a level 3–5
    spell slot. The bonus increases to +3 with a level 6+ spell slot." The
    refs' own level gates pick the tier; one rider per target."""
    ctx, emitted = _ctx(
        slot_level=slot_level,
        base_spell_level=2,
        source_passive_effects=list(MAGIC_WEAPON.passive_effects),
        conjuration=ConjurationCarrier(source_slug="magic-weapon", weapon_slug="longsword"),
    )
    resolve_activity(_only(MAGIC_WEAPON.activities), ctx)
    [applied] = emitted
    assert isinstance(applied, EffectApplied)
    effect = applied.effect
    slug = name.lower().replace(" ", "_")
    assert (effect.id, effect.origin, effect.target_id) == (
        f"effect:{slug}",
        f"cast:{slug}:char:hero",
        "char:hero",
    )
    assert effect.flags == {ENCHANTED_WEAPON_FLAG: "longsword"}
    assert ("system.magicalBonus", "upgrade", bonus) in {
        (c.key, c.mode, c.value) for c in effect.changes
    }
    assert effect.duration.seconds == 3600
    assert (ctx.construct_requests, ctx.transform_requests) == ([], [])


# ── Spiritual Weapon: the construct ──────────────────────────────────────────


@pytest.mark.parametrize(("slot_level", "expected_level"), [(None, 2), (3, 3)])
def test_spiritual_weapon_requests_a_construct(slot_level: int | None, expected_level: int) -> None:
    ctx, emitted = _ctx(
        targets=("mon:foe",),
        slot_level=slot_level,
        base_spell_level=2,
        conjuration=ConjurationCarrier(source_slug="spiritual-weapon", cell="1,0"),
    )
    resolve_activity(_only(SPIRITUAL_WEAPON.activities), ctx)
    assert emitted == []
    assert ctx.construct_requests == [
        ConstructRequest(
            spell_id="spiritual-weapon",
            owner_id="char:hero",
            cell="1,0",
            slot_level=expected_level,
            target_ids=("mon:foe",),
        )
    ]
    assert ctx.transform_requests == []


# ── Wild Shape: the transform ────────────────────────────────────────────────


def test_wild_shape_requests_a_transform_of_its_user() -> None:
    ctx, emitted = _ctx(
        conjuration=ConjurationCarrier(source_slug="wild-shape", form_slug="giant-badger"),
    )
    resolve_activity(_only(WILD_SHAPE.activities), ctx)
    assert emitted == []
    assert ctx.transform_requests == [
        TransformRequest(target_id="char:hero", form_slug="giant-badger", source="wild-shape")
    ]
    assert ctx.construct_requests == []


# ── Everything else stays narrative ──────────────────────────────────────────

_MW_CARRIER = ConjurationCarrier(source_slug="magic-weapon", weapon_slug="longsword")
_SW_CARRIER = ConjurationCarrier(source_slug="spiritual-weapon", cell="1,0")
_WS_CARRIER = ConjurationCarrier(source_slug="wild-shape", form_slug="giant-badger")


@pytest.mark.parametrize(
    ("activity", "carrier"),
    [
        # No carrier: today's behaviour for every caller.
        (_only(MAGIC_WEAPON.activities), None),
        (_only(SPIRITUAL_WEAPON.activities), None),
        (_only(WILD_SHAPE.activities), None),
        # A carrier of another source.
        (_only(MAGIC_WEAPON.activities), _SW_CARRIER),
        (_only(SPIRITUAL_WEAPON.activities), _WS_CARRIER),
        (_only(WILD_SHAPE.activities), _MW_CARRIER),
        # The source's own carrier without the input its kind needs.
        (_only(MAGIC_WEAPON.activities), ConjurationCarrier(source_slug="magic-weapon")),
        (_only(SPIRITUAL_WEAPON.activities), ConjurationCarrier(source_slug="spiritual-weapon")),
        (_only(WILD_SHAPE.activities), ConjurationCarrier(source_slug="wild-shape")),
        # A source outside the allowlist.
        (
            _only(MAGIC_WEAPON.activities),
            ConjurationCarrier(source_slug="shillelagh", weapon_slug="club"),
        ),
    ],
)
def test_anything_the_carrier_does_not_cover_stays_narrative(
    activity: Activity, carrier: ConjurationCarrier | None, caplog: pytest.LogCaptureFixture
) -> None:
    ctx, emitted = _ctx(
        slot_level=2,
        base_spell_level=2,
        source_passive_effects=list(MAGIC_WEAPON.passive_effects),
        conjuration=carrier,
    )
    with caplog.at_level(logging.INFO, logger="dnd5e_engine.activities.resolver"):
        resolve_activity(activity, ctx)
    assert emitted == []
    assert (ctx.construct_requests, ctx.transform_requests) == ([], [])
    assert any("activity_kind_narrative" in r.getMessage() for r in caplog.records)


def test_a_monster_summon_rider_stays_narrative(caplog: pytest.LogCaptureFixture) -> None:
    """A monster's summon rider (the Shadow's Draining Swipe) never gets a
    carrier: the monster attack path builds none."""
    shadow = LOADER.get_monster("shadow")
    assert shadow is not None
    [swipe] = [a for a in shadow.actions if a.slug == "draining-swipe"]
    [summon] = [a for a in swipe.activities if a.kind == "summon"]
    ctx, emitted = _ctx()
    with caplog.at_level(logging.INFO, logger="dnd5e_engine.activities.resolver"):
        resolve_activity(summon, ctx)
    assert emitted == []
    assert ctx.construct_requests == []
    assert any("activity_kind_narrative" in r.getMessage() for r in caplog.records)


# ── The registry and the effect builder ──────────────────────────────────────


def test_every_transform_source_in_the_allowlist_is_a_transform_source() -> None:
    sources = {
        slug
        for slug, kind in CONJURATION_ALLOWLIST.items()
        if kind in ("transform", "transform_rider")
    }
    assert sources == set(typing.get_args(TransformSource)) == {"wild-shape", "polymorph"}


def test_the_allowlist_is_read_only() -> None:
    with pytest.raises(TypeError):
        CONJURATION_ALLOWLIST["summon-dragon"] = "construct"  # type: ignore[index]


@pytest.mark.parametrize(
    ("concentration", "extra_flags", "flags"),
    [
        (False, None, {}),
        (True, None, {"concentration": True}),
        (False, {ENCHANTED_WEAPON_FLAG: "longsword"}, {ENCHANTED_WEAPON_FLAG: "longsword"}),
        (
            True,
            {ENCHANTED_WEAPON_FLAG: "longsword"},
            {"concentration": True, ENCHANTED_WEAPON_FLAG: "longsword"},
        ),
    ],
)
def test_extra_flags_merge_after_concentration(
    concentration: bool, extra_flags: dict[str, str] | None, flags: dict[str, Any]
) -> None:
    """Absent ``extra_flags`` build exactly today's flags."""
    effect = passive_effect_to_active_effect(
        MAGIC_WEAPON.passive_effects[0],
        target_id="char:hero",
        caster_id="char:hero",
        concentration=concentration,
        extra_flags=extra_flags,
    )
    assert effect.flags == flags
