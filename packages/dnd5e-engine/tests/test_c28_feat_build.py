"""Feats on the derived sheet: the background's Origin feat, repeats, the Epic
Boon floor and Magic Initiate's choices.

SRD 5.2: "A background gives your character a specified Origin feat"; "A feat
can be taken only once unless its description states otherwise in a
"Repeatable" subsection." Magic Initiate: "You learn two cantrips of your
choice from the Cleric, Druid, or Wizard spell list. Intelligence, Wisdom, or
Charisma is your spellcasting ability for this feat's spells ... Choose a
level 1 spell from the same list ... You can cast it once without a spell
slot ... Repeatable. You can take this feat more than once, but you must
choose a different spell list each time."
"""

from __future__ import annotations

from typing import Any

import pytest
from dnd5e_srd_data.loader import BundledAssetLoader
from dnd5e_srd_data.schema.background import Background
from dnd5e_srd_data.schema.feat import Feat, FeatPrerequisite

from dnd5e_engine.build_party import build_party_member
from dnd5e_engine.build_spec import CombatInstance, DerivedSheet, derive_sheet, make_build_spec
from dnd5e_engine.rules.choices import MagicInitiatePick, parse_selected_choices
from dnd5e_engine.spatial import cell_id

LOADER = BundledAssetLoader()

_CLERIC = "magic-initiate:cleric:wis:guidance,sacred-flame:guiding-bolt"
_WIZARD = "magic-initiate:wizard:int:fire-bolt,mage-hand:shield"


def _sheet(**fields: Any) -> DerivedSheet:
    fields.setdefault("species_slug", "dwarf")
    fields.setdefault("class_slug", "fighter")
    return derive_sheet(make_build_spec(**fields), loader=LOADER)


# ── the magic-initiate: token ────────────────────────────────────────────────


