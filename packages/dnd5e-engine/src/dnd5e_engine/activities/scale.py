"""Pure ScaleValue (``@scale.*``) resolution against owner advancement tables.

Foundry roll-data carries level-scaled magnitudes as ``@scale.<owner>.<key>``
tokens (and full-suffix variants ``@scale.<owner>.<key>.<sub>``). Each resolves
against a ScaleValue advancement entry on the OWNER doc — a class, subclass, or
species. The owner doc carries a sparse ``configuration.scale`` keyed by level;
the value at a given character level is the entry at the highest level <= it.

Determined empirically (SPIKE, Task 2) over ``canonical/features/*.json``:

* Owner space = class | subclass | species (``get_class`` / ``get_subclass`` /
  ``get_species``, in that order). Not just classes — e.g. the Land druid
  subclass (``@scale.land.lands-aid``) and Dragonborn species
  (``@scale.dragonborn.breath``).
* Key match: ``configuration.identifier == key`` OR ``slugify(title) == key``.
  Rogue Sneak Attack has an EMPTY identifier and is reached only via the title
  slug.
* ``configuration.type`` drives the value shape:
  - ``number`` / ``distance`` -> entry ``{value}`` (int).
  - ``dice`` -> entry ``{number, faces}``; bare -> ``f"{number}d{faces}"``
    (or ``f"d{faces}"`` when ``number is None``, e.g. Monk Martial Arts Die);
    suffix ``number`` -> the int count; suffix ``die`` -> ``f"d{faces}"``.
* Unresolvable owner/key (e.g. the feature-specific
  ``@scale.channel-divinity-cleric.spark``) -> ``None`` (caller logs + defers).

This module is PURE w.r.t. combat state: it takes a loaded loader (or owner doc)
and returns plain ints/strings. The orchestrator/build-party seam — which has
loader access — pre-resolves the caster's scales into the frozen
``ActivityResolutionContext`` carrier; the formula resolver never touches a
loader.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from dnd5e_srd_data.schema.advancement import AdvancementType

if TYPE_CHECKING:
    from dnd5e_srd_data.loader import AssetLoader


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _owner_doc(identifier: str, loader: AssetLoader) -> Any | None:
    """Resolve an owner slug against class -> subclass -> species (first hit)."""
    return (
        loader.get_class(identifier)
        or loader.get_subclass(identifier)
        or loader.get_species(identifier)
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


def build_scale_values(
    *,
    class_slug: str | None,
    subclass_slug: str | None,
    species_slug: str | None,
    level: int,
    loader: AssetLoader,
) -> dict[str, int | str]:
    """Pre-resolve every ScaleValue on the caster's owner docs at ``level``.

    Returns a flat ``{full-suffix: value}`` map keyed by the dotted token suffix
    (``"barbarian.rage-damage"``, ``"rogue.sneak-attack"``,
    ``"rogue.sneak-attack.number"``, ...) for direct lookup by the ``@scale.*``
    formula branch. Dice scales contribute the bare expr, the ``.number`` count,
    and the ``.die`` variants so any full-suffix token the activity references
    resolves. Unresolvable owner slugs contribute nothing.

    This is the pure half of the orchestrator/build-party seam: the loader call
    lives here, the result is plain data passed into the frozen context.
    """
    out: dict[str, int | str] = {}
    for slug in (class_slug, subclass_slug, species_slug):
        if slug is None:
            continue
        doc = _owner_doc(slug, loader)
        if doc is None:
            continue
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
    return out
