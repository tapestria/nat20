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
| `attuned_items` | up to three items from `equipment` that require attunement | a magic bonus needs attunement when the item requires it |
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

Pass a value on `CombatInstance` to pin it: `hp_max`, `hp_current` and
`base_speed` when not `None`, and `ac` / `attack_bonus` whenever you assign them
(even the default). An omitted `attack_bonus` lets the engine compute each
weapon's to-hit bonus from the governing ability and weapon proficiency.

## What `derive_sheet` does not apply

Magic items' own passive effects (pass them as `active_effects`), languages,
tool proficiencies, the background's Origin feat, ability increases from feats
other than the Ability Score Improvement feat, level-20 capstone increases,
multiclass ability prerequisites, how many picks a choice allows, and penalties
for armor worn without training (`armor_training` is reported so a host can
apply them). See `BACKLOG.md` for each.

## Errors

`derive_sheet` and `build_party_member` raise `ValueError` with the reason for:
unknown slugs, a subclass below its level, malformed or repeated tokens,
adjustments outside their options or budget, unreached or reused ASI levels,
unmet feat prerequisites, picks outside every reached pool, Expertise without
proficiency, rolls that don't fit `hp_mode`, two suits of armor or two Shields, an
`ac_calc_mode` the worn equipment rules out, and attunement over three items or
to items that don't need it.
