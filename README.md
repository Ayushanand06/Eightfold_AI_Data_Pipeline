# Candidate Profile Pipeline

Transforms messy, multi-source candidate data into one clean canonical profile.

## Pipeline stages

```
Ingest → Normalize → Merge → Confidence → Project → Validate → JSON output
```

| Stage | What it does |
|---|---|
| **Ingest** | One ingestor class per source type extracts a `RawRecord` |
| **Normalize** | Phones → E.164, dates → YYYY-MM, country → ISO-3166, skills → canonical |
| **Merge** | Deduplicates across sources; higher-priority sources win conflicts |
| **Confidence** | Weighted score based on field fill rate, source agreement, source quality |
| **Project** | Applies optional runtime config (rename fields, select subset, handle missing) |
| **Validate** | Checks required fields; degrades gracefully on failures |

## Supported source types

| Flag | Source | Group |
|---|---|---|
| `--csv` | Recruiter CSV export | Structured |
| `--ats` | ATS JSON blob | Structured |
| `--github` | GitHub profile URL or username | Unstructured |
| `--resume` | Resume PDF or DOCX | Unstructured |
| `--notes` | Recruiter notes .txt | Unstructured |

At least one structured **and** one unstructured source should be provided.

## Setup

```bash
pip install pydantic phonenumbers pycountry dateparser PyMuPDF python-docx requests rapidfuzz
```

## Run — default output (full canonical schema)

```bash
python cli.py \
  --csv    sample_inputs/candidate.csv \
  --ats    sample_inputs/candidate_ats.json \
  --notes  sample_inputs/recruiter_notes.txt
```

## Run — custom output config

```bash
python cli.py \
  --csv    sample_inputs/candidate.csv \
  --ats    sample_inputs/candidate_ats.json \
  --config config/custom_output.json \
  --out    output/result.json
```

## Run — tests

```bash
python -m pytest tests/ -v
```

All 44 tests should pass.

## Output config format

```json
{
  "fields": [
    { "path": "full_name",     "type": "string",   "required": true },
    { "path": "primary_email", "from": "emails[0]","type": "string",   "required": true },
    { "path": "phone",         "from": "phones[0]","type": "string",   "normalize": "E164" },
    { "path": "skills",        "from": "skills[].name", "type": "string[]" }
  ],
  "include_provenance": false,
  "include_confidence": true,
  "on_missing": "null"
}
```

| Key | Options | Meaning |
|---|---|---|
| `path` | any string | Output key name |
| `from` | `field`, `field[N]`, `field[].attr` | Canonical source path (defaults to `path`) |
| `required` | true/false | Affects `on_missing` behaviour |
| `normalize` | `"E164"`, `"canonical"` | Post-projection normalizer |
| `include_provenance` | true/false | Include provenance array in output |
| `include_confidence` | true/false | Include overall_confidence |
| `on_missing` | `"null"`, `"omit"`, `"error"` | What to do when a field has no value |

## Confidence scoring

```
confidence = (fields_populated × 0.30) + (source_agreement × 0.40) + (source_quality × 0.30)
```

- **fields_populated**: weighted fill rate; email/name/phone count more than headline/links
- **source_agreement**: do multiple sources agree on identity fields?
- **source_quality**: highest-quality source present (LinkedIn=1.0 → notes=0.4)

All weights live in `pipeline/confidence.py` and can be tuned without touching other code.

## Merge / conflict resolution

Source priority (highest wins): `resume > github > csv > ats > notes`

- Scalar fields (name, headline, location): highest-priority non-null value wins
- List fields (emails, phones, skills): union across all sources, deduplicated
- Skills confidence: proportional to how many sources mention the skill
- All contributing sources are recorded in `provenance`

## Project structure

```
candidate_pipeline/
├── cli.py                          # Entry point
├── models/
│   └── canonical.py                # All data models (Pydantic)
├── pipeline/
│   ├── pipeline.py                 # Orchestrator
│   ├── normalize.py                # Normalize stage
│   ├── merge.py                    # Merge + conflict resolution
│   ├── confidence.py               # Confidence scoring
│   ├── projector.py                # Runtime output config
│   ├── validator.py                # Output validation
│   ├── ingestors/
│   │   ├── base.py
│   │   ├── csv_ingestor.py
│   │   ├── ats_json_ingestor.py
│   │   ├── github_ingestor.py
│   │   ├── resume_ingestor.py
│   │   └── notes_ingestor.py
│   └── normalizers/
│       └── normalizers.py          # Phone, date, country, skill, email
├── config/
│   ├── custom_output.json          # Example: rename + select fields
│   └── minimal_output.json         # Example: minimal projection, omit missing
├── sample_inputs/
│   ├── candidate.csv
│   ├── candidate_ats.json
│   └── recruiter_notes.txt
└── tests/
    └── test_pipeline.py            # tests covering all stages
```

## Design decisions & assumptions

- **Wrong-but-confident is worse than null**: unrecognised skills are dropped (not passed through); username-like strings are never stored as `full_name`.
- **Email is the primary dedup key**: two records with the same normalized email are always the same person. Name fuzzy-matching is a secondary signal only.
- **GitHub `login` ≠ name**: `login` ("johnsmith42") goes into `links.github`, never into `full_name`. Only `user.name` (the display name) is used.
- **Deterministic output**: same inputs always produce the same output (no random UUIDs, no timestamp-based IDs).
- **LinkedIn scraping is out of scope**: against ToS. Mock the ingestor or pass a LinkedIn URL through the notes field.
- **Resume parsing is heuristic**: regex-based extraction works for clean resumes but will miss complex layouts. A production system would use a dedicated parsing service.