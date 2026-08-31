"""Rules-glossary condition pages → ``Condition`` (C22).

Foundry has NO structured condition mechanics: ``content24/appendices/
rules-glossary.yml`` pages (``system.type: condition``) are prose, and
``module/config.mjs::DND5E.conditionTypes`` only links Active-Effect statuses.
So the mechanics live here, one typed row per SRD 5.2 sentence, with the
sentence quoted next to it. Changing a row is a rules-fidelity change and is
reviewed as such; the canonical JSON is regenerated, never hand-edited.

SRD gate: journal pages carry no ``system.source.license``. The SRD 5.2 rules
glossary defines exactly the 15 conditions in ``SRD_CONDITION_SLUGS``; only
those pages are admitted, and a missing one is a regen failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from dnd5e_srd_data.schema.common import ReviewState
from dnd5e_srd_data.schema.condition import Condition, ConditionEffect, ConditionEffectKind
from tools.translators.foundry import _provenance
from tools.translators.prose_cleanup import cleanup_prose

K = ConditionEffectKind

#: SRD 5.2 rules glossary, Appendix — the complete condition list.
SRD_CONDITION_SLUGS: frozenset[str] = frozenset(
    {
        "blinded",
        "charmed",
        "deafened",
        "exhaustion",
        "frightened",
        "grappled",
        "incapacitated",
        "invisible",
        "paralyzed",
        "petrified",
        "poisoned",
        "prone",
        "restrained",
        "stunned",
        "unconscious",
    }
)


@dataclass(frozen=True)
class ConditionMechanics:
    effects: tuple[ConditionEffect, ...]
    implies: tuple[str, ...] = ()
    srd_quote: str = field(default="", compare=False)


def _e(
    kind: K,
    *,
    abilities: tuple[str, ...] = (),
    value: int | None = None,
    qualifier: str = "",
) -> ConditionEffect:
    return ConditionEffect(kind=kind, abilities=list(abilities), value=value, qualifier=qualifier)


#: slug → typed mechanics. Every ``srd_quote`` is the SRD 5.2 glossary text
#: (``rules-glossary.yml`` page named after the slug) the rows were read from.
CONDITION_MECHANICS: dict[str, ConditionMechanics] = {
    "blinded": ConditionMechanics(
        effects=(
            _e(K.AUTO_FAIL_SIGHT_CHECKS),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
            _e(K.DISADVANTAGE_OWN_ATTACKS),
        ),
        srd_quote=(
            "You can't see and automatically fail any ability check that requires sight. "
            "Attack rolls against you have Advantage, and your attack rolls have Disadvantage."
        ),
    ),
    "charmed": ConditionMechanics(
        effects=(
            _e(K.CANT_ATTACK_CHARMER),
            _e(K.CHARMER_SOCIAL_ADVANTAGE),
        ),
        srd_quote=(
            "You can't attack the charmer or target the charmer with damaging abilities or "
            "magical effects. The charmer has Advantage on any ability check to interact with "
            "you socially."
        ),
    ),
    "deafened": ConditionMechanics(
        effects=(_e(K.AUTO_FAIL_HEARING_CHECKS),),
        srd_quote="You can't hear and automatically fail any ability check that requires hearing.",
    ),
    "exhaustion": ConditionMechanics(
        effects=(
            _e(K.D20_TEST_PENALTY_PER_LEVEL, value=2),
            _e(K.SPEED_PENALTY_PER_LEVEL, value=5),
            _e(K.DEATH_AT_LEVEL, value=6),
        ),
        srd_quote=(
            "You die if your Exhaustion level is 6. When you make a D20 Test, the roll is "
            "reduced by 2 times your Exhaustion level. Your Speed is reduced by a number of "
            "feet equal to 5 times your Exhaustion level."
        ),
    ),
    "frightened": ConditionMechanics(
        effects=(
            _e(
                K.DISADVANTAGE_ABILITY_CHECKS,
                qualifier="while the source of fear is within line of sight",
            ),
            _e(
                K.DISADVANTAGE_OWN_ATTACKS,
                qualifier="while the source of fear is within line of sight",
            ),
            _e(K.CANT_MOVE_TOWARD_FEAR_SOURCE),
        ),
        srd_quote=(
            "You have Disadvantage on ability checks and attack rolls while the source of fear "
            "is within line of sight. You can't willingly move closer to the source of fear."
        ),
    ),
    "grappled": ConditionMechanics(
        effects=(
            _e(K.SPEED_ZERO),
            _e(K.DISADVANTAGE_ATTACKS_EXCEPT_GRAPPLER),
            _e(K.MOVABLE_BY_GRAPPLER),
        ),
        srd_quote=(
            "Your Speed is 0 and can't increase. You have Disadvantage on attack rolls against "
            "any target other than the grappler. The grappler can drag or carry you when it "
            "moves, but every foot of movement costs it 1 extra foot unless you are Tiny or two "
            "or more sizes smaller than it."
        ),
    ),
    "incapacitated": ConditionMechanics(
        effects=(
            _e(K.CANNOT_TAKE_ACTIONS),
            _e(K.BREAKS_CONCENTRATION),
            _e(K.CANNOT_SPEAK),
            _e(
                K.DISADVANTAGE_INITIATIVE,
                qualifier="if you're Incapacitated when you roll Initiative",
            ),
        ),
        srd_quote=(
            "You can't take any action, Bonus Action, or Reaction. Your Concentration is "
            "broken. You can't speak. If you're Incapacitated when you roll Initiative, you "
            "have Disadvantage on the roll."
        ),
    ),
    "invisible": ConditionMechanics(
        effects=(
            _e(
                K.ADVANTAGE_INITIATIVE,
                qualifier="if you're Invisible when you roll Initiative",
            ),
            _e(K.UNSEEN, qualifier="unless the effect's creator can somehow see you"),
            _e(
                K.DISADVANTAGE_ATTACKS_AGAINST,
                qualifier=(
                    "if a creature can somehow see you, you don't gain this benefit against "
                    "that creature"
                ),
            ),
            _e(
                K.ADVANTAGE_OWN_ATTACKS,
                qualifier=(
                    "if a creature can somehow see you, you don't gain this benefit against "
                    "that creature"
                ),
            ),
        ),
        srd_quote=(
            "If you're Invisible when you roll Initiative, you have Advantage on the roll. You "
            "aren't affected by any effect that requires its target to be seen unless the "
            "effect's creator can somehow see you. Attack rolls against you have Disadvantage, "
            "and your attack rolls have Advantage. If a creature can somehow see you, you don't "
            "gain this benefit against that creature."
        ),
    ),
    "paralyzed": ConditionMechanics(
        effects=(
            _e(K.SPEED_ZERO),
            _e(K.AUTO_FAIL_SAVE, abilities=("str", "dex")),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
            _e(K.AUTO_CRIT_WITHIN_5FT, value=5),
        ),
        implies=("incapacitated",),
        srd_quote=(
            "You have the Incapacitated condition. Your Speed is 0 and can't increase. You "
            "automatically fail Strength and Dexterity saving throws. Attack rolls against you "
            "have Advantage. Any attack roll that hits you is a Critical Hit if the attacker is "
            "within 5 feet of you."
        ),
    ),
    "petrified": ConditionMechanics(
        effects=(
            _e(K.SPEED_ZERO),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
            _e(K.AUTO_FAIL_SAVE, abilities=("str", "dex")),
            _e(K.RESIST_ALL_DAMAGE),
            _e(K.IMMUNE_TO_CONDITION, qualifier="poisoned"),
        ),
        implies=("incapacitated",),
        srd_quote=(
            "You have the Incapacitated condition. Your Speed is 0 and can't increase. Attack "
            "rolls against you have Advantage. You automatically fail Strength and Dexterity "
            "saving throws. You have Resistance to all damage. You have Immunity to the "
            "Poisoned condition."
        ),
    ),
    "poisoned": ConditionMechanics(
        effects=(
            _e(K.DISADVANTAGE_OWN_ATTACKS),
            _e(K.DISADVANTAGE_ABILITY_CHECKS),
        ),
        srd_quote="You have Disadvantage on attack rolls and ability checks.",
    ),
    "prone": ConditionMechanics(
        effects=(
            _e(
                K.RESTRICTED_MOVEMENT_CRAWL,
                qualifier=(
                    "spend an amount of movement equal to half your Speed (round down) to "
                    "right yourself"
                ),
            ),
            _e(K.DISADVANTAGE_OWN_ATTACKS),
            _e(
                K.ADVANTAGE_ATTACKS_AGAINST,
                value=5,
                qualifier="if the attacker is within 5 feet of you",
            ),
            _e(
                K.DISADVANTAGE_ATTACKS_AGAINST,
                value=5,
                qualifier="otherwise (the attacker is more than 5 feet from you)",
            ),
        ),
        srd_quote=(
            "Your only movement options are to crawl or to spend an amount of movement equal to "
            "half your Speed (round down) to right yourself and thereby end the condition. You "
            "have Disadvantage on attack rolls. An attack roll against you has Advantage if the "
            "attacker is within 5 feet of you. Otherwise, that attack roll has Disadvantage."
        ),
    ),
    "restrained": ConditionMechanics(
        effects=(
            _e(K.SPEED_ZERO),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
            _e(K.DISADVANTAGE_OWN_ATTACKS),
            _e(K.DISADVANTAGE_SAVE, abilities=("dex",)),
        ),
        srd_quote=(
            "Your Speed is 0 and can't increase. Attack rolls against you have Advantage, and "
            "your attack rolls have Disadvantage. You have Disadvantage on Dexterity saving "
            "throws."
        ),
    ),
    "stunned": ConditionMechanics(
        effects=(
            _e(K.AUTO_FAIL_SAVE, abilities=("str", "dex")),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
        ),
        implies=("incapacitated",),
        srd_quote=(
            "You have the Incapacitated condition. You automatically fail Strength and "
            "Dexterity saving throws. Attack rolls against you have Advantage."
        ),
    ),
    "unconscious": ConditionMechanics(
        effects=(
            _e(K.DROPS_HELD_ITEMS),
            _e(K.SPEED_ZERO),
            _e(K.ADVANTAGE_ATTACKS_AGAINST),
            _e(K.AUTO_FAIL_SAVE, abilities=("str", "dex")),
            _e(K.AUTO_CRIT_WITHIN_5FT, value=5),
        ),
        implies=("incapacitated", "prone"),
        srd_quote=(
            "You have the Incapacitated and Prone conditions, and you drop whatever you're "
            "holding. Your Speed is 0 and can't increase. Attack rolls against you have "
            "Advantage. You automatically fail Strength and Dexterity saving throws. Any attack "
            "roll that hits you is a Critical Hit if the attacker is within 5 feet of you."
        ),
    ),
}

# ``&Reference[Blinded]`` / ``&amp;Reference[Blinded]`` — journal-only enricher
# the shared cleanup does not know; keep the label text.
_REFERENCE_ENRICHER = re.compile(r"&(?:amp;)?Reference\[([^\]]+)\]")


def _clean_page_text(html: str) -> str:
    return cleanup_prose(_REFERENCE_ENRICHER.sub(r"\1", html))


def _page_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def translate_condition_pages(
    yaml_path: Path,
    *,
    ingest_date: date,
    ingest_version: str,
    require_complete: bool = True,
) -> list[Condition]:
    """Walk one rules-glossary journal and emit a ``Condition`` per admitted
    ``system.type == "condition"`` page, in journal page order.

    ``require_complete`` (the regen default) raises when any of the 15 SRD
    conditions is absent — a silent drop would ship an incomplete category.
    Tests translating a partial fixture pass ``False``.
    """
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    pages = doc.get("pages") if isinstance(doc, dict) else None
    if not isinstance(pages, list):
        return []
    out: list[Condition] = []
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        if ((page.get("system") or {}).get("type")) != "condition":
            continue
        slug = _page_slug(str(page.get("name") or ""))
        if slug not in SRD_CONDITION_SLUGS:
            print(f"[conditions-translator] skipping non-SRD condition page {slug!r}")
            continue
        mechanics = CONDITION_MECHANICS[slug]
        html = ((page.get("text") or {}).get("content")) or ""
        out.append(
            Condition(
                slug=slug,
                name=str(page.get("name")),
                description=_clean_page_text(str(html)),
                effects=list(mechanics.effects),
                implies=list(mechanics.implies),
                provenance=_provenance(yaml_path, ingest_date, ingest_version),
                review=ReviewState(),
            )
        )
        seen.add(slug)
    missing = sorted(SRD_CONDITION_SLUGS - seen)
    if missing and require_complete:
        raise RuntimeError(f"rules-glossary is missing SRD conditions: {missing}")
    return out
