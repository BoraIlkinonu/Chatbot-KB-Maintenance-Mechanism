#!/usr/bin/env python3
"""
CLI entry point for Dual-LLM Judge KB Validation.

Randomly samples lessons, has two independent LLM judges evaluate
every field against source ground truth, and produces a failure report.

Usage:
    python validate_kb_judge.py --verbose
    python validate_kb_judge.py --sample-rate 0.1 --terms 1 --verbose
    python validate_kb_judge.py --backend sdk --seed 42 --budget 60
    python validate_kb_judge.py --json
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Dual-LLM Judge KB Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sample-rate", type=float, default=0.25,
        help="Fraction of lessons to sample (default: 0.25)",
    )
    parser.add_argument(
        "--terms", type=int, nargs="+", default=None,
        help="Terms to validate (default: all). Example: --terms 1 2",
    )
    parser.add_argument(
        "--backend", choices=["cli", "sdk", "auto"], default="auto",
        help="LLM backend (default: auto-detect)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible sampling",
    )
    parser.add_argument(
        "--budget", type=int, default=60,
        help="Maximum LLM calls (default: 60)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print progress and details",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Print JSON report to stdout",
    )
    parser.add_argument(
        "--kb-dir", type=str, default=None,
        help="Path to KB output directory (default: output/ from config)",
    )

    args = parser.parse_args()

    from pathlib import Path
    from validation.dual_judge import run_dual_judge_validation

    kb_dir = Path(args.kb_dir) if args.kb_dir else None
    report = run_dual_judge_validation(
        terms=args.terms,
        sample_rate=args.sample_rate,
        backend=args.backend,
        seed=args.seed,
        budget=args.budget,
        verbose=args.verbose,
        kb_dir=kb_dir,
    )

    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    sys.exit(report.exit_code())


if __name__ == "__main__":
    main()