def test_a_magic_initiate_token_parses_its_list_ability_cantrips_and_spell() -> None:
    # The ability is a long name or a three-letter code.
    for ability in ("wis", "wisdom"):
        token = f"magic-initiate:cleric:{ability}:guidance,sacred-flame:guiding-bolt"
        assert parse_selected_choices((token,)).magic_initiate == (
            MagicInitiatePick("cleric", "wis", ("guidance", "sacred-flame"), "guiding-bolt"),
        )


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        (("magic-initiate:bard:cha:vicious-mockery,light:bless",), "cleric, druid or wizard"),
        (("magic-initiate:cleric:str:guidance,light:bless",), "Intelligence, Wisdom or Charisma"),
        (("magic-initiate:cleric:wis:guidance:bless",), "two different cantrips"),
        (("magic-initiate:cleric:wis:guidance,guidance:bless",), "two different cantrips"),
        (("magic-initiate:cleric:wis:guidance,light",), "expected magic-initiate:"),
        (
            (_CLERIC, "magic-initiate:cleric:int:light,thaumaturgy:bless"),
            "repeats Magic Initiate spell lists: ['cleric']",
        ),
        (
            (_CLERIC, "magic-initiate:druid:wis:guidance,druidcraft:cure-wounds"),
            "repeats Magic Initiate spells: ['guidance']",
        ),
        (("magic-initiate:cleric:wis:guidance,light:Bless",), "'Bless' is not a spell slug"),
    ],
)
def test_a_malformed_magic_initiate_token_is_refused(tokens: tuple[str, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_selected_choices(tokens)


# ── the background's feat ────────────────────────────────────────────────────


def test_the_backgrounds_feat_comes_first_and_joins_the_others() -> None:
    sheet = _sheet(
        background_slug="soldier",
        level=4,
        ability_scores={"strength": 13},
        selected_choices=("feat:fighter:4:grappler",),
    )
    assert sheet.feats == ("savage-attacker", "grappler")
    assert _sheet().feats == ()


def test_the_backgrounds_feat_counts_against_a_feat_token() -> None:
    # A Criminal already has Alert: Alert again at the level-4 Ability Score
    # Improvement takes it twice.
    with pytest.raises(ValueError, match="feat 'alert' is not repeatable; the build takes it 2"):
        _sheet(background_slug="criminal", level=4, selected_choices=("feat:fighter:4:alert",))


class _BackgroundsGrantAnUnknownFeat(BundledAssetLoader):
    """The bundled corpus, with every background granting a feat it lacks."""

    def get_background(self, slug: str) -> Background | None:
        found = super().get_background(slug)
        return found and found.model_copy(update={"starting_feat_slug": "no-such-feat"})


def test_a_background_granting_an_unknown_feat_is_refused() -> None:
    spec = make_build_spec(species_slug="dwarf", class_slug="fighter", background_slug="criminal")
    with pytest.raises(
        ValueError, match="background 'criminal' grants unknown feat 'no-such-feat'"
    ):
        derive_sheet(spec, loader=_BackgroundsGrantAnUnknownFeat())


def test_an_epic_boon_at_a_lower_ability_score_improvement_is_refused() -> None:
    # A Fighter 19 reached its level-4 Ability Score Improvement at character
    # level 4; Epic Boon feats need "Level 19+".
    with pytest.raises(ValueError, match="is taken at character level 4 at most"):
        _sheet(level=19, selected_choices=("feat:fighter:4:boon-of-fate",))


class _GrapplerNeedsLevel8(BundledAssetLoader):
    """The bundled corpus, with Grappler's level prerequisite raised to 8."""

    def get_feat(self, slug: str) -> Feat | None:
        found = super().get_feat(slug)
        if found is None or slug != "grappler":
            return found
        return found.model_copy(update={"prerequisites": [FeatPrerequisite(level=8)]})


def test_a_multiclass_level_prerequisite_is_checked_against_the_level_taken() -> None:
    # Fighter 8/Rogue 1: the level-4 Ability Score Improvement was reached at
    # character level 5 at most (every level Fighter gained afterwards could
    # have come after it), below a feat needing character level 8.
    spec = make_build_spec(
        species_slug="dwarf",
        classes={"fighter": 8, "rogue": 1},
        selected_choices=("feat:fighter:4:grappler",),
    )
    with pytest.raises(ValueError, match="is taken at character level 5 at most"):
        derive_sheet(spec, loader=_GrapplerNeedsLevel8())


def test_a_fighting_style_taken_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="feat 'defense' is not repeatable; the build takes it 2"):
        _sheet(level=4, selected_choices=("defense", "feat:fighter:4:defense"))


# ── Magic Initiate on the sheet ──────────────────────────────────────────────


def test_magic_initiate_records_each_spells_ability_and_its_slotless_spell() -> None:
    sheet = _sheet(background_slug="acolyte", selected_choices=(_CLERIC,))
    assert sheet.feats == ("magic-initiate",)
    assert sheet.spell_abilities == {
        "guidance": "wis",
        "sacred-flame": "wis",
        "guiding-bolt": "wis",
    }
    assert sheet.slotless_casts == ("guiding-bolt",)


def test_two_magic_initiates_need_two_lists_and_keep_both_choices() -> None:
    # An Acolyte Human takes Magic Initiate again from Versatile.
    sheet = _sheet(
        species_slug="human",
        background_slug="acolyte",
        selected_choices=("magic-initiate", _CLERIC, _WIZARD),
    )
    assert sheet.feats == ("magic-initiate", "magic-initiate")
    assert sheet.spell_abilities == {
        "guidance": "wis",
        "sacred-flame": "wis",
        "guiding-bolt": "wis",
        "fire-bolt": "int",
        "mage-hand": "int",
        "shield": "int",
    }
    assert sheet.slotless_casts == ("guiding-bolt", "shield")


def test_a_magic_initiate_without_a_token_has_no_spells_yet() -> None:
    sheet = _sheet(background_slug="sage")
    assert (sheet.feats, sheet.spell_abilities, sheet.slotless_casts) == (
        ("magic-initiate",),
        {},
        (),
    )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"selected_choices": (_CLERIC,)}, "1 magic-initiate: tokens but the build takes"),
        (
            {
                "background_slug": "acolyte",
                "selected_choices": ("magic-initiate:cleric:wis:guidance,bless:guiding-bolt",),
            },
            "'bless' is a level 1 spell, not a cantrip",
        ),
        (
            {
                "background_slug": "acolyte",
                "selected_choices": ("magic-initiate:cleric:wis:guidance,light:spirit-guardians",),
            },
            "'spirit-guardians' is a level 3 spell, not a level 1 spell",
        ),
        (
            {
                "background_slug": "acolyte",
                "selected_choices": ("magic-initiate:cleric:wis:guidance,light:no-such-spell",),
            },
            "unknown spell: 'no-such-spell'",
        ),
    ],
)
def test_magic_initiate_choices_must_fit_the_feat(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _sheet(**fields)


# ── build_party_member ───────────────────────────────────────────────────────


def test_magic_initiate_reaches_the_party_spec() -> None:
    member = build_party_member(
        make_build_spec(
            species_slug="dwarf",
            class_slug="fighter",
            background_slug="acolyte",
            selected_choices=(_CLERIC,),
        ),
        CombatInstance(
            entity_id="char:hero",
            name="Hero",
            zone_id=cell_id(0, 0),
            spells_known=("light", "guidance"),
        ),
        loader=LOADER,
    )
    # The host's spells first, then the feat's, each once.
    assert member.spells_known == ["light", "guidance", "sacred-flame", "guiding-bolt"]
    assert member.spell_abilities == {
        "guidance": "wis",
        "sacred-flame": "wis",
        "guiding-bolt": "wis",
    }
    assert member.slotless_casts == ("guiding-bolt",)
    assert member.feats == ("magic-initiate",)
