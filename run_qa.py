"""
CLI entry point for the Layered QA System.

Usage:
    python run_qa.py                    # Run all 4 layers
    python run_qa.py --layer 1          # Programmatic only (fast)
    python run_qa.py --layer 1 3 4      # Skip LLM layer
    python run_qa.py --skip-llm         # Same as --layer 1 3 4
    python run_qa.py --layer 2          # LLM only
    python run_qa.py --term 2           # Single term
    python run_qa.py --budget 5         # Small LLM budget
    python run_qa.py --verbose          # Detailed per-check output
    python run_qa.py --json             # JSON report to stdout

Exit codes: 0=PASS, 1=NEEDS_REVIEW, 2=FAIL
"""

import sys
import argparse

sys.stdout.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Layered QA System for KB Maintenance Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0=PASS, 1=NEEDS_REVIEW, 2=FAIL",
    )
    parser.add_argument("--layer", type=int, nargs="+", choices=[1, 2, 3, 4],
                        help="Layers to run (default: all)")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip Layer 2 (LLM). Same as --layer 1 3 4")
    parser.add_argument("--term", type=int, nargs="+", choices=[1, 2, 3],
                        help="Terms to check (default: all)")
    parser.add_argument("--budget", type=int, default=None,
                        help="LLM call budget for Layer 2 (default: 15)")
    parser.add_argument("--verbose", action="store_true",
                        help="Detailed per-check output")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report to stdout")

    args = parser.parse_args()

    # Determine layers
    layers = args.layer
    if args.skip_llm:
        layers = [1, 3, 4]
    if layers is None:
        layers = [1, 2, 3, 4]

    terms = args.term or [1, 2, 3]

    from qa.runner import run_qa
    report = run_qa(
        layers=layers,
        terms=terms,
        budget=args.budget,
        verbose=args.verbose,
        json_output=args.json,
    )

    if args.json:
        print(report.to_json())

    sys.exit(report.exit_code())


if __name__ == "__main__":
    main()
