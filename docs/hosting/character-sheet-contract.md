# Character-sheet contract

`derive_sheet(spec, *, loader)` turns a `CharacterBuildSpec` into a `DerivedSheet`:
every number SRD 5.2 derives from a character's choices. `build_party_member`
calls it and fills each `PartyMemberSpec` value your `CombatInstance` leaves
unset. This page lists what a host stores so the engine can re-derive a sheet at
any time, and the rules the derivation applies.

## What to persist

| Field | Store | Why it matters |
|---|---|---|
| `species_slug` | the species | speed, senses, resistances, species features and choices |
| `classes` | `{class_slug: level}` **in the order the classes were first taken** | the first key alone gets its Hit Die maximum at level 1 and its initial-class proficiencies |
| `subclass_slug` | once the class reaches its subclass level (3) | earlier is rejected |
| `background_slug` | the background | its two skill proficiencies; the options for the `background:` adjustment |
| `ability_scores` | the scores **before** the increases listed in `selected_choices` | a host that stores final scores lists no `background:` / `asi:` tokens |
| `ability_score_method` | optional: `standard_array` or `point_buy` | the base scores are checked against it |
| `selected_choices` | one token per choice (below) | skills, Expertise, adjustments, ASIs, feats, feature picks |
| `equipment` | carried items; armor and Shields listed here are **worn** | one suit of armor and one Shield at most |
| `attuned_items` | up to the attunement limit (three, or four with the Thief's Use Magic Device) — items from `equipment` that require attunement | a magic bonus needs attunement when the item requires it |
| `hp_mode`, `hp_rolls` | `fixed` (default), or `rolled` with the recorded Hit Die results per class | the first class records `level - 1` results, every other class `level` |
| `ac_calc_mode` | leave unset for the best eligible mode; set it to force one | Unarmored Defense, Draconic Resilience, Mage Armor |

## Choice tokens

| Token | Meaning |
|---|---|
| `skill:athletics` | a chosen skill proficiency (long-form skill slug) |
| `expertise:stealth` | an Expertise pick; the character must be proficient |
| `background:strength+2,constitution+1` | the background's +2/+1 or +1/+1/+1 |
| `asi:fighter:4:strength+2` | the Ability Score Improvement feat at Fighter level 4 (+2, or +1/+1) |
| `feat:fighter:6:grappler` | another feat taken at an Ability Score Improvement level |
| `defense` | a pick from a feature-choice pool: Fighting Style, Eldritch Invocation, Metamagic, Divine or Primal Order, a species choice |

Abilities are long names or three-letter codes. Increases stop at 20.

## Explicit values win

`CombatInstance.hp_max`, `hp_current`, `ac`, `attack_bonus` and `base_speed`
all default to `None`, which means "derive it" — pass any other value to pin
it, and that pin survives a `CombatInstance(**inst.model_dump())` round-trip.
An omitted `attack_bonus` lets the engine compute each weapon's to-hit bonus
from the governing ability and weapon proficiency. An empty or omitted
`spell_slots` / `pact_slots` on `CombatInstance` likewise means "derive the
multiclass slot table"; pass a non-empty map to pin one.

## What reaches combat

`build_party_member` also forwards the build's `feats` and `classes` to
`PartyMemberSpec`. The four SRD 5.2 Fighting Style feats therefore apply in
combat (Defense is already in the derived `ac`, and only while Light, Medium
or Heavy armor is worn), and each class's features and scale values are read
at that class's own level.

## What `derive_sheet` does not apply

Magic items' own passive effects (pass them as `active_effects`), languages,
tool proficiencies, the background's Origin feat, ability increases from feats
other than the Ability Score Improvement feat, level-20 capstone increases,
multiclass ability prerequisites, how many picks a choice allows, and penalties
for armor worn without training (`armor_training` is reported so a host can
apply them). Feature-choice picks other than the Fighting Styles (Eldritch
Invocations, Metamagic, Blessed Warrior, …) are recorded on
`DerivedSheet.features` / `feats`, but their effects are not applied and they
never reach the in-combat feature gate. Fast Movement still adds its speed
bonus while wearing Heavy armor (SRD 5.2 requires none). A variant crafting
template such as `shield-1-2-or-3` derives AC from the dataset's placeholder
base value, not the real item. A class granted specific weapon slugs rather
than a category (Rogue, Monk) gets no Proficiency Bonus with a magic variant
of one of them, such as a Scimitar of Speed — magic weapons are not yet
matched to their base weapon. See `BACKLOG.md` for each.

## Errors

`derive_sheet` and `build_party_member` raise `ValueError` with the reason for:
unknown slugs, a subclass below its level, malformed or repeated tokens,
adjustments outside their options or budget, unreached or reused ASI levels,
unmet feat prerequisites, picks outside every reached pool, Expertise without
proficiency, rolls that don't fit `hp_mode`, two suits of armor or two Shields, an
`ac_calc_mode` the worn equipment rules out, and attunement over the limit
(three, or four with the Thief's Use Magic Device) or to items that don't
need it.
