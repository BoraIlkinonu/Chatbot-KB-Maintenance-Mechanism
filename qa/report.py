"""
Unified report builder for the QA system.

CheckResult dataclass, QAReport aggregation, verdict logic, save/print.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class CheckResult:
    """A single QA check result — used across all 4 layers."""
    check_id: str
    layer: int
    passed: bool
    severity: str  # "ERROR", "WARNING", "INFO"
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class QAReport:
    """Aggregates CheckResults from all layers and computes verdict."""

    def __init__(self):
        self.results: list[CheckResult] = []
        self.layer_summaries: dict[int, dict] = {}
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.llm_meta: dict = {}  # Layer 2 metadata (model, budget, etc.)

    def add(self, result: CheckResult):
        self.results.append(result)

    def add_all(self, results: list[CheckResult]):
        self.results.extend(results)

    def set_layer_summary(self, layer: int, summary: dict):
        self.layer_summaries[layer] = summary

    def set_llm_meta(self, meta: dict):
        self.llm_meta = meta

    # ── Filtering ──

    def by_layer(self, layer: int) -> list[CheckResult]:
        return [r for r in self.results if r.layer == layer]

    def by_severity(self, severity: str) -> list[CheckResult]:
        return [r for r in self.results if r.severity == severity]

    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def errors(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity == "ERROR"]

    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity == "WARNING"]

    # ── Verdict ──

    def compute_verdict(self) -> str:
        """
        PASS:         0 blocking errors, <10 warnings, Layer 4 >=80%, LLM confidence >=80%
        NEEDS_REVIEW: 0 blocking errors but warnings or low confidence
        FAIL:         Any blocking errors (ERROR-severity failures)
        """
        error_count = len(self.errors())
        warning_count = len(self.warnings())

        if error_count > 0:
            return "FAIL"

        # Layer 4 pass rate
        l4 = self.by_layer(4)
        l4_pass_rate = sum(1 for r in l4 if r.passed) / max(len(l4), 1)

        # LLM confidence from layer summary
        llm_confidence = self.layer_summaries.get(2, {}).get("confidence", 1.0)

        if warning_count < 10 and l4_pass_rate >= 0.8 and llm_confidence >= 0.8:
            return "PASS"

        return "NEEDS_REVIEW"

    def exit_code(self) -> int:
        verdict = self.compute_verdict()
        return {"PASS": 0, "NEEDS_REVIEW": 1, "FAIL": 2}.get(verdict, 2)

    # ── Summary ──

    def summary(self) -> dict:
        layers_run = sorted(set(r.layer for r in self.results))
        return {
            "verdict": self.compute_verdict(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": self.started_at,
            "total_checks": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
            "errors": len(self.errors()),
            "warnings": len(self.warnings()),
            "info_failures": len([r for r in self.results if not r.passed and r.severity == "INFO"]),
            "layers_run": layers_run,
            "per_layer": {
                layer: {
                    "total": len(self.by_layer(layer)),
                    "passed": sum(1 for r in self.by_layer(layer) if r.passed),
                    "failed": sum(1 for r in self.by_layer(layer) if not r.passed),
                }
                for layer in layers_run
            },
            "layer_summaries": self.layer_summaries,
            "llm_meta": self.llm_meta,
        }

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, path: Path, term: Optional[int] = None):
        """Save full JSON report."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    def save_text(self, path: Path):
        """Save human-readable text summary."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.format_text())

    # ── Text Formatting ──

    def format_text(self, verbose: bool = False) -> str:
        lines = []
        s = self.summary()
        verdict = s["verdict"]

        lines.append("=" * 70)
        lines.append(f"  QA REPORT — {verdict}")
        lines.append(f"  {s['generated_at']}")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Verdict:    {verdict}")
        lines.append(f"Checks:     {s['total_checks']} total, {s['passed']} passed, {s['failed']} failed")
        lines.append(f"Errors:     {s['errors']}")
        lines.append(f"Warnings:   {s['warnings']}")
        lines.append(f"Layers run: {s['layers_run']}")
        lines.append("")

        # Per-layer summary
        for layer, stats in s["per_layer"].items():
            layer_name = {1: "Programmatic", 2: "LLM Cross-Val", 3: "Edge Cases", 4: "User Scenarios"}.get(layer, f"Layer {layer}")
            lines.append(f"  Layer {layer} ({layer_name}): {stats['passed']}/{stats['total']} passed")

        lines.append("")

        # Failures
        failures = self.failures()
        if failures:
            lines.append("FAILURES:")
            lines.append("-" * 50)
            for r in sorted(failures, key=lambda x: ({"ERROR": 0, "WARNING": 1, "INFO": 2}.get(x.severity, 3), x.check_id)):
                lines.append(f"  [{r.severity}] {r.check_id}: {r.message}")
                if verbose and r.details:
                    for k, v in r.details.items():
                        lines.append(f"           {k}: {v}")
            lines.append("")

        # LLM summary if present
        if 2 in s.get("layer_summaries", {}):
            llm = s["layer_summaries"][2]
            lines.append("LLM CROSS-VALIDATION:")
            lines.append("-" * 50)
            lines.append(f"  Confidence: {llm.get('confidence', 'N/A')}")
            lines.append(f"  Calls made: {llm.get('calls_made', 'N/A')}")
            lines.append(f"  Budget:     {llm.get('budget', 'N/A')}")
            lines.append("")

        return "\n".join(lines)

    def print_summary(self, verbose: bool = False):
        print(self.format_text(verbose))
