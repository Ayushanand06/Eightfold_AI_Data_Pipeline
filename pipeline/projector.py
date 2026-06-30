"""
Projector: transforms a CanonicalProfile into a custom output shape
according to a runtime config dict.

Config schema:
{
  "fields": [
    {
      "path":      "primary_email",        # output key name
      "from":      "emails[0]",            # optional: canonical path to read from
      "type":      "string",               # for documentation / validation
      "required":  true,                   # affects on_missing behaviour
      "normalize": "E164"                  # optional post-projection normalizer
    },
    ...
  ],
  "include_provenance":  true,   # include provenance array in output?
  "include_confidence":  true,   # include overall_confidence in output?
  "on_missing":          "null"  # "null" | "omit" | "error"
}

If no config is supplied the full canonical profile is returned as-is.
"""

import logging
import re
from typing import Any

from models.canonical import CanonicalProfile
from pipeline.normalizers import normalize_phone

logger = logging.getLogger(__name__)


def project(profile: CanonicalProfile, config: dict | None) -> dict:
    """
    Apply the output config to a CanonicalProfile.
    Returns a plain dict ready for JSON serialisation.
    """
    if not config:
        return _full_output(profile)

    on_missing  = config.get("on_missing", "null")
    inc_prov    = config.get("include_provenance", True)
    inc_conf    = config.get("include_confidence", True)
    field_specs = config.get("fields", [])

    output: dict[str, Any] = {}

    for spec in field_specs:
        out_key   = spec["path"]
        src_path  = spec.get("from", spec["path"])   # default: same as output key
        required  = spec.get("required", False)
        normalizer = spec.get("normalize")

        value = _resolve_path(profile, src_path)
        value = _apply_normalizer(value, normalizer)

        if value is None:
            if required and on_missing == "error":
                raise ValueError(f"Required field '{out_key}' is missing from profile.")
            if on_missing == "omit":
                continue
            output[out_key] = None
        else:
            output[out_key] = value

    if inc_prov:
        output["provenance"] = [p.model_dump() for p in profile.provenance]
    if inc_conf:
        output["overall_confidence"] = profile.overall_confidence

    return output


# ------------------------------------------------------------------
# Path resolver
# ------------------------------------------------------------------

def _resolve_path(profile: CanonicalProfile, path: str) -> Any:
    """
    Resolve a dot-notation / index path against the profile.

    Supported forms:
      "full_name"           → profile.full_name
      "emails[0]"           → profile.emails[0]
      "skills[].name"       → [s.name for s in profile.skills]
      "experience[0].title" → profile.experience[0].title
    """
    # skills[].name  →  map over list
    array_map = re.fullmatch(r"(\w+)\[\]\.(\w+)", path)
    if array_map:
        field, attr = array_map.groups()
        items = getattr(profile, field, []) or []
        return [getattr(item, attr, None) for item in items if getattr(item, attr, None)]

    # field[N].attr  or  field[N]
    indexed = re.fullmatch(r"(\w+)\[(\d+)\](?:\.(\w+))?", path)
    if indexed:
        field, idx_str, attr = indexed.groups()
        items = getattr(profile, field, []) or []
        idx = int(idx_str)
        if idx >= len(items):
            return None
        item = items[idx]
        if attr:
            return getattr(item, attr, None)
        return item

    # Simple field or nested field (field.sub)
    parts = path.split(".")
    obj: Any = profile
    for part in parts:
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


# ------------------------------------------------------------------
# Post-projection normalizers
# ------------------------------------------------------------------

def _apply_normalizer(value: Any, normalizer: str | None) -> Any:
    if value is None or not normalizer:
        return value

    if normalizer == "E164":
        if isinstance(value, list):
            return [normalize_phone(v) or v for v in value]
        return normalize_phone(str(value)) or value

    if normalizer == "canonical":
        # For skills this means "already canonical" — just lowercase for output
        if isinstance(value, list):
            return [v.lower() if isinstance(v, str) else v for v in value]
        return value.lower() if isinstance(value, str) else value

    logger.warning("Unknown normalizer: %r", normalizer)
    return value


# ------------------------------------------------------------------
# Default (no-config) output
# ------------------------------------------------------------------

def _full_output(profile: CanonicalProfile) -> dict:
    return profile.model_dump()