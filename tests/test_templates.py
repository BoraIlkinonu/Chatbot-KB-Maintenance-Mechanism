"""
Tests for LLM-only templates builder (build_templates.py).
Mocks the LLM client to verify template JSON structure.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


SAMPLE_TEMPLATE_RESPONSE = {
    "is_template": True,
    "template_name": "Assessment Guide - Term 2",
    "component": "summative-product",
    "label": "Assessment / Rubric",
    "purpose": "Teacher rubric for evaluating student game design projects.",
    "skills": ["game design", "level design"],
    "criteria": ["Game mechanics implementation", "Visual design quality"],
    "weighting": 50,
    "term": 2,
    "lessons": [],
}


def _setup_consolidated_with_resources(config_override, term_num=2):
    """Helper: create consolidated JSON with term_resources."""
    consolidated = config_override["CONSOLIDATED_DIR"]
    converted = config_override["CONVERTED_DIR"]

    # Create the term resource file
    resource_path = f"term{term_num}/Assessment Guide.md"
    full_path = converted / resource_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(
        "# Assessment Guide\n\n## Rubric\n\n| Criterion | Basic | Advanced |\n"
        "|-----------|-------|----------|\n| Design | Simple | Complex |\n",
        encoding="utf-8",
    )

    data = {
        "term": term_num,
        "by_lesson": {},
        "term_resources": [
            {"path": resource_path, "content_type": "assessment_guide",
             "description": "Assessment guide for term 2"}
        ],
    }
    (consolidated / f"consolidated_term{term_num}.json").write_text(
        json.dumps(data), encoding="utf-8")


def test_templates_build_produces_json(config_override, mock_llm_client):
    """Templates build should produce templates.json."""
    _setup_consolidated_with_resources(config_override)
    mock_llm_client.call.return_value = SAMPLE_TEMPLATE_RESPONSE

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_templates import run_build_templates
        result = run_build_templates(backend="cli")

    assert result is not None
    assert result["total_templates"] == 1

    output = config_override["OUTPUT_DIR"]
    templates_file = output / "templates.json"
    assert templates_file.exists()

    data = json.loads(templates_file.read_text(encoding="utf-8"))
    assert data["total_templates"] == 1


def test_templates_entry_structure(config_override, mock_llm_client):
    """Each template entry should have the expected metadata fields."""
    _setup_consolidated_with_resources(config_override)
    mock_llm_client.call.return_value = SAMPLE_TEMPLATE_RESPONSE

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_templates import run_build_templates
        result = run_build_templates(backend="cli")

    template = result["templates"][0]
    assert "file" in template
    assert "metadata" in template

    meta = template["metadata"]
    assert meta["programme_component"] == "summative-product"
    assert meta["purpose"] != ""
    assert isinstance(meta["core_skills"], list)
    assert "items" in meta["assessment_criteria_summary"]


def test_templates_skips_non_templates(config_override, mock_llm_client):
    """Templates build should skip files the LLM says are not templates."""
    _setup_consolidated_with_resources(config_override)
    mock_llm_client.call.return_value = {"is_template": False}

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_templates import run_build_templates
        result = run_build_templates(backend="cli")

    assert result["total_templates"] == 0


def test_templates_no_resources_returns_none(config_override, mock_llm_client):
    """Templates build should handle terms with no resources."""
    consolidated = config_override["CONSOLIDATED_DIR"]
    data = {"term": 1, "by_lesson": {"1": {}}, "term_resources": []}
    (consolidated / "consolidated_term1.json").write_text(
        json.dumps(data), encoding="utf-8")

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_templates import run_build_templates
        result = run_build_templates(backend="cli")

    # No LLM calls should be made for empty resources
    mock_llm_client.call.assert_not_called()


def test_templates_per_term_output(config_override, mock_llm_client):
    """Templates build should create per-term output files."""
    _setup_consolidated_with_resources(config_override, term_num=2)
    mock_llm_client.call.return_value = SAMPLE_TEMPLATE_RESPONSE

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_templates import run_build_templates
        run_build_templates(backend="cli")

    output = config_override["OUTPUT_DIR"]
    assert (output / "Term 2 - Templates.json").exists()
