"""
Dual-LLM Judge KB Validation Layer.

Two independent LLM judges evaluate sampled KB lessons against source
ground truth. Consensus-based scoring with tiered severity fields.

Usage:
    from validation.dual_judge import run_dual_judge_validation

    result = run_dual_judge_validation(
        terms=None,          # auto-discover from KB output
        sample_rate=0.25,
        backend="auto",
        seed=42,
        budget=60,
        verbose=True,
    )
"""

from validation.dual_judge.evaluator import run_dual_judge_validation

__all__ = ["run_dual_judge_validation"]
