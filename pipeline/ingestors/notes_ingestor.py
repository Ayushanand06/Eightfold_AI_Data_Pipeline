"""
Unstructured source: Recruiter notes (.txt free text).
Extracts emails, phones, and skills via regex.
Name and other rich fields are not reliably extractable from free text.
"""

import logging
import re
from pathlib import Path

from models.canonical import RawRecord
from pipeline.normalizers.normalizers import _SKILL_ALIASES, canonicalize_skill
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class RecruiterNotesIngestor(BaseIngestor):
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

    def extract(self) -> RawRecord:
        if not self.file_path.exists():
            logger.warning("Notes file not found: %s", self.file_path)
            return RawRecord(source="notes")

        try:
            text = self.file_path.read_text(encoding="utf-8")
            records = self.extract_records_from_text(text)
            return records[0] if records else RawRecord(source="notes")
        except Exception as exc:
            logger.error("Notes ingestion failed (%s): %s", self.file_path, exc)
            return RawRecord(source="notes")

    def extract_records(self) -> list[RawRecord]:
        if not self.file_path.exists():
            logger.warning("Notes file not found: %s", self.file_path)
            return []

        try:
            text = self.file_path.read_text(encoding="utf-8")
            return self.extract_records_from_text(text)
        except Exception as exc:
            logger.error("Notes ingestion failed (%s): %s", self.file_path, exc)
            return []

    @staticmethod
    def extract_records_from_text(text: str) -> list[RawRecord]:
        stripped = text.strip()
        if not stripped:
            return []

        sections = RecruiterNotesIngestor._split_sections(stripped)
        records: list[RawRecord] = []
        for section in sections:
            record = RecruiterNotesIngestor._parse_section(section)
            if any([record.full_name, record.emails, record.phones, record.skills]):
                records.append(record)

        if not records:
            return [RecruiterNotesIngestor._parse_section(stripped)]
        return records

    @staticmethod
    def _split_sections(text: str) -> list[str]:
        pattern = re.compile(r"(?im)^\s*candidate\s*[:\-]\s*", re.IGNORECASE)
        matches = list(pattern.finditer(text))
        if not matches:
            return [text]

        sections: list[str] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section = text[start:end].strip()
            if section:
                sections.append(section)
        return sections

    @staticmethod
    def _parse_section(text: str) -> RawRecord:
        emails = list({m.lower() for m in re.findall(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text
        )})
        phones = list({m.group() for m in re.finditer(
            r"(?:\+?\d[\d\s\-().]{7,}\d)", text
        )})

        skills = []
        text_lower = text.lower()
        for alias in _SKILL_ALIASES:
            if re.search(rf"\b{re.escape(alias)}\b", text_lower):
                canonical = canonicalize_skill(alias)
                if canonical and canonical not in skills:
                    skills.append(canonical)

        full_name = None
        candidate_match = re.search(r"candidate\s*[:\-]\s*(.+)", text, re.IGNORECASE)
        if candidate_match:
            full_name = candidate_match.group(1).strip()
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if re.search(r"\b(contact|skills|experience|summary|notes|email|phone)\b", line, re.I):
                    continue
                name_match = re.match(r"^([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)+)$", line)
                if name_match:
                    full_name = line
                    break

        return RawRecord(
            source="notes",
            full_name=full_name,
            emails=emails,
            phones=phones,
            skills=skills,
        )