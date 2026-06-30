#!/usr/bin/env python3
"""
Candidate Profile Pipeline — CLI

Usage examples:

  # Default output (full canonical schema)
  python cli.py --csv sample_inputs/candidate.csv --github https://github.com/torvalds

  # Custom output config
  python cli.py --csv sample_inputs/candidate.csv --config config/custom_output.json

  # All source types
  python cli.py \\
    --csv    sample_inputs/candidate.csv \\
    --ats    sample_inputs/candidate_ats.json \\
    --github https://github.com/torvalds \\
    --resume sample_inputs/resume.pdf \\
    --notes  sample_inputs/recruiter_notes.txt \\
    --config config/custom_output.json \\
    --out    output/result.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the project root is on the path regardless of where CLI is invoked from.
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.pipeline import run, run_batch, should_run_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Transform candidate sources into a canonical profile.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--csv",    metavar="FILE",  help="Recruiter CSV export")
    p.add_argument("--ats",    metavar="FILE",  help="ATS JSON blob")
    p.add_argument("--github", metavar="URL",   help="GitHub profile URL or username")
    p.add_argument("--resume", metavar="FILE",  help="Resume PDF or DOCX")
    p.add_argument("--notes",  metavar="FILE",  help="Recruiter notes .txt")
    p.add_argument("--config", metavar="FILE",  help="Output config JSON (optional)")
    p.add_argument("--out",    metavar="FILE",  help="Write JSON output to file (default: stdout)")
    p.add_argument("--batch", action="store_true", default=False,
                   help="Process multiple candidates in batch mode")
    p.add_argument("--pretty", action="store_true", default=True,
                   help="Pretty-print JSON output (default: true)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    sources: list[tuple[str, str]] = []
    if args.csv:    sources.append(("csv",    args.csv))
    if args.ats:    sources.append(("ats",    args.ats))
    if args.github: sources.append(("github", args.github))
    if args.resume: sources.append(("resume", args.resume))
    if args.notes:  sources.append(("notes",  args.notes))

    if not sources:
        print("Error: at least one source is required.", file=sys.stderr)
        sys.exit(1)

    output_config = None
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Error: config file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        output_config = json.loads(config_path.read_text())

    try:
        use_batch = args.batch or should_run_batch(sources)
        if use_batch:
            result = run_batch(sources=sources, output_config=output_config)
        else:
            result = run(sources=sources, output_config=output_config)
    except Exception as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        sys.exit(1)

    indent = 2 if args.pretty else None
    json_out = json.dumps(result, indent=indent, default=str)

    if args.out:
        Path(args.out).write_text(json_out)
        print(f"Output written to {args.out}")
    else:
        print(json_out)


if __name__ == "__main__":
    main()