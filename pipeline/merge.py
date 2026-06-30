"""
Merge stage: combines multiple normalized RawRecords into one CanonicalProfile.

Conflict-resolution policy:
  - Source priority (highest → lowest): linkedin > resume > github > csv > ats > notes
  - For scalar fields: highest-priority non-null value wins.
  - For list fields (emails, phones, skills): union across all sources, deduped.
  - All contributing sources are recorded in provenance.
"""

import hashlib
import logging
from collections import defaultdict
from typing import Any, Optional

from models.canonical import (
    CanonicalProfile, RawRecord, Skill, ProvenanceEntry, Links,
)
from pipeline.normalizers import years_from_experience

logger = logging.getLogger(__name__)

# Higher index = higher priority
_SOURCE_PRIORITY: dict[str, int] = {
    "notes": 0, "ats": 1, "csv": 2, "github": 3, "resume": 4, "linkedin": 5,
}


def merge(records: list[RawRecord]) -> CanonicalProfile:
    """Merge a list of normalized RawRecords into one CanonicalProfile."""
    if not records:
        raise ValueError("Cannot merge an empty list of records.")

    records = _sort_by_priority(records)
    provenance: list[ProvenanceEntry] = []

    full_name = _pick_scalar(records, "full_name", provenance)
    headline  = _pick_scalar(records, "headline",  provenance)
    location  = _pick_scalar(records, "location",  provenance)

    emails = _merge_list(records, "emails", provenance)
    phones = _merge_list(records, "phones", provenance)

    links = _merge_links(records, provenance)
    skills = _merge_skills(records, provenance)
    experience = _merge_experience(records, provenance)
    education  = _merge_education(records, provenance)

    years_exp = years_from_experience(experience)

    candidate_id = _make_id(emails, full_name)

    return CanonicalProfile(
        candidate_id=candidate_id,
        full_name=full_name,
        emails=emails,
        phones=phones,
        location=location,
        links=links,
        headline=headline,
        years_experience=years_exp,
        skills=skills,
        experience=experience,
        education=education,
        provenance=provenance,
        overall_confidence=0.0,  # filled in by the confidence stage
    )


# ------------------------------------------------------------------
# Field-level merge helpers
# ------------------------------------------------------------------

def _sort_by_priority(records: list[RawRecord]) -> list[RawRecord]:
    """Highest priority last so list[-1] gives the winner in scalar picks."""
    return sorted(records, key=lambda r: _SOURCE_PRIORITY.get(r.source, 0))


def _pick_scalar(
    records: list[RawRecord],
    field: str,
    provenance: list[ProvenanceEntry],
) -> Any:
    """
    Return the value from the highest-priority source that has this field set.
    Records are sorted lowest-to-highest priority, so we iterate in reverse.
    """
    for rec in reversed(records):
        value = getattr(rec, field, None)
        if value:
            provenance.append(ProvenanceEntry(field=field, source=rec.source, method="direct"))
            return value
    return None


def _merge_list(
    records: list[RawRecord],
    field: str,
    provenance: list[ProvenanceEntry],
) -> list:
    """Union of list fields across all sources, preserving insertion order."""
    seen: set = set()
    result = []
    for rec in reversed(records):  # highest priority contributes first
        for item in getattr(rec, field, []):
            key = item if isinstance(item, str) else str(item)
            if key not in seen:
                seen.add(key)
                result.append(item)
                provenance.append(ProvenanceEntry(field=field, source=rec.source, method="direct"))
    return result


def _merge_links(
    records: list[RawRecord],
    provenance: list[ProvenanceEntry],
) -> Optional[Links]:
    merged = Links()
    for rec in reversed(records):
        if not rec.links:
            continue
        if rec.links.linkedin and not merged.linkedin:
            merged.linkedin = rec.links.linkedin
            provenance.append(ProvenanceEntry(field="links.linkedin", source=rec.source, method="direct"))
        if rec.links.github and not merged.github:
            merged.github = rec.links.github
            provenance.append(ProvenanceEntry(field="links.github", source=rec.source, method="direct"))
        if rec.links.portfolio and not merged.portfolio:
            merged.portfolio = rec.links.portfolio
            provenance.append(ProvenanceEntry(field="links.portfolio", source=rec.source, method="direct"))
        for url in rec.links.other:
            if url not in merged.other:
                merged.other.append(url)

    has_any = any([merged.linkedin, merged.github, merged.portfolio, merged.other])
    return merged if has_any else None


def _merge_skills(
    records: list[RawRecord],
    provenance: list[ProvenanceEntry],
) -> list[Skill]:
    """
    Union of skills; confidence is proportional to number of sources that mention it.
    """
    skill_sources: dict[str, list[str]] = defaultdict(list)

    for rec in records:
        for skill_name in rec.skills:
            skill_sources[skill_name].append(rec.source)

    all_sources = len(records)
    skills: list[Skill] = []
    for name, sources in sorted(skill_sources.items()):
        confidence = min(1.0, len(set(sources)) / max(all_sources, 1))
        skills.append(Skill(name=name, confidence=round(confidence, 2), sources=list(set(sources))))
        provenance.append(ProvenanceEntry(field=f"skills[{name}]", source=sources[0], method="direct"))

    return sorted(skills, key=lambda s: s.confidence, reverse=True)


def _merge_experience(records: list[RawRecord], provenance: list[ProvenanceEntry]) -> list:
    """Union of experience entries; dedup by (company, title) pair."""
    seen: set[tuple] = set()
    result = []
    for rec in reversed(records):
        for exp in rec.experience:
            key = (exp.company or "", exp.title or "")
            if key not in seen:
                seen.add(key)
                result.append(exp)
                provenance.append(ProvenanceEntry(field="experience", source=rec.source, method="direct"))
    return result


def _merge_education(records: list[RawRecord], provenance: list[ProvenanceEntry]) -> list:
    """Union of education entries; dedup by institution."""
    seen: set[str] = set()
    result = []
    for rec in reversed(records):
        for edu in rec.education:
            key = edu.institution or edu.degree or ""
            if key not in seen:
                seen.add(key)
                result.append(edu)
                provenance.append(ProvenanceEntry(field="education", source=rec.source, method="direct"))
    return result


def _make_id(emails: list[str], full_name: Optional[str]) -> str:
    """Stable, deterministic ID: hash of primary email, or name as fallback."""
    seed = emails[0] if emails else (full_name or "unknown")
    return "cand_" + hashlib.sha256(seed.encode()).hexdigest()[:12]