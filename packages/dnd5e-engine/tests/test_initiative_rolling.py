"""C14-T8 — engine-rolled initiative with surprise/incapacitated disadvantage.

SRD 5.2 Initiative: "every participant rolls Initiative; they make a
Dexterity check". SRD 5.2 Surprise: "that creature is surprised, which
causes it to have Disadvantage on its Initiative roll." SRD 5.2
Incapacitated glossary: "If you're Incapacitated when you roll Initiative,
you have Disadvantage on the roll."

``PartyMemberSpec.initiative`` / ``EncounterMemberSpec.initiative`` are
``int | None`` (C14): a fixed int seats the combatant with ZERO RNG draws
(the pre-C14 host-supplied path, byte-identical); ``None`` opts into an
engine-rolled d20 + DEX modifier, resolved in spec order (party, then
encounter) using the SAME ``random.Random(rng_seed)`` instance that then
seeds every subsequent in-combat draw (controller ruling R4).
"""

from __future__ import annotations

import asyncio
import random

from dnd5e_engine import (
    EncounterMemberSpec,
    GridScene,
    PartyMemberSpec,
    PlayerIntent,
    cell_id,
    start_combat,
    submit_player_intent,
)
from dnd5e_engine.orchestrator import _get_live, drain_pending_events
from dnd5e_engine.types.effects import ActiveEffect


def _run(
    *,
    seed: int,
    ambushed_surprised: bool = False,
    third_entity: bool = True,
    active_effects: tuple[ActiveEffect, ...] = (),
) -> dict[str, int]:
    party = [
        PartyMemberSpec(
            entity_id="char:aware",
            name="Aware",
            initiative=None,
            dexterity=16,
            hp_current=20,
            hp_max=20,
            zone_id=cell_id(0, 0),
        ),
        PartyMemberSpec(
            entity_id="char:ambushed",
            name="Ambushed",
            initiative=None,
            is_surprised=ambushed_surprised,
            dexterity=16,
            hp_current=20,
            hp_max=20,
            zone_id=cell_id(1, 0),
        ),
    ]
    encounter = [
        EncounterMemberSpec(
            entity_id="mon:foe",
            entity_type="Monster",
            name="Foe",
            initiative=None,
            dexterity=10,
            hp_current=20,
            hp_max=20,
            zone_id=cell_id(2, 0),
        )
    ]
    if third_entity:
        encounter.append(
            EncounterMemberSpec(
                entity_id="mon:foe2",
                entity_type="Monster",
                name="Foe2",
                initiative=None,
                dexterity=10,
                hp_current=20,
                hp_max=20,
                zone_id=cell_id(3, 0),
            )
        )

    async def _inner() -> dict[str, int]:
        start = await start_combat(
            session_id=f"initiative-rolling-{seed}",
            party=party,
            encounter=encounter,
            grid_scene=GridScene(width=10, height=10),
            rng_seed=seed,
            active_effects=active_effects,
        )
        live = _get_live(start.handle)
        return {c.entity_id: c.initiative for c in live.initiative}

    return asyncio.run(_inner())


def test_engine_rolled_initiative_is_bounded_and_reproducible() -> None:
    """(a) ``initiative=None`` seats a d20 + DEX-mod value; two runs at the
    same seed agree bit-for-bit; different seeds may (and here do) differ."""
    # DEX 16 -> +3 mod; bound is [1+3, 20+3].
    first = _run(seed=100)
    again = _run(seed=100)
    assert first == again
    for entity_id in ("char:aware", "char:ambushed"):
        assert 4 <= first[entity_id] <= 23

    other_seed = _run(seed=101)
    assert other_seed != first


