"""
Tests for LLM-only KB builder (build_kb.py).
Mocks the LLM client to verify KB JSON structure.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


SAMPLE_KB_ENTRY = {
    "lesson_title": "Introduction to Game Design",
    "url": "Lesson 1",
    "metadata": {
        "term_id": 1,
        "lesson_id": 1,
        "title": "Introduction to Game Design",
        "grade_band": "G9-G10",
        "core_topics": ["game design", "level design"],
        "endstar_tools": ["Triggers", "NPCs"],
        "ai_focus": [],
        "learning_objectives": ["Understand basic game design principles"],
        "activity_type": "group",
        "activity_description": "Students work in groups to design a simple game.",
        "artifacts": ["game concept document"],
        "assessment_signals": ["peer review"],
        "videos": [{"url": "https://youtube.com/watch?v=abc", "title": "Intro", "type": "youtube"}],
        "resources": ["https://example.com/resource"],
        "keywords": ["game design", "level design", "NPC", "trigger"],
        "images": [],
    },
    "description_of_activities": "Students work in groups to design a simple game.",
    "big_question": "What makes a game fun?",
    "uae_link": "UAE heritage in game settings",
    "success_criteria": ["I can describe core game mechanics"],
    "curriculum_alignment": ["CS.9-10.1"],
    "teacher_notes": [{"slide": 1, "notes": "Introduce the topic"}],
    "slides": [{"slide_number": 1, "text": "Welcome to Game Design", "notes": "Introduce the topic"}],
    "rubrics": [],
    "data_tables": [],
    "schedule_tables": [],
    "document_sources": ["term1/Lesson 1/Teachers Slides.md"],
}


def _setup_consolidated(config_override, term_num=1, lessons=None):
    """Helper: create consolidated JSON with lesson data."""
    if lessons is None:
        lessons = {"1": {
            "documents": [
                {"path": f"term{term_num}/Lesson 1/Teachers Slides.md",
                 "content_type": "teachers_slides", "has_slides": True, "char_count": 500}
            ],
            "links": [],
            "video_refs": [],
            "image_count": 0,
        }}

    consolidated = config_override["CONSOLIDATED_DIR"]
    data = {"term": term_num, "by_lesson": lessons, "term_resources": []}
    (consolidated / f"consolidated_term{term_num}.json").write_text(
        json.dumps(data), encoding="utf-8")

    # Create the actual source file
    converted = config_override["CONVERTED_DIR"]
    for lesson_key, lesson_data in lessons.items():
        for doc in lesson_data.get("documents", []):
            doc_path = converted / doc["path"]
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(
                "## Slide 1\nWelcome to Game Design\n\n**Speaker Notes:**\nIntroduce the topic",
                encoding="utf-8",
            )


def test_build_produces_kb_json(config_override, mock_llm_client):
    """KB build should produce Term N - Lesson Based Structure.json."""
    _setup_consolidated(config_override)

    mock_llm_client.call.return_value = SAMPLE_KB_ENTRY

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_kb import run_build
        result = run_build(backend="cli")

    assert result is True

    output = config_override["OUTPUT_DIR"]
    kb_file = output / "Term 1 - Lesson Based Structure.json"
    assert kb_file.exists()

    kb = json.loads(kb_file.read_text(encoding="utf-8"))
    assert kb["term"] == 1
    assert kb["total_lessons"] == 1
    assert len(kb["lessons"]) == 1

    lesson = kb["lessons"][0]
    assert lesson["lesson_title"] == "Introduction to Game Design"
    assert lesson["pipeline_version"] == "5.0"
    assert "generated_at" in lesson


def test_build_kb_entry_structure(config_override, mock_llm_client):
    """Each KB entry should have all required fields."""
    _setup_consolidated(config_override)
    mock_llm_client.call.return_value = SAMPLE_KB_ENTRY

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_kb import run_build
        run_build(backend="cli")

    output = config_override["OUTPUT_DIR"]
    kb = json.loads((output / "Term 1 - Lesson Based Structure.json").read_text(encoding="utf-8"))
    lesson = kb["lessons"][0]

    # Check required top-level fields
    assert "lesson_title" in lesson
    assert "url" in lesson
    assert "metadata" in lesson
    assert "description_of_activities" in lesson
    assert "big_question" in lesson
    assert "uae_link" in lesson
    assert "success_criteria" in lesson
    assert "curriculum_alignment" in lesson
    assert "teacher_notes" in lesson
    assert "slides" in lesson

    # Check metadata fields
    meta = lesson["metadata"]
    assert "term_id" in meta
    assert "lesson_id" in meta
    assert "learning_objectives" in meta
    assert "keywords" in meta
    assert "videos" in meta


def test_build_multiple_lessons(config_override, mock_llm_client):
    """KB build should handle multiple lessons per term."""
    lessons = {}
    for i in range(1, 4):
        lessons[str(i)] = {
            "documents": [
                {"path": f"term1/Lesson {i}/Slides.md",
                 "content_type": "teachers_slides", "has_slides": True, "char_count": 200}
            ],
            "links": [], "video_refs": [], "image_count": 0,
        }
    _setup_consolidated(config_override, lessons=lessons)

    mock_llm_client.call.return_value = SAMPLE_KB_ENTRY

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_kb import run_build
        run_build(backend="cli")

    output = config_override["OUTPUT_DIR"]
    kb = json.loads((output / "Term 1 - Lesson Based Structure.json").read_text(encoding="utf-8"))
    assert kb["total_lessons"] == 3
    assert mock_llm_client.call.call_count == 3


def test_build_skips_empty_lessons(config_override, mock_llm_client):
    """KB build should skip lessons with no source content."""
    consolidated = config_override["CONSOLIDATED_DIR"]
    data = {
        "term": 1,
        "by_lesson": {
            "1": {"documents": [], "links": [], "video_refs": [], "image_count": 0}
        },
        "term_resources": [],
    }
    (consolidated / "consolidated_term1.json").write_text(json.dumps(data), encoding="utf-8")

    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_kb import run_build
        run_build(backend="cli")

    # LLM should NOT have been called for empty lessons
    mock_llm_client.call.assert_not_called()


def test_build_no_consolidated_returns_none(config_override, mock_llm_client):
    """KB build should return None when no consolidated files exist."""
    with patch("validation.dual_judge.client.create_client", return_value=mock_llm_client):
        from build_kb import run_build
        result = run_build(backend="cli")

    assert result is None
