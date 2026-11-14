"""The scripted-dice test seam: ``dnd5e_engine.testing.rng_factory``.

Every die a combat rolls, the Initiative rolled inside ``start_combat``
included, comes from the one ``random.Random`` that ``start_combat`` builds
from ``rng_seed``. A seed reproduces a fight but cannot force a chosen roll,
so a host test suite needs to supply its own ``random.Random`` (a subclass
that scripts or records ``randint``). Within the ``rng_factory`` block every
new combat draws from ``factory(rng_seed)``; outside it the engine is
unchanged.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path

import pytest

import dnd5e_engine
from dnd5e_engine import orchestrator, testing
from dnd5e_engine.events import AttackRolled, SaveRolled
from dnd5e_engine.orchestrator import _LiveCombat
from tests.c21_support import act, combatant, events, foe, pc, start, wizard


class _Recording(random.Random):
    """Draws exactly as ``random.Random`` does and counts every ``randint``."""

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.draws = 0

    def randint(self, a: int, b: int) -> int:
        self.draws += 1
        return super().randint(a, b)


class _FirstD20IsTwenty(random.Random):
    """Rolls a natural 20 on the first d20, then draws as seeded."""

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.scripted = False

    def randint(self, a: int, b: int) -> int:
        if (a, b) == (1, 20) and not self.scripted:
            self.scripted = True
            return 20
        return super().randint(a, b)


def _log(live: _LiveCombat) -> list[dict[str, object]]:
    return [e.model_dump(mode="json") for e in live.event_log]


def _recorder(made: list[_Recording]) -> Callable[[int], random.Random]:
    def factory(seed: int) -> random.Random:
        made.append(_Recording(seed))
        return made[-1]

    return factory


def test_initiative_rolled_inside_start_combat_draws_from_the_factory() -> None:
    party = [pc(initiative=None)]
    encounter = [foe(initiative=None)]
    _, plain = start(party, seed=11, encounter=encounter)
    made: list[_Recording] = []
    with testing.rng_factory(_recorder(made)):
        _, recorded = start(party, seed=11, encounter=encounter)
    [rng] = made
    assert rng.draws > 0
    assert _log(recorded) == _log(plain)
    assert [c.initiative for c in recorded.initiative] == [c.initiative for c in plain.initiative]


def test_an_attack_and_a_save_draw_from_the_factory_and_match_the_plain_run() -> None:
    def fight() -> tuple[_LiveCombat, list[int]]:
        handle, live = start([wizard(), pc("char:hero", initiative=19)], seed=5)
        marks = [_draws()]
        act(
            handle,
            "char:wiz",
            intent_type="cast_spell",
            spell_id="hold-person",
            target_id="mon:foe",
        )
        marks.append(_draws())
        act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
        marks.append(_draws())
        return live, marks

    made: list[_Recording] = []

    def _draws() -> int:
        return made[-1].draws if made else 0

    plain, _ = fight()
    with testing.rng_factory(_recorder(made)):
        recorded, marks = fight()
    assert events(recorded, SaveRolled)
    assert events(recorded, AttackRolled)
    assert marks[1] - marks[0] > 0  # the save
    assert marks[2] - marks[1] > 0  # the attack
    assert _log(recorded) == _log(plain)


def test_a_scripted_factory_forces_a_natural_20_on_the_first_attack() -> None:
    with testing.rng_factory(_FirstD20IsTwenty):
        handle, live = start([pc()], seed=3)
        act(handle, "char:hero", intent_type="attack", weapon_id="longsword", target_id="mon:foe")
    [attack] = events(live, AttackRolled)
    assert attack.natural == 20
    assert combatant(live, "mon:foe").hp_current < 500


def test_the_default_factory_is_restored_after_the_block() -> None:
    with testing.rng_factory(_FirstD20IsTwenty):
        assert orchestrator._rng_factory is _FirstD20IsTwenty
    assert orchestrator._rng_factory is random.Random


def test_the_default_factory_is_restored_when_the_block_raises() -> None:
    with pytest.raises(RuntimeError), testing.rng_factory(_FirstD20IsTwenty):
        raise RuntimeError("boom")
    assert orchestrator._rng_factory is random.Random


def test_only_the_test_support_module_exposes_the_seam() -> None:
    assert "rng_factory" in testing.__all__
    assert "rng_factory" not in dnd5e_engine.__all__
    src = Path(dnd5e_engine.__file__).parent
    users = sorted(
        str(p.relative_to(src)) for p in src.rglob("*.py") if "rng_factory" in p.read_text()
    )
    assert users == ["orchestrator.py", "testing.py"]
