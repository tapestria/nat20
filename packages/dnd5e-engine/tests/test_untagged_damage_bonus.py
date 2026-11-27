"""An untagged ``damage.bonus`` active effect adds to the damage of every
attack roll its bearer hits with, weapon and spell alike.

The untagged sibling of the to-hit ``attack.roll.bonus`` (which already buffs
weapon and spell attacks): an effect without an ``applicable_action_types``
restriction applies to any attack. A weapon-tagged (``["attack"]``) bonus
stays on weapon swings only (SRD 5.2 §Magic Items — a magic weapon's bonus
applies to attack and damage rolls made with that weapon).
"""

from __future__ import annotations

from typing import Any

from dnd5e_engine import PlayerIntent
from dnd5e_engine.events import AttackRolled, DamageApplied
from dnd5e_engine.orchestrator import _get_live, start_combat, submit_player_intent
from dnd5e_engine.specs import EncounterMemberSpec, PartyMemberSpec
from dnd5e_engine.types.effects import ActiveEffect, ActiveEffectChange
from tests.e2e.harness import adjacent_cells, events_of, grid_scene, run_async

_HERO = "char:hero"
_FOE = "mon:foe"
_HERO_CELL, _FOE_CELL = adjacent_cells(2)


def _damage_bonus(value: int, *, tags: list[str] | None = None) -> ActiveEffect:
    suffix = "-".join(tags) if tags else "untagged"
    return ActiveEffect(
        id=f"effect:damage-bonus-{suffix}",
        name="Damage Bonus",
        origin=f"item:charm-{suffix}",
        target_id=_HERO,
        changes=[ActiveEffectChange(key="damage.bonus", mode="add", value=value)],
        flags={"applicable_action_types": tags} if tags else {},
    )


def _damage_dealt(session: str, intent: PlayerIntent, effects: list[ActiveEffect]) -> int:
    async def _run() -> Any:
        start = await start_combat(
            session_id=session,
            party=[
                PartyMemberSpec(
                    entity_id=_HERO,
                    name="Hero",
                    initiative=20,
                    hp_current=20,
                    hp_max=20,
                    attack_bonus=5,
                    strength=16,
                    intelligence=16,
                    spells_known=["fire-bolt"],
                    zone_id=_HERO_CELL,
                )
            ],
            encounter=[
                EncounterMemberSpec(
                    entity_id=_FOE,
                    entity_type="Monster",
                    name="Foe",
                    initiative=1,
                    ac=1,
                    hp_current=500,
                    hp_max=500,
                    zone_id=_FOE_CELL,
                )
            ],
            grid_scene=grid_scene(),
            rng_seed=11,
            active_effects=effects,
        )
        await submit_player_intent(start.handle, actor_id=_HERO, intent=intent)
        return _get_live(start.handle)

    live = run_async(_run())
    rolled = events_of(live, AttackRolled)
    assert rolled
    assert rolled[-1].is_hit
    return sum(e.amount for e in events_of(live, DamageApplied) if e.target_id == _FOE)


_SPEAR = PlayerIntent(intent_type="attack", weapon_id="spear", target_id=_FOE)
_FIRE_BOLT = PlayerIntent(intent_type="cast_spell", spell_id="fire-bolt", target_id=_FOE)


def test_untagged_damage_bonus_adds_to_a_weapon_hit() -> None:
    base = _damage_dealt("untagged-dmg-spear-base", _SPEAR, [])
    buffed = _damage_dealt("untagged-dmg-spear", _SPEAR, [_damage_bonus(1)])
    assert base > 0
    assert buffed == base + 1


def test_tagged_and_untagged_damage_bonuses_each_apply_once() -> None:
    base = _damage_dealt("both-dmg-spear-base", _SPEAR, [])
    buffed = _damage_dealt(
        "both-dmg-spear",
        _SPEAR,
        [_damage_bonus(2, tags=["attack"]), _damage_bonus(1)],
    )
    assert buffed == base + 3


def test_untagged_damage_bonus_adds_to_a_spell_attack_hit() -> None:
    base = _damage_dealt("untagged-dmg-bolt-base", _FIRE_BOLT, [])
    buffed = _damage_dealt("untagged-dmg-bolt", _FIRE_BOLT, [_damage_bonus(1)])
    assert base > 0
    assert buffed == base + 1


def test_weapon_tagged_damage_bonus_stays_off_a_spell_attack() -> None:
    base = _damage_dealt("tagged-dmg-bolt-base", _FIRE_BOLT, [])
    buffed = _damage_dealt(
        "tagged-dmg-bolt",
        _FIRE_BOLT,
        [_damage_bonus(2, tags=["attack"]), _damage_bonus(1)],
    )
    assert buffed == base + 1
