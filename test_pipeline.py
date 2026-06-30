"""
Tests for the candidate profile pipeline.
Run with:  python -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.canonical import RawRecord, Location, Links, Experience
from pipeline.normalizers import (
    normalize_phone, normalize_date, normalize_country,
    canonicalize_skill, normalize_email,
)
from pipeline.normalize  import normalize
from pipeline.merge      import merge
from pipeline.confidence import compute_confidence
from pipeline.projector  import project, _resolve_path
from pipeline.validator  import validate, ValidationError
from pipeline.ingestors.notes_ingestor import RecruiterNotesIngestor
from pipeline.ingestors.resume_ingestor import ResumeIngestor


# ==========================================================================
# Normalizers
# ==========================================================================

class TestNormalizers:
    def test_phone_e164(self):
        assert normalize_phone("+1-415-555-0101") == "+14155550101"

    def test_phone_digits_only(self):
        assert normalize_phone("4155550101", "US") == "+14155550101"

    def test_phone_garbage_returns_none(self):
        assert normalize_phone("not-a-phone") is None

    def test_date_yyyy_mm(self):
        assert normalize_date("03-2020") == "03-2020"

    def test_date_year_only(self):
        assert normalize_date("2020") == "01-2020"

    def test_date_human_readable(self):
        result = normalize_date("March 2020")
        assert result == "03-2020"

    def test_date_empty_returns_none(self):
        assert normalize_date("") is None

    def test_country_full_name(self):
        assert normalize_country("United States") == "US"

    def test_country_alpha2_passthrough(self):
        assert normalize_country("US") == "US"

    def test_country_unknown_returns_none(self):
        assert normalize_country("Narnia") is None

    def test_skill_alias(self):
        assert canonicalize_skill("js") == "JavaScript"
        assert canonicalize_skill("ML") == "Machine Learning"
        assert canonicalize_skill("k8s") == "Kubernetes"

    def test_skill_unknown_returns_none(self):
        assert canonicalize_skill("wizardry") is None

    def test_email_normalizes(self):
        assert normalize_email("Jane.Doe@EXAMPLE.COM") == "jane.doe@example.com"

    def test_email_invalid_returns_none(self):
        assert normalize_email("not-an-email") is None


# ==========================================================================
# Normalize stage
# ==========================================================================

class TestNormalizeStage:
    def _make_record(self, **kwargs) -> RawRecord:
        return RawRecord(source="csv", **kwargs)

    def test_phones_normalized(self):
        rec = self._make_record(phones=["+1 (415) 555-0101"])
        result = normalize(rec)
        assert result.phones == ["+14155550101"]

    def test_invalid_phone_dropped(self):
        rec = self._make_record(phones=["not-a-phone"])
        result = normalize(rec)
        assert result.phones == []

    def test_skills_canonicalized(self):
        rec = self._make_record(skills=["js", "python", "unknown_skill"])
        result = normalize(rec)
        assert "JavaScript" in result.skills
        assert "Python" in result.skills
        assert "unknown_skill" not in result.skills

    def test_username_like_name_dropped(self):
        rec = self._make_record(full_name="johnsmith42")
        result = normalize(rec)
        assert result.full_name is None

    def test_real_name_kept(self):
        rec = self._make_record(full_name="Jane Doe")
        result = normalize(rec)
        assert result.full_name == "Jane Doe"

    def test_duplicate_emails_deduped(self):
        rec = self._make_record(emails=["a@b.com", "A@B.COM", "c@d.com"])
        result = normalize(rec)
        assert result.emails == ["a@b.com", "c@d.com"]


# ==========================================================================
# Merge stage
# ==========================================================================

class TestMergeStage:
    def _csv_record(self, **kwargs) -> RawRecord:
        return RawRecord(source="csv", **kwargs)

    def _github_record(self, **kwargs) -> RawRecord:
        return RawRecord(source="github", **kwargs)

    def _resume_record(self, **kwargs) -> RawRecord:
        return RawRecord(source="resume", **kwargs)

    def test_email_dedup_across_sources(self):
        r1 = self._csv_record(emails=["jane@example.com"])
        r2 = self._github_record(emails=["jane@example.com"])
        profile = merge([r1, r2])
        assert profile.emails.count("jane@example.com") == 1

    def test_name_priority_resume_over_csv(self):
        r1 = self._csv_record(full_name="J. Doe")
        r2 = self._resume_record(full_name="Jane Doe")
        profile = merge([r1, r2])
        assert profile.full_name == "Jane Doe"  # resume wins

    def test_skills_union(self):
        r1 = self._csv_record(skills=["Python"])
        r2 = self._github_record(skills=["JavaScript"])
        profile = merge([r1, r2])
        names = [s.name for s in profile.skills]
        assert "Python" in names
        assert "JavaScript" in names

    def test_skill_confidence_higher_with_two_sources(self):
        r1 = self._csv_record(skills=["Python"])
        r2 = self._github_record(skills=["Python"])
        profile = merge([r1, r2])
        python_skill = next(s for s in profile.skills if s.name == "Python")
        assert python_skill.confidence > 0.5

    def test_candidate_id_deterministic(self):
        r1 = self._csv_record(emails=["jane@example.com"])
        id1 = merge([r1]).candidate_id
        id2 = merge([r1]).candidate_id
        assert id1 == id2

    def test_provenance_populated(self):
        r1 = self._csv_record(full_name="Jane Doe", emails=["jane@example.com"])
        profile = merge([r1])
        fields = {p.field for p in profile.provenance}
        assert "full_name" in fields

    def test_missing_source_handled_gracefully(self):
        r1 = self._csv_record(full_name="Jane Doe")
        r2 = RawRecord(source="github")  # empty
        profile = merge([r1, r2])
        assert profile.full_name == "Jane Doe"


# ==========================================================================
# Confidence stage
# ==========================================================================

class TestConfidenceStage:
    def test_more_fields_higher_confidence(self):
        full = RawRecord(
            source="resume",
            full_name="Jane Doe",
            emails=["jane@example.com"],
            phones=["+14155550101"],
            skills=["Python"],
            experience=[Experience(company="Acme", title="Engineer")],
        )
        sparse = RawRecord(source="csv", full_name="Jane Doe")

        p_full   = merge([full])
        p_sparse = merge([sparse])

        c_full   = compute_confidence(p_full,   [full])
        c_sparse = compute_confidence(p_sparse, [sparse])
        assert c_full > c_sparse

    def test_confidence_in_range(self):
        rec = RawRecord(source="csv", full_name="Jane", emails=["j@example.com"])
        profile = merge([rec])
        c = compute_confidence(profile, [rec])
        assert 0.0 <= c <= 1.0


# ==========================================================================
# Projector
# ==========================================================================

class TestProjector:
    def _make_profile(self):
        from models.canonical import CanonicalProfile, Skill
        return CanonicalProfile(
            candidate_id="cand_abc123",
            full_name="Jane Doe",
            emails=["jane@example.com", "jane@work.com"],
            phones=["+14155550101"],
            skills=[Skill(name="Python", confidence=0.9, sources=["csv"])],
            overall_confidence=0.85,
        )

    def test_path_simple_field(self):
        p = self._make_profile()
        assert _resolve_path(p, "full_name") == "Jane Doe"

    def test_path_indexed(self):
        p = self._make_profile()
        assert _resolve_path(p, "emails[0]") == "jane@example.com"

    def test_path_array_map(self):
        p = self._make_profile()
        result = _resolve_path(p, "skills[].name")
        assert result == ["Python"]

    def test_path_out_of_bounds_returns_none(self):
        p = self._make_profile()
        assert _resolve_path(p, "emails[99]") is None

    def test_project_with_config(self):
        p = self._make_profile()
        config = {
            "fields": [
                {"path": "full_name", "type": "string", "required": True},
                {"path": "primary_email", "from": "emails[0]", "type": "string"},
            ],
            "include_confidence": True,
            "include_provenance": False,
            "on_missing": "null",
        }
        out = project(p, config)
        assert out["full_name"] == "Jane Doe"
        assert out["primary_email"] == "jane@example.com"
        assert "overall_confidence" in out
        assert "provenance" not in out

    def test_on_missing_omit(self):
        p = self._make_profile()
        config = {
            "fields": [{"path": "headline", "type": "string"}],
            "on_missing": "omit",
            "include_confidence": False,
            "include_provenance": False,
        }
        out = project(p, config)
        assert "headline" not in out

    def test_on_missing_null(self):
        p = self._make_profile()
        config = {
            "fields": [{"path": "headline", "type": "string"}],
            "on_missing": "null",
            "include_confidence": False,
            "include_provenance": False,
        }
        out = project(p, config)
        assert out["headline"] is None


# ==========================================================================
# Validator
# ==========================================================================

class TestValidator:
    def test_passes_when_valid(self):
        config = {"fields": [{"path": "name", "required": True, "type": "string"}]}
        out = validate({"name": "Jane"}, config)
        assert out["name"] == "Jane"

    def test_warns_on_missing_non_required(self, caplog):
        import logging
        config = {"fields": [{"path": "headline", "required": False}], "on_missing": "null"}
        with caplog.at_level(logging.WARNING):
            validate({"headline": None}, config)
        # No exception should be raised

    def test_raises_on_missing_required_when_error(self):
        config = {
            "fields": [{"path": "email", "required": True}],
            "on_missing": "error",
        }
        with pytest.raises(ValidationError):
            validate({"email": None}, config)

    def test_no_config_passes_through(self):
        data = {"anything": 42}
        assert validate(data, None) == data


# ==========================================================================
# Edge cases (integration-level)
# ==========================================================================

class TestEdgeCases:
    def test_notes_ingestor_splits_multiple_candidates(self, tmp_path):
        notes_file = tmp_path / "notes.txt"
        notes_file.write_text(
            """Candidate: Arjun Mehta
