"""
Canonical data models for the candidate profile pipeline.
All pipeline stages operate on these types.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator
import re


class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2


class Links(BaseModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = []


class Skill(BaseModel):
    name: str                  # canonical skill name
    confidence: float          # 0.0 – 1.0
    sources: list[str] = []   # which sources mentioned it


class Experience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None   # YYYY-MM
    end: Optional[str] = None     # YYYY-MM or None = present
    summary: Optional[str] = None


class Education(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


class ProvenanceEntry(BaseModel):
    field: str
    source: str    # e.g. "csv", "github", "resume"
    method: str    # e.g. "direct", "normalized", "inferred"


class RawRecord(BaseModel):
    """Intermediate representation produced by each ingestor before merging."""
    source: str
    full_name: Optional[str] = None
    emails: list[str] = []
    phones: list[str] = []
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    skills: list[str] = []         # raw skill strings; canonicalized in normalize stage
    experience: list[Experience] = []
    education: list[Education] = []


class CanonicalProfile(BaseModel):
    """The single clean profile emitted by the pipeline."""
    candidate_id: str
    full_name: Optional[str] = None
    emails: list[str] = []
    phones: list[str] = []
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[Skill] = []
    experience: list[Experience] = []
    education: list[Education] = []
    provenance: list[ProvenanceEntry] = []
    overall_confidence: float = 0.0

    @field_validator("overall_confidence")
    @classmethod
    def clamp(cls, v: float) -> float:
        return round(max(0.0, min(1.0, v)), 3)