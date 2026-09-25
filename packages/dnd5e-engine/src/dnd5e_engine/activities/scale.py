"""Pure ScaleValue (``@scale.*``) resolution against owner advancement tables.

Foundry roll-data carries level-scaled magnitudes as ``@scale.<owner>.<key>``
tokens (and full-suffix variants ``@scale.<owner>.<key>.<sub>``). Each resolves
against a ScaleValue advancement entry on the OWNER doc — a class, subclass,
species, or a FEATURE granted by one of those. The owner
doc carries a sparse ``configuration.scale`` keyed by level; the value at a
given character level is the entry at the highest level <= it.

Determined empirically (SPIKE, over ``canonical/features/*.json``;
extended to feature-owned scales:

* Owner space = class | subclass | species | feature (``get_class`` /
  ``get_subclass`` / ``get_species`` / ``get_feature``, in that order). Not
  just classes — e.g. the Land druid subclass (``@scale.land.lands-aid``),
  Dragonborn species (``@scale.dragonborn.breath``), and a FEATURE granted by
  a class/subclass/species (Channel Divinity's own Divine Spark die count,
  ``@scale.channel-divinity-cleric.spark`` — the granting class doc carries no
  such ScaleValue itself; ``build_scale_values`` walks the caster's granted
  feature slugs, via the same ``granted_feature_slugs`` helper the
  orchestrator's USE_FEATURE repertoire gate uses, to reach it).
* Key match: ``configuration.identifier == key`` OR ``slugify(title) == key``.
  Rogue Sneak Attack has an EMPTY identifier and is reached only via the title
  slug.
* ``configuration.type`` drives the value shape:
  - ``number`` / ``distance`` -> entry ``{value}`` (int).
  - ``dice`` -> entry ``{number, faces}``; bare -> ``f"{number}d{faces}"``
    (or ``f"d{faces}"`` when ``number is None``, e.g. Monk Martial Arts Die);
    suffix ``number`` -> the int count; suffix ``die`` -> ``f"d{faces}"``.
* Unresolvable owner/key -> ``None`` (caller logs + defers).

This module is PURE w.r.t. combat state: it takes a loaded loader (or owner doc)
and returns plain ints/strings. The orchestrator/build-party seam — which has
loader access — pre-resolves the caster's scales into the frozen
``ActivityResolutionContext`` carrier; the formula resolver never touches a
loader.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from dnd5e_srd_data.schema.advancement import AdvancementType

from dnd5e_engine.rules.character import leveled_feature_levels

if TYPE_CHECKING:
    from dnd5e_srd_data.loader import AssetLoader
    from dnd5e_srd_data.schema.class_ import Class, Subclass
    from dnd5e_srd_data.schema.species import Species


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _owner_doc(identifier: str, loader: AssetLoader) -> Any | None:
    """Resolve an owner slug against class -> subclass -> species -> FEATURE
    (first hit). The feature fallback reaches a feature-owned
    ``@scale.<feature-slug>.<key>`` token (e.g. Channel Divinity's Divine
    Spark die count) whose ScaleValue advancement lives on the granting
    feature's OWN doc, not its class/subclass/species."""
    return (
        loader.get_class(identifier)
        or loader.get_subclass(identifier)
        or loader.get_species(identifier)
        or loader.get_feature(identifier)
    )


def _scale_config(doc: Any, key: str) -> dict[str, Any] | None:
    """Find the ScaleValue advancement config on ``doc`` matching ``key``."""
    for entry in getattr(doc, "advancement", None) or []:
        if entry.type != AdvancementType.SCALE_VALUE:
            continue
        config = entry.configuration or {}
        if config.get("scale") is None:
            continue
        if config.get("identifier") == key or _slugify(entry.title) == key:
            return config
    return None


def _entry_at_level(scale: dict[str, Any], level: int) -> dict[str, Any] | None:
    """Pick the scale entry at the highest defined level <= ``level``."""
    eligible = [int(lvl) for lvl in scale if int(lvl) <= level]
    if not eligible:
        return None
    entry: dict[str, Any] = scale[str(max(eligible))]
    return entry


def _project(config: dict[str, Any], entry: dict[str, Any], suffix: str | None) -> int | str:
    """Project a scale entry to the value selected by ``suffix`` + scale type."""
    scale_type = config.get("type")
    if scale_type == "dice":
        number = entry.get("number")
        faces = entry.get("faces")
        if suffix == "number":
            return int(number) if number is not None else 0
        if suffix == "die":
            return f"d{faces}"
        # bare dice token -> full expression (count omitted when number is None)
        return f"{number}d{faces}" if number is not None else f"d{faces}"
    # number / distance scales carry a plain {value}
    return int(entry["value"])


