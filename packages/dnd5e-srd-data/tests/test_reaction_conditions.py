"""C22-S07 — typed reaction triggers derived from Foundry's free-text
``activation.condition``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from dnd5e_srd_data.schema.common import ActivationBlock, ReactionCondition, ReactionTriggerKind
from tools.translators.foundry import reaction_conditions_from_text, translate_spell_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "foundry_pack_minimal"


def test_activation_block_defaults_to_no_reaction_conditions():
    assert ActivationBlock().reaction_conditions == []
    block = ActivationBlock(
        type="reaction",
        reaction_conditions=[ReactionCondition(kind=ReactionTriggerKind.HIT_BY_ATTACK)],
    )
    assert ActivationBlock.model_validate(block.model_dump(mode="json")) == block


def test_shield_phrase_yields_two_disjoint_triggers():
    text = "when you are hit by an attack roll or targeted by the Magic Missile spell"
    conds = reaction_conditions_from_text(text)
    assert [c.kind for c in conds] == [
        ReactionTriggerKind.HIT_BY_ATTACK,
        ReactionTriggerKind.TARGETED_BY_SPELL,
    ]
    assert conds[1].target_spell_slug == "magic-missile"
    assert all(c.condition_text == text for c in conds)


def test_counterspell_hellish_rebuke_feather_fall_phrases():
    counterspell = reaction_conditions_from_text(
        "when you see a creature within range casting a spell with Verbal, Somatic, or Material components"
    )
    assert [c.kind for c in counterspell] == [ReactionTriggerKind.SEES_SPELL_CAST]
    assert counterspell[0].max_range_ft is None  # "within range" defers to the activity range
    rebuke = reaction_conditions_from_text(
        "taking damage from a creature that you can see within 60 feet of yourself"
    )
    assert [c.kind for c in rebuke] == [ReactionTriggerKind.TAKES_DAMAGE]
    assert rebuke[0].max_range_ft == 60
    fall = reaction_conditions_from_text(
        "when you or a creature you can see within 60 feet of you falls"
    )
    assert [c.kind for c in fall] == [ReactionTriggerKind.CREATURE_FALLS]
    assert fall[0].max_range_ft == 60


def test_unknown_phrase_is_the_catch_all():
    assert (
        reaction_conditions_from_text("when a creature ends its turn within 5 feet of the octopus")
        == []
    )
    assert reaction_conditions_from_text("") == []


def test_shield_utility_activity_inherits_the_item_level_reaction_condition():
    spell = translate_spell_yaml(
        yaml_path=FIXTURE / "spells" / "shield.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    utility = next(a for a in spell.activities if a.kind == "utility")
    kinds = {c.kind for c in utility.activation.reaction_conditions}
    assert kinds == {ReactionTriggerKind.HIT_BY_ATTACK, ReactionTriggerKind.TARGETED_BY_SPELL}


def test_lightning_bolt_has_no_reaction_conditions():
    spell = translate_spell_yaml(
        yaml_path=FIXTURE / "spells" / "lightning-bolt.yml",
        ingest_date=date(2026, 5, 30),
        ingest_version="foundry-translator-v1",
    )
    assert all(a.activation.reaction_conditions == [] for a in spell.activities)
