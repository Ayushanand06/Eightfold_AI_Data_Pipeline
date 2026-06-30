"""
Structured source: ATS JSON blob.
Field names do NOT match our canonical schema — mapping is done here.
"""

import json
import logging
from pathlib import Path

from models.canonical import RawRecord, Experience, Education, Location
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# ATS field → our field.  Extend as needed for different ATS vendors.
_FIELD_MAP = {
    # Identity
    "candidate_name": "full_name", "applicant_name": "full_name",
    "emp_email": "email", "applicant_email": "email",
    "emp_phone": "phone", "applicant_phone": "phone",
    # Job
    "emp_title": "title", "current_position": "title",
    "org": "company", "current_org": "company",
    # Location
    "city": "city", "state": "region", "country": "country",
    # Skills
    "skill_tags": "skills", "competencies": "skills",
    # Headline / summary
    "summary": "headline", "profile_summary": "headline",
}


class ATSJsonIngestor(BaseIngestor):
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

    def extract(self) -> RawRecord:
        if not self.file_path.exists():
            logger.warning("ATS JSON file not found: %s", self.file_path)
            return RawRecord(source="ats")

        try:
            records = self._parse_records()
            return records[0] if records else RawRecord(source="ats")
        except Exception as exc:
            logger.error("ATS JSON ingestion failed (%s): %s", self.file_path, exc)
            return RawRecord(source="ats")

    def extract_records(self) -> list[RawRecord]:
        if not self.file_path.exists():
            logger.warning("ATS JSON file not found: %s", self.file_path)
            return []

        try:
            return self._parse_records()
        except Exception as exc:
            logger.error("ATS JSON ingestion failed (%s): %s", self.file_path, exc)
            return []

    def _parse_records(self) -> list[RawRecord]:
        raw = json.loads(self.file_path.read_text(encoding="utf-8"))

        candidates = []
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
            candidates = raw["candidates"]
        elif isinstance(raw, dict) and isinstance(raw.get("candidate"), dict):
            candidates = [raw["candidate"]]
        elif isinstance(raw, dict):
            candidates = [raw]

        records: list[RawRecord] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            records.append(self._parse_object(item))

        return records

    def _parse_object(self, raw: dict) -> RawRecord:
        data: dict = {}
        for ats_key, value in raw.items():
            our_key = _FIELD_MAP.get(ats_key.lower())
            if our_key and value not in (None, "", [], {}):
                data[our_key] = value

        location = None
        if any(k in data for k in ("city", "region", "country")):
            location = Location(
                city=data.get("city"),
                region=data.get("region"),
                country=data.get("country"),
            )

        experience = []
        if data.get("company") or data.get("title"):
            experience.append(Experience(company=data.get("company"), title=data.get("title")))

        # ATS may list previous roles under "work_history"
        for role in raw.get("work_history", []):
            experience.append(Experience(
                company=role.get("org") or role.get("company"),
                title=role.get("emp_title") or role.get("title"),
                start=role.get("start_date"),
                end=role.get("end_date"),
                summary=role.get("description"),
            ))

        education = []
        for edu in raw.get("education_history", []):
            education.append(Education(
                institution=edu.get("institution") or edu.get("school"),
                degree=edu.get("degree"),
                field=edu.get("field_of_study") or edu.get("major"),
                end_year=edu.get("graduation_year"),
            ))

        skills_raw = data.get("skills", [])
        if isinstance(skills_raw, str):
            skills_raw = [s.strip() for s in skills_raw.split(",")]

        return RawRecord(
            source="ats",
            full_name=data.get("full_name"),
            emails=[data["email"]] if data.get("email") else [],
            phones=[data["phone"]] if data.get("phone") else [],
            location=location,
            headline=data.get("headline"),
            skills=skills_raw,
            experience=experience,
            education=education,
        )