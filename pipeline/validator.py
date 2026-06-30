"""
Validator: checks projected output against the requested field specs.

Rules:
  - Required fields must be present and non-null.
  - Type assertions are best-effort warnings, not hard failures.
  - on_missing="error" on a required missing field raises ValidationError.
  - All other issues are logged as warnings so the run degrades gracefully.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_TYPE_CHECKS = {
    "string":   str,
    "number":   (int, float),
    "boolean":  bool,
    "string[]": list,
}


class ValidationError(Exception):
    pass


def validate(output: dict, config: dict | None) -> dict:
    """
    Validate projected output against the config's field specs.
    Returns the output dict unchanged if valid; raises ValidationError on hard failures.
    """
    if not config or "fields" not in config:
        return output  # no spec → nothing to validate

    on_missing = config.get("on_missing", "null")

    for spec in config["fields"]:
        key      = spec["path"]
        required = spec.get("required", False)
        typ      = spec.get("type")

        value = output.get(key)

        if value is None:
            if required:
                msg = f"Validation failed: required field '{key}' is null/missing."
                if on_missing == "error":
                    raise ValidationError(msg)
                logger.warning(msg)
            continue

        if typ and typ in _TYPE_CHECKS:
            expected = _TYPE_CHECKS[typ]
            if not isinstance(value, expected):
                logger.warning(
                    "Type mismatch for '%s': expected %s, got %s.",
                    key, typ, type(value).__name__,
                )

    return output