def test_surprise_disadvantage_keeps_lower_of_two_draws() -> None:
    """(b) ``is_surprised=True`` re-rolled at the same seed seats <= the
    unsurprised value (Disadvantage keeps the lower draw) and consumes
    exactly two draws — proven by the THIRD entity (foe2) after it: its
    seat shifts between the two runs because the surprised combatant
    consumed an extra draw ahead of it (mirrors S07's shape)."""
    unsurprised = _run(seed=1)
    surprised = _run(seed=1, ambushed_surprised=True)

    assert surprised["char:ambushed"] <= unsurprised["char:ambushed"]
    # The Aware combatant draws first in both runs -> unaffected.
    assert surprised["char:aware"] == unsurprised["char:aware"]
    # foe2 draws AFTER ambushed in spec order; the extra disadvantage draw
    # consumed for "ambushed" shifts the RNG stream foe2 reads from.
    assert surprised["mon:foe2"] != unsurprised["mon:foe2"]


def test_all_int_initiative_consumes_zero_rng_draws() -> None:
    """(c) All-``int`` initiative specs draw NOTHING from the seeded RNG —
    the first in-combat roll (the hero's attack) matches the very first
    draw an independent ``random.Random(seed)`` would produce, proving no
    draws were consumed resolving initiative."""

    async def _inner() -> int:
        start = await start_combat(
            session_id="initiative-zero-draw",
            party=[
                PartyMemberSpec(
                    entity_id="char:hero",
                    name="Hero",
                    initiative=20,
                    hp_current=30,
                    hp_max=30,
                    ac=5,
                    zone_id=cell_id(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    hp_current=20,
                    hp_max=20,
                    zone_id=cell_id(1, 0),
                )
            ],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=7,
        )
        drain_pending_events(start.handle)
        await submit_player_intent(
            start.handle,
            actor_id="char:hero",
            intent=PlayerIntent(intent_type="attack", target_id="mon:foe", weapon_id="longsword"),
        )
        events = drain_pending_events(start.handle)
        (rolled,) = [e for e in events if type(e).__name__ == "AttackRolled"]
        return rolled.natural

    natural = asyncio.run(_inner())
    # Nothing consumes the RNG before the attack's own d20 draw when every
    # initiative is a fixed int -- so the FIRST draw off a fresh
    # random.Random(7) is exactly the attack roll's natural die.
    assert natural == random.Random(7).randint(1, 20)


def test_seeded_incapacitated_effect_imposes_initiative_disadvantage() -> None:
    """(d) An entity with a seeded incapacitated-implying status (e.g.
    Stunned, which implies Incapacitated per ``CONDITION_IMPLIES``) rolls
    Initiative at Disadvantage even without ``is_surprised``."""
    baseline = _run(seed=42, third_entity=False)
    stunned_effect = ActiveEffect(
        id="effect:stunned",
        name="Stunned",
        origin="cast:hold-person:1",
        target_id="char:ambushed",
        statuses={"stunned"},
    )
    with_stun = _run(seed=42, third_entity=False, active_effects=(stunned_effect,))

    assert with_stun["char:ambushed"] <= baseline["char:ambushed"]
    assert with_stun["char:aware"] == baseline["char:aware"]


def test_fixed_initiative_is_a_no_op_even_when_surprised() -> None:
    """(e) ``is_surprised=True`` alongside a fixed ``initiative=17`` is a
    no-op — the explicit value wins and no roll (and no disadvantage) is
    ever applied."""

    async def _inner() -> int:
        start = await start_combat(
            session_id="initiative-fixed-surprised",
            party=[
                PartyMemberSpec(
                    entity_id="char:ambushed",
                    name="Ambushed",
                    initiative=17,
                    is_surprised=True,
                    dexterity=16,
                    hp_current=20,
                    hp_max=20,
                    zone_id=cell_id(0, 0),
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id="mon:foe",
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    dexterity=10,
                    hp_current=20,
                    hp_max=20,
                    zone_id=cell_id(1, 0),
                )
            ],
            grid_scene=GridScene(width=10, height=10),
            rng_seed=5,
        )
        live = _get_live(start.handle)
        return next(c for c in live.initiative if c.entity_id == "char:ambushed").initiative

    assert asyncio.run(_inner()) == 17