def resolve_scale_value(
    identifier: str,
    key: str,
    *,
    level: int,
    loader: AssetLoader,
    suffix: str | None = None,
) -> int | str | None:
    """Resolve ``@scale.<identifier>.<key>[.<suffix>]`` at ``level``.

    Returns an int (number/distance scales, dice ``.number`` count), a dice-expr
    string (dice scales, bare or ``.die``), or ``None`` when the owner / key /
    level has no matching ScaleValue entry.
    """
    doc = _owner_doc(identifier, loader)
    if doc is None:
        return None
    config = _scale_config(doc, key)
    if config is None:
        return None
    entry = _entry_at_level(config["scale"], level)
    if entry is None:
        return None
    return _project(config, entry, suffix)


def _walk_owner_scales(slug: str, doc: Any, level: int, out: dict[str, int | str]) -> None:
    """Fold every ScaleValue advancement entry on ``doc`` into ``out``, keyed
    ``"<slug>.<key>[.<suffix>]"``. Shared by the class/subclass/species walk
    and the feature walk below — same projection, different owner slug."""
    for entry in getattr(doc, "advancement", None) or []:
        if entry.type != AdvancementType.SCALE_VALUE:
            continue
        config = entry.configuration or {}
        scale = config.get("scale")
        if scale is None:
            continue
        scaled = _entry_at_level(scale, level)
        if scaled is None:
            continue
        key = config.get("identifier") or _slugify(entry.title)
        base = f"{slug}.{key}"
        out[base] = _project(config, scaled, None)
        if config.get("type") == "dice":
            out[f"{base}.number"] = _project(config, scaled, "number")
            out[f"{base}.die"] = _project(config, scaled, "die")


def feature_owners(
    *,
    classes: Mapping[str, int],
    subclass_slug: str | None,
    species_slug: str | None,
    level: int,
    loader: AssetLoader,
) -> list[tuple[str, Class | Subclass | Species, int]]:
    """Every document that grants a character features, with the level it is
    read at. SRD 5.2 Multiclassing: "When you gain a new level in a class, you
    get its features for that level." Each class reads at its own level, the
    subclass at its class's level (``level`` when that class isn't listed), the
    species at character ``level``. Unknown slugs are skipped."""
    owners: list[tuple[str, Class | Subclass | Species, int]] = []
    for slug, class_level in classes.items():
        cls = loader.get_class(slug)
        if cls is not None:
            owners.append((slug, cls, class_level))
    if subclass_slug:
        subclass = loader.get_subclass(subclass_slug)
        if subclass is not None:
            owners.append((subclass_slug, subclass, classes.get(subclass.class_identifier, level)))
    if species_slug:
        species = loader.get_species(species_slug)
        if species is not None:
            owners.append((species_slug, species, level))
    return owners


def build_scale_values(
    *,
    class_slug: str | None,
    subclass_slug: str | None,
    species_slug: str | None,
    level: int,
    loader: AssetLoader,
    classes: Mapping[str, int] | None = None,
) -> dict[str, int | str]:
    """Pre-resolve every ScaleValue on the caster's owner docs at ``level``.

    Returns a flat ``{full-suffix: value}`` map keyed by the dotted token suffix
    (``"barbarian.rage-damage"``, ``"rogue.sneak-attack"``,
    ``"rogue.sneak-attack.number"``, ``"channel-divinity-cleric.spark"``, ...)
    for direct lookup by the ``@scale.*`` formula branch. Dice scales
    contribute the bare expr, the ``.number`` count, and the ``.die`` variants
    so any full-suffix token the activity references resolves. Unresolvable
    owner slugs contribute nothing.

    a FEATURE-OWNED scale (e.g. Channel Divinity's Divine Spark die
    count) lives on the granting feature's OWN doc, not its granting class/
    subclass/species. After walking the owner docs directly, also walk every
    feature slug they GRANT at/below their own level (``leveled_feature_levels``,
    the same helper the orchestrator's USE_FEATURE repertoire gate uses) and
    fold each granted feature's ScaleValue table too.

    ``classes`` — per-class levels of a multiclass character; each owner, and
    each feature it grants, reads at its own level. ``None`` reads
    ``class_slug`` at ``level``, as before.

    This is the pure half of the orchestrator/build-party seam: the loader call
    lives here, the result is plain data passed into the frozen context.
    """
    class_levels = dict(classes) if classes else ({class_slug: level} if class_slug else {})
    owners = feature_owners(
        classes=class_levels,
        subclass_slug=subclass_slug,
        species_slug=species_slug,
        level=level,
        loader=loader,
    )
    out: dict[str, int | str] = {}
    for slug, doc, owner_level in owners:
        _walk_owner_scales(slug, doc, owner_level, out)
    granted = leveled_feature_levels([(doc, owner_level) for _, doc, owner_level in owners])
    for feature_slug, feature_level in granted.items():
        feature_doc = loader.get_feature(feature_slug)
        if feature_doc is not None:
            _walk_owner_scales(feature_slug, feature_doc, feature_level, out)
    return out
