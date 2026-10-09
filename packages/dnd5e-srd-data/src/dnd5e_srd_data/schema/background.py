"""Background schema (2024 SRD).

Foundry encodes the four 2024 SRD backgrounds (acolyte, criminal, sage,
soldier) as ``type: background`` documents. The mechanical payload lives in
``system.advancement[]``:

- An ``AbilityScoreImprovement`` advancement carries the +2/+1 ability-score
  choice. Foundry expresses the *eligible* abilities indirectly via
  ``configuration.locked`` (the three abilities the background does NOT
  improve); the translator inverts that to the three improvable abilities.
- A ``Trait`` advancement grants the fixed skill + tool proficiencies
  (``skills:<short>`` / ``tool:<group>:<kind>`` grant strings).
- A second ``Trait`` advancement grants the language(s) (``languages:...``).
- An ``ItemGrant`` advancement titled "Background Feat" grants the starting
  feat (a Foundry compendium UUID, which the translator resolves to the
  feat's canonical slug).

``system.startingEquipment[]`` plus ``system.wealth`` (the gp alternative)
carry the equipment options. The starting-equipment entries are preserved
structurally as opaque dicts — their group/linked/focus/tool shape is read
directly by downstream consumers (the engine, a host's importer).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, NonNegativeInt, field_serializer

from dnd5e_srd_data.schema.common import Provenance, ReviewState

Ability = Literal["str", "dex", "con", "int", "wis", "cha"]


class BackgroundAbilityChoice(BaseModel):
    """The background's +2/+1 ability-score improvement.

    ``options`` is the set of three abilities the player may raise (Foundry
    stores the complement in ``configuration.locked``; the translator inverts
    it). ``cap`` is the per-ability ceiling for a single increase (2 in the
    2024 SRD) and ``points`` is the total spendable (3 — "+2 and +1, or three
    +1s")."""

    options: frozenset[Ability]
    cap: NonNegativeInt = 2
    points: NonNegativeInt = 3

    @field_serializer("options")
    def _serialize_options(self, value: frozenset[str]) -> list[str]:
        # frozenset → JSON list in deterministic (sorted) order so canonical
        # output is byte-stable across runs.
        return sorted(value)


class Background(BaseModel):
    slug: str
    name: str
    description: str
    ability_options: BackgroundAbilityChoice
    skill_proficiencies: list[str] = Field(default_factory=list)
    """Foundry skill short-codes (``ins``, ``rel``, ``ath`` …) from the
    proficiency ``Trait`` advancement's ``skills:<short>`` grants. Source
    order preserved."""
    tool_proficiencies: list[str] = Field(default_factory=list)
    """Foundry tool keys (``art:calligrapher``, ``thief``, ``game:*`` …) from
    the proficiency ``Trait`` advancement's ``tool:<...>`` grants — both fixed
    grants and ``game:*``-style player choices. Source order preserved."""
    languages: list[str] = Field(default_factory=list)
    """Granted language slugs from the language ``Trait`` advancement's
    ``languages:<group>:<slug>`` grants (e.g. ``common``). The two free
    "Standard Languages" choices are a player decision, not a fixed grant, so
    they are not surfaced here."""
    starting_feat_slug: str = ""
    """SRD 5.2: "A background gives your character a specified Origin feat."
    The canonical slug of that feat (``magic-initiate`` for the Acolyte),
    resolved from the "Background Feat" ItemGrant's compendium UUID
    (``Compendium.dnd5e.feats24.Item.phbftMagicInitia``). Empty for a
    background that grants none."""
    starting_equipment: list[dict[str, Any]] = Field(default_factory=list)
    """Foundry ``system.startingEquipment`` preserved structurally — the
    typed group/linked/focus/tool entries that describe the "Choose A or B"
    equipment bundle. Opaque per-entry dicts; consumers read them directly."""
    wealth: str = ""
    """Foundry ``system.wealth`` — the gp-alternative ("B" option). A string
    to match Foundry's own encoding (e.g. ``"50"``)."""
    provenance: Provenance
    review: ReviewState

    entry_kind: Literal["background"] = "background"
