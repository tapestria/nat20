"""``ActiveEffect.statuses`` serializes in one order in every process.

The field is a ``set[str]``: its iteration order follows the process's string
hash seed, so a multi-status effect dumped straight from the set comes out in a
different order in every process, and a replayed stream stops being
byte-stable. Every dump mode emits the statuses sorted; the model keeps its set.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from dnd5e_engine.types.effects import ActiveEffect

_STATUSES = {"prone", "blinded", "deafened", "frightened", "grappled"}


def _effect() -> ActiveEffect:
    return ActiveEffect(
        id="effect:test",
        name="Test",
        origin="cast:test:char:a",
        target_id="char:a",
        statuses=set(_STATUSES),
    )


def test_statuses_dump_sorted_in_every_mode() -> None:
    effect = _effect()
    expected = sorted(_STATUSES)
    assert effect.model_dump()["statuses"] == expected
    assert effect.model_dump(mode="json")["statuses"] == expected
    assert json.loads(effect.model_dump_json())["statuses"] == expected
    assert effect.statuses == _STATUSES


def test_statuses_round_trip_to_the_same_effect() -> None:
    effect = _effect()
    assert ActiveEffect.model_validate(effect.model_dump()) == effect
    assert ActiveEffect.model_validate_json(effect.model_dump_json()) == effect


_DUMP = (
    "from dnd5e_engine.types.effects import ActiveEffect\n"
    "print(ActiveEffect(id='e', name='e', origin='o', target_id='t', statuses="
    "{'prone', 'blinded', 'deafened', 'frightened', 'grappled'}).model_dump_json())\n"
)


def test_statuses_json_is_stable_across_hash_seeds() -> None:
    dumps = {
        subprocess.run(
            [sys.executable, "-c", _DUMP],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("0", "1", "2", "3", "4", "5")
    }
    assert len(dumps) == 1
