"""
Unstructured source: Resume file (PDF or DOCX).
Text is extracted then parsed with heuristics + regex.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from models.canonical import RawRecord, Experience, Education
from pipeline.normalizers.normalizers import canonicalize_skill
from .base import BaseIngestor

logger = logging.getLogger(__name__)


class ResumeIngestor(BaseIngestor):
    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)

    def extract(self) -> RawRecord:
        if not self.file_path.exists():
            logger.warning("Resume file not found: %s", self.file_path)
            return RawRecord(source="resume")

        try:
            text = self._extract_text()
            return self._parse(text)
        except Exception as exc:
            logger.error("Resume ingestion failed (%s): %s", self.file_path, exc)
            return RawRecord(source="resume")

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def _extract_text(self) -> str:
        suffix = self.file_path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf()
        if suffix in (".docx", ".doc"):
            return self._read_docx()
        if suffix in (".txt", ".md"):
            return self.file_path.read_text(encoding="utf-8")
        raise ValueError(f"Unsupported resume format: {suffix}")

    def _read_pdf(self) -> str:
        import fitz  # PyMuPDF
        doc = fitz.open(str(self.file_path))
        return "\n".join(page.get_text() for page in doc)

    def _read_docx(self) -> str:
        from docx import Document
        doc = Document(str(self.file_path))
        return "\n".join(p.text for p in doc.paragraphs)

    # ------------------------------------------------------------------
    # Parsing heuristics
    # ------------------------------------------------------------------

    def _parse(self, text: str) -> RawRecord:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return RawRecord(
            source="resume",
            full_name=self._find_name(lines),
            emails=self._find_emails(text),
            phones=self._find_phones(text),
            headline=self._find_headline(lines),
            skills=self._find_skills(text),
            experience=self._find_experience(text),
            education=self._find_education(text),
        )

    @staticmethod
    def _find_name(lines: list[str]) -> Optional[str]:
        """Prefer the first short line that looks like a person name."""
        for line in lines[:8]:
            if not line:
                continue
            if line.lower().startswith(("education", "experience", "skills", "projects", "achievements")):
                continue
            if re.fullmatch(r"[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)+", line.strip()):
                return line.strip()
        for line in lines[:5]:
            if 2 <= len(line.split()) <= 5 and line[0].isupper() and "|" not in line and "@" not in line:
                return line.strip()
        return None

    @staticmethod
    def _find_emails(text: str) -> list[str]:
        return list({m.lower() for m in re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)})

    @staticmethod
    def _find_phones(text: str) -> list[str]:
        return list({m.group() for m in re.finditer(
            r"(?:\+?\d[\d\s\-().]{7,}\d)", text
        )})

    @staticmethod
    def _find_headline(lines: list[str]) -> Optional[str]:
        """Use the first short line after the name that is not contact info or a section heading."""
        for line in lines[1:8]:
            if not line or line.lower() in {"education", "experience", "projects", "technical skills", "achievements"}:
                continue
            if "|" in line or "@" in line or line.startswith("+"):
                continue
            if 2 <= len(line.split()) <= 12 and not re.fullmatch(r"[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)+", line.strip()):
                return line.strip()
        return None

    @staticmethod
    def _find_skills(text: str) -> list[str]:
        """Extract skills from a dedicated skills section or inline skill labels."""
        matches = []
        for pattern in [
            r"(?:skills?|technical skills?|core competencies)[:\s]*\n(.*?)(?:\n\n|\Z)",
            r"(?:languages|development/frameworks|databases/tools|areas of focus)[:\s]*(.*?)(?:\n(?:achievements|experience|education|projects|$))",
        ]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                raw = match.group(1)
                tokens = re.split(r"[,•|\n\t]+", raw)
                for token in tokens:
                    clean = token.strip().strip(':')
                    if 2 <= len(clean) <= 40:
                        canonical = canonicalize_skill(clean.lower())
                        if canonical:
                            matches.append(canonical)
                        elif clean not in matches:
                            matches.append(clean)

        if matches:
            return matches

        for token in re.findall(r"\b(?:python|javascript|typescript|react|node\.js|sql|postgresql|mongodb|git|docker|kubernetes|aws|c\+\+|java|html|css|machine learning|backend systems|api design)\b", text, re.IGNORECASE):
            canonical = canonicalize_skill(token.lower())
            if canonical and canonical not in matches:
                matches.append(canonical)
        return matches

    @staticmethod
    def _find_experience(text: str) -> list[Experience]:
        """Parse an experience section into structured entries."""
        section = re.search(
            r"(?:experience|work history|employment)[:\s]*\n(.*?)(?=\n(?:education|skills?|projects?|achievements)\b|\Z)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if not section:
            return []

        experiences: list[Experience] = []
        blocks = re.split(r"\n\s*\n", section.group(1).strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            title = None
            company = None
            start = None
            end = None

            if len(lines) >= 1:
                first = lines[0]
                if first.lower().startswith(("software", "developer", "engineer", "intern", "lead", "manager", "analyst")) or re.match(r"^[A-Z][A-Za-z/&()\- ]+$", first):
                    title = first
            if len(lines) >= 3:
                for candidate in lines[1:]:
                    if re.search(r"\b(202[0-9]|20[0-9]{2})\b", candidate):
                        continue
                    if candidate.lower().startswith(("nov", "dec", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct")):
                        continue
                    if candidate and candidate[0].isupper() and len(candidate.split()) <= 5 and candidate not in {title}:
                        company = candidate
                        break
            if not company and len(lines) >= 2:
                company = lines[-1]
            if len(lines) >= 2:
                for candidate in lines[1:]:
                    match = re.search(r"(?P<start>\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}|\b\d{4}\b)\s*[–\-]\s*(?P<end>\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}|\b\d{4}\b|present|current)\b", candidate, re.IGNORECASE)
                    if match:
                        start = match.group("start")
                        end = match.group("end")
                        break

            if title or company:
                experiences.append(Experience(title=title, company=company, start=start, end=None if end and end.lower() in ("present", "current") else end))

        return experiences

    @staticmethod
    def _find_education(text: str) -> list[Education]:
        """Parse an education section from common resume layouts."""
        section = re.search(
            r"education[:\s]*\n(.*?)(?=\n(?:experience|skills?|projects?|achievements)\b|\Z)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if not section:
            return []

        education: list[Education] = []
        blocks = re.split(r"\n\s*\n", section.group(1).strip())
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            institution = None
            degree = None
            field = None
            year = None

            for line in lines:
                if re.search(r"\b(202[0-9]|20[0-9]{2})\b", line):
                    match = re.search(r"(20\d{2})", line)
                    year = int(match.group(1)) if match else None
                    continue
                if not institution and line[0].isupper() and len(line.split()) <= 6:
                    institution = line
                    continue
                if re.search(r"\b(bachelor|master|ph\.d|b\.e|b\.tech|m\.tech|b\.s|m\.s)\b", line, re.IGNORECASE):
                    degree = line
                    if "in" in line.lower():
                        field = line.split("in", 1)[1].strip().split("-")[0].strip()
                    break

            if institution or degree:
                education.append(Education(institution=institution, degree=degree, field=field, end_year=year))

        return education