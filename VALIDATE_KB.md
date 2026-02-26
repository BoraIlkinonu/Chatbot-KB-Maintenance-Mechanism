# Dual-Judge KB Validation — Manual Guide

After the CI pipeline generates KBs, download them and run validation locally using Claude CLI.

## Quick Start

```bash
# Pull latest outputs from GitHub
git pull

# Run dual-judge on all terms (samples 25% of lessons)
python validate_kb_judge.py --backend cli --verbose

# Run on a specific term
python validate_kb_judge.py --backend cli --terms 1 --verbose
python validate_kb_judge.py --backend cli --terms 2 --verbose
python validate_kb_judge.py --backend cli --terms 3 --verbose

# Higher coverage (50% sample rate, more LLM budget)
python validate_kb_judge.py --backend cli --sample-rate 0.5 --budget 120 --verbose

# JSON output for programmatic use
python validate_kb_judge.py --backend cli --json
```

## What It Does

Two independent Claude LLM judges evaluate each sampled lesson by comparing KB fields against source documents:

- **lesson_title** — matches source slide/doc title
- **learning_objectives** — extracted from slides or native docs
- **core_topics** — relevant educational topics, no noise
- **uae_link** — UAE context from speaker notes or docs
- **success_criteria** — tiered assessment criteria
- **assessment_signals** — "I can..." statements, tier labels
- **artifacts** — portfolio entries
- **videos** — correct lesson assignment, no exemplar leakage
- **document_sources** — no cross-term files

Both judges must agree for a field to PASS. Disagreements trigger a third call.

## Reports

After running, check:
- `validation/dual_judge_report.json` — full structured report
- `validation/dual_judge_report.txt` — human-readable summary
- `validation/dual_judge_report_term{1,2,3}.json` — per-term reports

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--backend` | `auto` | `cli` (Claude CLI) or `sdk` (Anthropic SDK) |
| `--terms` | all | Which terms to validate (e.g., `--terms 1 2`) |
| `--sample-rate` | `0.25` | Fraction of lessons to sample |
| `--seed` | random | Fixed seed for reproducible sampling |
| `--budget` | `60` | Max LLM calls |
| `--verbose` | off | Print progress details |
| `--json` | off | Output JSON to stdout |

## Prerequisites

- Claude CLI installed and authenticated (`claude --version` to verify)
- Generated KB files in `output/` directory
- Source files in `sources/` directory (for ground truth comparison)
