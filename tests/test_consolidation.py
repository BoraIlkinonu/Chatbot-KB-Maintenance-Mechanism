"""
Tests for LLM-only consolidation (consolidate.py).
Mocks the LLM client to verify consolidated JSON structure.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_consolidation_produces_valid_json(config_override, mock_llm_client):
    """Consolidation should produce a valid consolidated_term{N}.json."""
    converted = config_override["CONVERTED_DIR"]

    # Create sample converted files
    term_dir = converted / "term1"
    lesson_dir = term_dir / "Lesson 1"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "Teachers Slides.md").write_text(
        "## Slide 1\nLesson 1 - Introduction\n\n## Slide 2\nLearning Objectives",
        encoding="utf-8",
    )

    # Configure mock LLM response
    mock_llm_client.call.return_value = {
        "term": 1,
        "by_lesson": {
            "1": {
                "documents": [
                    {
                        "path": "term1/Lesson 1/Teachers Slides.md",
                        "content_type": "teachers_slides",
                        "has_slides": True,
                        "char_count": 100,
                    }
                ],
                "links": [],
                "video_refs": [],
                "image_count": 0,
            }
        },
        "term_resources": [],
    }

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from consolidate import run_consolidation
        result = run_consolidation(backend="cli")

    assert result is True

    # Check output file
    consolidated = config_override["CONSOLIDATED_DIR"]
    out_file = consolidated / "consolidated_term1.json"
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert "by_lesson" in data
    assert "term_resources" in data
    assert "1" in data["by_lesson"]
    assert data["by_lesson"]["1"]["documents"][0]["content_type"] == "teachers_slides"


def test_consolidation_adds_full_path(config_override, mock_llm_client):
    """Consolidation should add full_path to each document."""
    converted = config_override["CONVERTED_DIR"]
    term_dir = converted / "term2"
    lesson_dir = term_dir / "Lesson 3"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "Slides.md").write_text("slide content", encoding="utf-8")

    mock_llm_client.call.return_value = {
        "term": 2,
        "by_lesson": {
            "3": {
                "documents": [
                    {"path": "term2/Lesson 3/Slides.md", "content_type": "teachers_slides",
                     "has_slides": True, "char_count": 50}
                ],
                "links": [],
                "video_refs": [],
                "image_count": 0,
            }
        },
        "term_resources": [],
    }

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from consolidate import run_consolidation
        run_consolidation(backend="cli")

    consolidated = config_override["CONSOLIDATED_DIR"]
    data = json.loads((consolidated / "consolidated_term2.json").read_text(encoding="utf-8"))
    doc = data["by_lesson"]["3"]["documents"][0]
    assert "full_path" in doc
    assert doc["full_path"].endswith("Slides.md")


def test_consolidation_no_files_skips(config_override, mock_llm_client):
    """Consolidation should skip terms with no files."""
    converted = config_override["CONVERTED_DIR"]
    term_dir = converted / "term1"
    term_dir.mkdir(parents=True)
    # Empty directory — no files

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from consolidate import run_consolidation
        result = run_consolidation(backend="cli")

    # LLM should NOT have been called
    mock_llm_client.call.assert_not_called()


def test_consolidation_includes_native_extractions(config_override, mock_llm_client):
    """Consolidation should include native extractions in the prompt."""
    converted = config_override["CONVERTED_DIR"]
    term_dir = converted / "term3"
    lesson_dir = term_dir / "Lesson 5"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "Slides.md").write_text("content", encoding="utf-8")

    # Create native extractions
    native = config_override["NATIVE_DIR"]
    native_data = {
        "extractions": [
            {"term": "term3", "file_name": "Lesson Plan 5", "native_type": "google_doc"}
        ]
    }
    (native / "native_extractions.json").write_text(json.dumps(native_data), encoding="utf-8")

    mock_llm_client.call.return_value = {
        "term": 3,
        "by_lesson": {"5": {"documents": [], "links": [], "video_refs": [], "image_count": 0}},
        "term_resources": [],
    }

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from consolidate import run_consolidation
        run_consolidation(backend="cli")

    # Verify native content was passed to the LLM
    call_args = mock_llm_client.call.call_args[0][0]
    assert "term3" in call_args
    assert "Lesson Plan 5" in call_args


def test_consolidation_multiple_terms(config_override, mock_llm_client):
    """Consolidation should process all terms."""
    converted = config_override["CONVERTED_DIR"]
    for term in ("term1", "term2"):
        d = converted / term / "Lesson 1"
        d.mkdir(parents=True)
        (d / "Slides.md").write_text("content", encoding="utf-8")

    mock_llm_client.call.return_value = {
        "by_lesson": {"1": {"documents": [], "links": [], "video_refs": [], "image_count": 0}},
        "term_resources": [],
    }

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from consolidate import run_consolidation
        run_consolidation(backend="cli")

    consolidated = config_override["CONSOLIDATED_DIR"]
    assert (consolidated / "consolidated_term1.json").exists()
    assert (consolidated / "consolidated_term2.json").exists()
    assert mock_llm_client.call.call_count == 2