Contact: arjun.mehta@email.com | +91 98765 43210
Skills: Python, AWS

Candidate: Priya Reddy
Contact: priya.reddy@email.com | +91 99887 66554
Skills: JavaScript, React
""",
            encoding="utf-8",
        )

        records = RecruiterNotesIngestor(notes_file).extract_records()

        assert len(records) == 2
        assert records[0].full_name == "Arjun Mehta"
        assert records[0].emails == ["arjun.mehta@email.com"]
        assert "Python" in records[0].skills
        assert records[1].full_name == "Priya Reddy"
        assert records[1].emails == ["priya.reddy@email.com"]
        assert "React" in records[1].skills

    def test_resume_ingestor_extracts_structured_fields(self, tmp_path):
        resume_file = tmp_path / "resume.txt"
        resume_file.write_text(
            """Ayush Anand
+91-7644092315 | ayushaanand06@gmail.com | LinkedIn | GitHub
Education
Bangalore Institute of Technology
2022 – 2026
Bachelor of Engineering in Computer Science (Data Science) - CGPA: 9.1/10.0
Experience
Software Development Engineer Intern
Nov 2025 – Dec 2025
Akatsuki AI Technologies
Technical Skills
Languages: Python, JavaScript, TypeScript
Databases/Tools: SQL, PostgreSQL, MongoDB, Git
""",
            encoding="utf-8",
        )

        record = ResumeIngestor(resume_file).extract()

        assert record.full_name == "Ayush Anand"
        assert record.emails == ["ayushaanand06@gmail.com"]
        assert record.phones == ["+91-7644092315"]
        assert "Python" in record.skills
        assert len(record.experience) >= 1
        assert len(record.education) >= 1

    def test_completely_empty_source_doesnt_crash(self):
        """An ingestor returning an empty RawRecord must not break the merge."""
        empty = RawRecord(source="csv")
        real  = RawRecord(source="resume", full_name="Jane Doe", emails=["j@example.com"])
        profile = merge([empty, real])
        assert profile.full_name == "Jane Doe"

    def test_all_empty_sources_still_produces_profile(self):
        """Even all-empty records should produce a (low-confidence) profile."""
        records = [RawRecord(source="csv"), RawRecord(source="github")]
        profile = merge(records)
        assert profile.candidate_id.startswith("cand_")

    def test_conflicting_names_highest_priority_wins(self):
        low  = RawRecord(source="ats",    full_name="J. Doe")
        mid  = RawRecord(source="csv",    full_name="Jane D.")
        high = RawRecord(source="resume", full_name="Jane Doe")
        profile = merge([low, mid, high])
        assert profile.full_name == "Jane Doe"

    def test_single_source_confidence_below_multisource(self):
        single = RawRecord(source="resume", full_name="Jane", emails=["j@example.com"],
                           skills=["Python"])
        multi  = [
            RawRecord(source="resume", full_name="Jane", emails=["j@example.com"], skills=["Python"]),
            RawRecord(source="csv",    full_name="Jane", emails=["j@example.com"]),
        ]
        p_single = merge([single])
        p_multi  = merge(multi)
        c_single = compute_confidence(p_single, [single])
        c_multi  = compute_confidence(p_multi,  multi)
        assert c_multi >= c_single