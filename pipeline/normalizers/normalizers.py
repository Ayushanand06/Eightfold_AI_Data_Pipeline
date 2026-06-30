"""
Normalizers: pure functions that convert raw strings to canonical formats.
Each function returns None on failure — never raises, never invents.
"""

from __future__ import annotations
import re
import logging
from datetime import datetime
from typing import Optional

import phonenumbers
import pycountry
import dateparser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill canonicalization table
# Keys are lowercased aliases; values are the canonical display name.
# Extend this dict to cover more aliases without touching any other code.
# ---------------------------------------------------------------------------
_SKILL_ALIASES: dict[str, str] = {
    # JavaScript
    "js": "JavaScript", "javascript": "JavaScript", "es6": "JavaScript",
    # TypeScript
    "ts": "TypeScript", "typescript": "TypeScript",
    # Python
    "python": "Python", "python3": "Python", "py": "Python",
    # Java
    "java": "Java",
    # C / C++
    "c++": "C++", "cpp": "C++", "c": "C",
    # Go
    "go": "Go", "golang": "Go",
    # Rust
    "rust": "Rust",
    # React
    "react": "React", "reactjs": "React", "react.js": "React",
    # Node
    "node": "Node.js", "nodejs": "Node.js", "node.js": "Node.js",
    # SQL / databases
    "sql": "SQL", "mysql": "MySQL", "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL", "mongodb": "MongoDB", "mongo": "MongoDB",
    "redis": "Redis",
    # Cloud
    "aws": "AWS", "amazon web services": "AWS",
    "gcp": "GCP", "google cloud": "GCP",
    "azure": "Azure", "microsoft azure": "Azure",
    # ML / AI
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "deep learning": "Deep Learning", "dl": "Deep Learning",
    "nlp": "NLP", "natural language processing": "NLP",
    "llm": "LLMs", "large language models": "LLMs",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow",
    # DevOps
    "docker": "Docker", "kubernetes": "Kubernetes", "k8s": "Kubernetes",
    "ci/cd": "CI/CD", "cicd": "CI/CD",
    "git": "Git", "github": "Git",
    # Other
    "rest": "REST APIs", "graphql": "GraphQL",
    "html": "HTML", "css": "CSS",
}


def normalize_phone(raw: str, default_region: str = "IN") -> Optional[str]:
    """Return E.164 format or None if unparseable."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    logger.debug("Could not normalize phone: %r", raw)
    return None


def normalize_date(raw: str) -> Optional[str]:
    """Return MM-YYYY string or None if unparseable."""
    if not raw or not raw.strip():
        return None
    # Fast path: already in MM-YYYY or YYYY
    if re.fullmatch(r"\d{2}-\d{4}", raw.strip()):
        return raw.strip()
    if re.fullmatch(r"\d{4}", raw.strip()):
        return f"01-{raw.strip()}"
    parsed = dateparser.parse(raw, settings={"PREFER_DAY_OF_MONTH": "first"})
    if parsed:
        return parsed.strftime("%m-%Y")
    logger.debug("Could not normalize date: %r", raw)
    return None


def normalize_country(raw: str) -> Optional[str]:
    """Return ISO-3166 alpha-2 code or None."""
    if not raw:
        return None
    raw = raw.strip()
    # Already a 2-letter code?
    if re.fullmatch(r"[A-Za-z]{2}", raw):
        match = pycountry.countries.get(alpha_2=raw.upper())
        return match.alpha_2 if match else None
    # Try lookup by name
    try:
        results = pycountry.countries.search_fuzzy(raw)
        return results[0].alpha_2 if results else None
    except LookupError:
        return None


def canonicalize_skill(raw: str) -> Optional[str]:
    """Map a raw skill string to its canonical name, or None if unrecognised."""
    return _SKILL_ALIASES.get(raw.strip().lower())


def normalize_email(raw: str) -> Optional[str]:
    """Lowercase and basic-validate an email address."""
    clean = raw.strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean):
        return clean
    return None


def years_from_experience(experiences: list) -> Optional[float]:
    """
    Compute total years of experience from a list of Experience objects.
    Overlapping date ranges are not deduplicated — a simple sum is used,
    which is the industry-standard approximation for resume parsing.
    """
    total_months = 0
    now = datetime.now()

    for exp in experiences:
        start = dateparser.parse(exp.start) if exp.start else None
        if exp.end:
            end = dateparser.parse(exp.end)
        else:
            end = now  # present

        if start and end and end >= start:
            total_months += (end.year - start.year) * 12 + (end.month - start.month)

    return round(total_months / 12, 1) if total_months > 0 else None