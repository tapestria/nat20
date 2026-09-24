"""The ``selected_choices`` token grammar (rules/choices.py) and the skill
vocabularies it and ``activities/check.py`` share (rules/skills.py)."""

from __future__ import annotations

from typing import get_args

import pytest

from dnd5e_engine.rules.choices import AsiPick, FeatPick, parse_selected_choices
from dnd5e_engine.rules.skills import SKILL_ABILITIES, SKILL_CODE_TO_SLUG, Skill


def test_skill_vocabularies_agree() -> None:
    assert set(get_args(Skill)) == set(SKILL_ABILITIES) == set(SKILL_CODE_TO_SLUG.values())


def test_parses_every_token_kind() -> None:
    parsed = parse_selected_choices(
        (
            "skill:Sleight of Hand",
            "expertise:stealth",
            "background:str+2,constitution+1",
            "asi:fighter:4:strength+2",
            "feat:fighter:6:grappler",
            "defense",
        )
    )
    assert parsed.skills == ("sleight_of_hand",)
    assert parsed.expertise == ("stealth",)
    assert parsed.background == {"strength": 2, "constitution": 1}
    assert parsed.asis == (AsiPick("fighter", 4, {"strength": 2}),)
    assert parsed.feats == (FeatPick("fighter", 6, "grappler"),)
    assert parsed.picks == ("defense",)


def test_no_tokens_parse_to_nothing() -> None:
    parsed = parse_selected_choices(())
    assert (parsed.skills, parsed.background, parsed.asis, parsed.picks) == ((), None, (), ())


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("skill:flying", "unknown skill"),
        ("asi:4:strength+2", "expected asi:<class>:<level>"),
        ("asi:fighter:four:strength+2", "expected <class>:<level>"),
        ("asi:fighter:4:strength2", "expected <ability>\\+<n>"),
        ("asi:fighter:4:luck+2", "unknown ability"),
        ("asi:fighter:4:str+1,strength+1", "twice"),
        ("feat:fighter:4:Not A Slug", "feat slug"),
        ("wish:granted", "unknown kind"),
        ("Not A Slug", "not a known kind or a slug"),
    ],
)
def test_malformed_tokens_are_rejected(token: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_selected_choices((token,))


def test_repeats_are_rejected() -> None:
    with pytest.raises(ValueError, match="repeats"):
        parse_selected_choices(("defense", "defense"))
    with pytest.raises(ValueError, match="repeats"):
        parse_selected_choices(("skill:athletics", "skill:Athletics"))
    with pytest.raises(ValueError, match="more than one background"):
        parse_selected_choices(("background:str+2,con+1", "background:dex+1,con+1,str+1"))
