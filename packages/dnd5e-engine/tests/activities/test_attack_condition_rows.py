"""C12 — Prone (distance-aware) and Grappled (grappler-aware) rows on the live
attack path, fed by the ``target_distance_ft`` / ``attacker_grappler_id``
sidecars. SRD 5.2 glossary, Prone and Grappled."""

from __future__ import annotations

import random

from dnd5e_srd_data.loader import BundledAssetLoader

from dnd5e_engine.activities.context import ActivityResolutionContext
from dnd5e_engine.activities.resolver import resolve_activity
from dnd5e_engine.events import AttackRolled
from dnd5e_engine.types.combat import Combatant
from dnd5e_engine.types.conditions import ActiveCondition

_SEED = 9


def _fighter(*conditions: str) -> Combatant:
    return Combatant(
        entity_id="char:fighter",
        entity_type="Character",
        name="Fighter",
        initiative=10,
        hp_current=20,
        hp_max=20,
        conditions=[
            ActiveCondition(condition=c, source_entity_id="implied:effect", scope="combat")
            for c in conditions
        ],
    )


def _foe(entity_id: str = "mon:foe", *conditions: str) -> Combatant:
    return Combatant(
        entity_id=entity_id,
        entity_type="Monster",
        name="Foe",
        initiative=1,
        hp_current=500,
        hp_max=500,
        ac=1,
        conditions=[
            ActiveCondition(condition=c, source_entity_id="implied:effect", scope="combat")
            for c in conditions
        ],
    )


def _swing(
    attacker: Combatant,
    target: Combatant,
    *,
    distance_ft: int | None = None,
    grappler_id: str | None = None,
    forced_d20: int | None = None,
    d20_test_penalty: dict[str, int] | None = None,
) -> AttackRolled:
    weapon = BundledAssetLoader().get_weapon("dagger")
    assert weapon is not None
    activity = next(a for a in weapon.activities if a.kind == "attack")
    events: list = []
    ctx = ActivityResolutionContext(
        rng=random.Random(_SEED),
        caster=attacker,
        targets=[target],
        event_emitter=events.append,
        caster_abilities={"str": 10, "dex": 18, "con": 10, "int": 10, "wis": 10, "cha": 10},
        caster_proficiency_bonus=3,
        caster_level=5,
        attacker_conditions=[c.condition for c in attacker.conditions],
        target_conditions={target.entity_id: [c.condition for c in target.conditions]},
        target_distance_ft={} if distance_ft is None else {target.entity_id: distance_ft},
        attacker_grappler_id=grappler_id,
        d20_test_penalty=d20_test_penalty or {},
        variables={} if forced_d20 is None else {"force_d20": forced_d20},
    )
    resolve_activity(activity, ctx, weapon=weapon)
    rolled = [e for e in events if isinstance(e, AttackRolled)]
    assert len(rolled) == 1
    return rolled[0]


def test_prone_target_within_5ft_grants_advantage() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "prone"), distance_ft=5)
    assert e.advantage == "advantage"
    assert "condition:target" in e.sources


def test_prone_target_beyond_5ft_imposes_disadvantage() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "prone"), distance_ft=30)
    assert e.advantage == "disadvantage"
    assert "condition:target" in e.sources


def test_prone_target_without_distance_sidecar_rolls_normally() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "prone"))
    assert e.advantage == "normal"
    assert e.sources == []


def test_prone_attacker_has_disadvantage() -> None:
    e = _swing(_fighter("prone"), _foe(), distance_ft=5)
    assert e.advantage == "disadvantage"
    assert "condition:attacker" in e.sources


def test_grappled_attacker_vs_non_grappler_has_disadvantage() -> None:
    e = _swing(_fighter("grappled"), _foe("mon:goblin"), distance_ft=5, grappler_id="mon:ogre")
    assert e.advantage == "disadvantage"


def test_grappled_attacker_vs_grappler_rolls_normally() -> None:
    e = _swing(_fighter("grappled"), _foe("mon:ogre"), distance_ft=5, grappler_id="mon:ogre")
    assert e.advantage == "normal"


def test_no_condition_still_consumes_exactly_one_draw() -> None:
    e = _swing(_fighter(), _foe(), distance_ft=5)
    mirror = random.Random(_SEED)
    assert e.natural == mirror.randint(1, 20)


# SRD 5.2 Paralyzed / Unconscious: "Any attack roll that hits you is a Critical
# Hit if the attacker is within 5 feet of you."
def test_hit_on_paralyzed_target_within_5ft_is_a_critical_hit() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "paralyzed"), distance_ft=5, forced_d20=10)
    assert e.is_hit is True
    assert e.is_crit is True
    assert e.advantage == "advantage"


def test_hit_on_unconscious_target_within_5ft_is_a_critical_hit() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "unconscious"), distance_ft=0, forced_d20=10)
    assert e.is_crit is True


def test_hit_on_paralyzed_target_beyond_5ft_is_not_forced_to_crit() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "paralyzed"), distance_ft=10, forced_d20=10)
    assert e.is_hit is True
    assert e.is_crit is False


def test_natural_one_still_misses_a_paralyzed_target() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "paralyzed"), distance_ft=5, forced_d20=1)
    assert e.is_hit is False
    assert e.is_crit is False


def test_stunned_target_within_5ft_does_not_auto_crit() -> None:
    e = _swing(_fighter(), _foe("mon:foe", "stunned"), distance_ft=5, forced_d20=10)
    assert e.is_crit is False


def test_exhaustion_penalty_lowers_attack_modifier_and_total_without_extra_draws() -> None:
    plain = _swing(_fighter(), _foe(), forced_d20=10)
    tired = _swing(
        _fighter("exhaustion"), _foe(), forced_d20=10, d20_test_penalty={"char:fighter": -4}
    )
    assert tired.modifier == plain.modifier - 4
    assert tired.roll_total == plain.roll_total - 4
    assert tired.advantage == "normal"
