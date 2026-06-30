"""
Structured source: Recruiter CSV export.
Expected columns: name, email, phone, current_company, title
Extra / missing columns are handled gracefully.
"""

import csv
import logging
from pathlib import Path

from models.canonical import RawRecord, Experience
from .base import BaseIngestor

logger = logging.getLogger(__name__)

# Map CSV column names → our internal field names.
# Add aliases here if different recruiters use different headers.
_COLUMN_MAP = {
    "name": "name", "full_name": "name", "candidate_name": "name",
    "email": "email", "email_address": "email",
    "phone": "phone", "phone_number": "phone", "mobile": "phone",
    "current_company": "company", "company": "company", "employer": "company",
    "title": "title", "job_title": "title", "position": "title",
    "location": "location", "city": "location",
}


class CSVIngestor(BaseIngestor):
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

    def extract(self) -> RawRecord:
        if not self.file_path.exists():
            logger.warning("CSV file not found: %s", self.file_path)
            return RawRecord(source="csv")

        try:
            records = self._parse_records()
            return records[0] if records else RawRecord(source="csv")
        except Exception as exc:
            logger.error("CSV ingestion failed (%s): %s", self.file_path, exc)
            return RawRecord(source="csv")

    def extract_records(self) -> list[RawRecord]:
        if not self.file_path.exists():
            logger.warning("CSV file not found: %s", self.file_path)
            return []

        try:
            return self._parse_records()
        except Exception as exc:
            logger.error("CSV ingestion failed (%s): %s", self.file_path, exc)
            return []

    def _parse_records(self) -> list[RawRecord]:
        with open(self.file_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        records: list[RawRecord] = []
        for row in rows:
            if row is None:
                continue

            data: dict[str, str] = {}
            for col, value in row.items():
                canonical_key = _COLUMN_MAP.get(col.strip().lower())
                if canonical_key and value and value.strip():
                    data[canonical_key] = value.strip()

            experience = []
            if data.get("company") or data.get("title"):
                experience.append(
                    Experience(company=data.get("company"), title=data.get("title"))
                )

            records.append(RawRecord(
                source="csv",
                full_name=data.get("name"),
                emails=[data["email"]] if data.get("email") else [],
                phones=[data["phone"]] if data.get("phone") else [],
                experience=experience,
            ))

        return records