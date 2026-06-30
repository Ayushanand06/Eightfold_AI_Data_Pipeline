"""
Confidence stage: computes overall_confidence for a CanonicalProfile.

Score = weighted average of three components:
  1. fields_populated  — weighted field fill rate (high-identity fields matter more)
  2. source_agreement  — do multiple sources agree on key fields?
  3. source_quality    — how trustworthy are the sources that contributed?

All weights and importance values are in one place so they're easy to tune.
"""

from models.canonical import CanonicalProfile, RawRecord

# -----------------------------------------------------------------------
# Tunable parameters — edit these to change scoring behaviour
# -----------------------------------------------------------------------

# How much each component contributes to the final score (must sum to 1.0)
COMPONENT_WEIGHTS = {
    "fields_populated": 0.30,
    "source_agreement":  0.40,
    "source_quality":    0.30,
}

# Importance of each canonical field; high-identity fields score more when present.
FIELD_IMPORTANCE: dict[str, float] = {
    "emails":           1.5,
    "full_name":        1.4,
    "phones":           1.3,
    "experience":       1.0,
    "skills":           0.9,
    "education":        0.9,
    "location":         0.8,
    "headline":         0.7,
    "links":            0.6,
    "years_experience": 0.5,
}

# How much to trust each source (0.0 – 1.0)
SOURCE_QUALITY: dict[str, float] = {
    "linkedin": 1.0,
    "resume":   0.9,
    "github":   0.8,
    "csv":      0.7,
    "ats":      0.6,
    "notes":    0.4,
}


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def compute_confidence(profile: CanonicalProfile, raw_records: list[RawRecord]) -> float:
    """
    Return a confidence score in [0.0, 1.0].
    The profile's overall_confidence field is NOT mutated here — the caller
    (pipeline.py) assigns the return value.
    """
    f = _fields_score(profile)
    a = _agreement_score(profile, raw_records)
    q = _quality_score(raw_records)

    score = (
        f * COMPONENT_WEIGHTS["fields_populated"] +
        a * COMPONENT_WEIGHTS["source_agreement"] +
        q * COMPONENT_WEIGHTS["source_quality"]
    )
    return round(min(1.0, max(0.0, score)), 3)


# -----------------------------------------------------------------------
# Component scorers
# -----------------------------------------------------------------------

def _fields_score(profile: CanonicalProfile) -> float:
    """Weighted fraction of important fields that are populated."""
    total = sum(FIELD_IMPORTANCE.values())
    earned = 0.0
    for field, importance in FIELD_IMPORTANCE.items():
        value = getattr(profile, field, None)
        if value:  # non-null, non-empty
            earned += importance
    return earned / total


def _agreement_score(profile: CanonicalProfile, records: list[RawRecord]) -> float:
    """
    For each identity field, check whether sources agree.
    Agreement on high-importance fields (email, name) carries more weight.

    We only measure agreement when ≥2 sources provide a value for that field.
    """
    if len(records) < 2:
        return 0.8  # single-source: can't measure agreement, give benefit of doubt

    checks = {
        "emails":    ([r.emails[0] for r in records if r.emails], 1.5),
        "full_name": ([r.full_name for r in records if r.full_name], 1.4),
        "phones":    ([r.phones[0] for r in records if r.phones], 1.3),
    }

    total_weight = 0.0
    agreed_weight = 0.0

    for _field, (values, importance) in checks.items():
        if len(values) < 2:
            continue
        from collections import Counter
        most_common_count = Counter(values).most_common(1)[0][1]
        agreement_ratio = most_common_count / len(values)
        total_weight += importance
        agreed_weight += importance * agreement_ratio

    if total_weight == 0:
        return 0.5  # no overlap at all

    return agreed_weight / total_weight


def _quality_score(records: list[RawRecord]) -> float:
    """Max quality score among contributing sources."""
    scores = [SOURCE_QUALITY.get(r.source, 0.5) for r in records]
    return max(scores) if scores else 0.0