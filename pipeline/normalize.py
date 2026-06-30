"""
Normalize stage: applies format normalization to every RawRecord in place.
Phones → E.164, dates → YYYY-MM, country → ISO-3166, skills → canonical names.
"""

import logging
from models.canonical import RawRecord, Location
from pipeline.normalizers import (
    normalize_phone, normalize_date, normalize_country,
    normalize_email, canonicalize_skill,
)

logger = logging.getLogger(__name__)


def normalize(record: RawRecord) -> RawRecord:
    """Return a new RawRecord with all fields normalized."""
    return RawRecord(
        source=record.source,
        full_name=_clean_name(record.full_name),
        emails=_normalize_list(record.emails, normalize_email),
        phones=_normalize_list(record.phones, normalize_phone),
        location=_normalize_location(record.location),
        links=record.links,
        headline=record.headline,
        skills=_normalize_skills(record.skills),
        experience=_normalize_experience(record.experience),
        education=record.education,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalize_list(values: list[str], fn) -> list[str]:
    """Apply fn to each item, drop Nones, deduplicate preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        normalized = fn(v)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip()
    # Drop names that look like usernames (no spaces, has digits)
    if " " not in name and any(c.isdigit() for c in name):
        logger.debug("Dropping username-like name: %r", name)
        return None
    return name if len(name) >= 2 else None


def _normalize_location(loc: Location | None) -> Location | None:
    if loc is None:
        return None
    return Location(
        city=loc.city,
        region=loc.region,
        country=normalize_country(loc.country) if loc.country else None,
    )


def _normalize_skills(skills: list[str]) -> list[str]:
    """Canonicalize known skills; drop unrecognised ones (unknown ≠ invented)."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in skills:
        canonical = canonicalize_skill(raw)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _normalize_experience(experiences: list) -> list:
    from models.canonical import Experience
    normalized = []
    for exp in experiences:
        normalized.append(Experience(
            company=exp.company,
            title=exp.title,
            start=normalize_date(exp.start) if exp.start else None,
            end=normalize_date(exp.end) if exp.end else None,
            summary=exp.summary,
        ))
    return normalized