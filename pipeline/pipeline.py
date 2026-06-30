"""
Pipeline orchestrator: wires all stages together.

Usage:
    from pipeline.pipeline import run

    result = run(
        sources=[
            ("csv",    "path/to/recruiter.csv"),
            ("github", "https://github.com/username"),
        ],
        output_config=None,   # or a dict from a JSON config file
    )
"""

import logging
from typing import Any

from models.canonical import RawRecord, CanonicalProfile
from pipeline.ingestors import (
    CSVIngestor, ATSJsonIngestor, GitHubIngestor,
    ResumeIngestor, RecruiterNotesIngestor,
)
from pipeline.normalize  import normalize
from pipeline.merge      import merge
from pipeline.confidence import compute_confidence
from pipeline.projector  import project
from pipeline.validator  import validate

logger = logging.getLogger(__name__)

# Maps the source type string in the config to the ingestor class
_INGESTOR_MAP = {
    "csv":    CSVIngestor,
    "ats":    ATSJsonIngestor,
    "github": GitHubIngestor,
    "resume": ResumeIngestor,
    "notes":  RecruiterNotesIngestor,
}


def run(
    sources: list[tuple[str, str]],
    output_config: dict | None = None,
) -> dict[str, Any]:
    """
    Run the full pipeline.

    Args:
        sources:       list of (source_type, path_or_url) tuples.
        output_config: optional projection config dict.

    Returns:
        A plain dict (JSON-serialisable) representing the candidate profile.
    """
    # 1 · Ingest
    raw_records: list[RawRecord] = []
    for source_type, source_value in sources:
        ingestor_cls = _INGESTOR_MAP.get(source_type.lower())
        if ingestor_cls is None:
            logger.warning("Unknown source type %r — skipping.", source_type)
            continue
        logger.info("Ingesting source: %s (%s)", source_type, source_value)
        raw_records.append(ingestor_cls(source_value).extract())

    if not raw_records:
        raise ValueError("No valid sources provided.")

    # 2 · Normalize
    normalized: list[RawRecord] = [normalize(r) for r in raw_records]

    # 3 · Merge
    profile: CanonicalProfile = merge(normalized)

    # 4 · Confidence
    profile.overall_confidence = compute_confidence(profile, normalized)

    # 5 · Project
    output = project(profile, output_config)

    # 6 · Validate
    output = validate(output, output_config)

    logger.info(
        "Pipeline complete. candidate_id=%s  confidence=%.3f",
        profile.candidate_id, profile.overall_confidence,
    )
    return output


def should_run_batch(sources: list[tuple[str, str]]) -> bool:
    """Return True when a source set is likely to produce multiple candidate records."""
    for source_type, source_value in sources:
        ingestor_cls = _INGESTOR_MAP.get(source_type.lower())
        if ingestor_cls is None:
            continue
        try:
            records = ingestor_cls(source_value).extract_records()
        except Exception as exc:
            logger.warning("Could not inspect source %s (%s): %s", source_type, source_value, exc)
            continue
        if len(records) > 1:
            return True
    return False


def run_batch(
    sources: list[tuple[str, str]],
    output_config: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Run the full pipeline for multiple candidates.

    Args:
        sources:       list of (source_type, path_or_url) tuples.
        output_config: optional projection config dict.

    Returns:
        A list of plain dicts representing canonical profiles.
    """
    raw_records: list[RawRecord] = []
    for source_type, source_value in sources:
        ingestor_cls = _INGESTOR_MAP.get(source_type.lower())
        if ingestor_cls is None:
            logger.warning("Unknown source type %r — skipping.", source_type)
            continue
        logger.info("Ingesting source: %s (%s)", source_type, source_value)
        raw_records.extend(ingestor_cls(source_value).extract_records())

    raw_records = [r for r in raw_records if not _is_empty_record(r)]
    if not raw_records:
        raise ValueError("No valid sources provided.")

    normalized: list[RawRecord] = [normalize(r) for r in raw_records]
    groups = _group_records(normalized)

    outputs: list[dict[str, Any]] = []
    for group in groups:
        profile = merge(group)
        profile.overall_confidence = compute_confidence(profile, group)
        output = project(profile, output_config)
        output = validate(output, output_config)

        logger.info(
            "Pipeline complete. candidate_id=%s  confidence=%.3f",
            profile.candidate_id, profile.overall_confidence,
        )
        outputs.append(output)

    return outputs


def _is_empty_record(record: RawRecord) -> bool:
    return not any(
        [
            record.full_name,
            record.emails,
            record.phones,
            record.location,
            record.links,
            record.headline,
            record.skills,
            record.experience,
            record.education,
        ]
    )


def _group_records(records: list[RawRecord]) -> list[list[RawRecord]]:
    groups: dict[str, list[RawRecord]] = {}
    email_to_group: dict[str, str] = {}
    name_to_group: dict[str, str] = {}
    next_group = 0

    def new_group_id() -> str:
        nonlocal next_group
        group_id = f"group_{next_group}"
        next_group += 1
        return group_id

    for record in records:
        group_id: str | None = None
        for email in record.emails:
            if email in email_to_group:
                group_id = email_to_group[email]
                break

        if group_id is None and record.full_name:
            group_id = name_to_group.get(record.full_name)

        if group_id is None:
            group_id = new_group_id()

        groups.setdefault(group_id, []).append(record)

        for email in record.emails:
            email_to_group[email] = group_id
        if record.full_name and record.full_name not in name_to_group:
            name_to_group[record.full_name] = group_id

    return list(groups.values())