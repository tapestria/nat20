from datetime import date

import pytest
from pydantic import ValidationError

from dnd5e_srd_data.schema.background import Background, BackgroundAbilityChoice
from dnd5e_srd_data.schema.common import Provenance, ReviewState


def _prov() -> Provenance:
    return Provenance(
        source="foundry",
        source_url="x",
        ingest_date=date(2026, 5, 30),
        ingest_version="v1",
        srd_version=frozenset({"5.2"}),
    )


def test_background_minimal_acolyte() -> None:
    bg = Background(
        slug="acolyte",
        name="Acolyte",
        description="A devout servant.",
        ability_options=BackgroundAbilityChoice(
            options=frozenset({"int", "wis", "cha"}),
            cap=2,
            points=3,
        ),
        skill_proficiencies=["ins", "rel"],
        tool_proficiencies=["art:calligrapher"],
        languages=["common"],
        starting_feat_slug="phbftMagicInitia",
        wealth="50",
        provenance=_prov(),
        review=ReviewState(),
    )
    assert bg.slug == "acolyte"
    assert bg.ability_options.options == frozenset({"int", "wis", "cha"})
    assert bg.skill_proficiencies == ["ins", "rel"]
    assert bg.starting_feat_slug == "phbftMagicInitia"
    assert bg.entry_kind == "background"


def test_background_ability_options_serialize_sorted() -> None:
    bg = Background(
        slug="x",
        name="X",
        description="d",
        ability_options=BackgroundAbilityChoice(
            options=frozenset({"wis", "cha", "int"}),
            cap=2,
            points=3,
        ),
        provenance=_prov(),
        review=ReviewState(),
    )
    dumped = bg.model_dump(mode="json")
    # frozenset → deterministic sorted list for byte-stable canonical output.
    assert dumped["ability_options"]["options"] == ["cha", "int", "wis"]


def test_background_rejects_unknown_ability() -> None:
    with pytest.raises(ValidationError):
        BackgroundAbilityChoice(
            options=frozenset({"int", "wis", "luck"}),  # type: ignore[arg-type]
            cap=2,
            points=3,
        )
