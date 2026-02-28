"""
Stage 6 Tests: KB Build (LLM-based)
Tests parse_slides_from_markdown(), extract_tables_from_markdown(), classify_table(),
and build_lesson_entry() with mocked LLM cache.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from build_kb import (
    parse_slides_from_markdown, extract_tables_from_markdown,
    classify_table, build_lesson_entry,
)


class TestParseSlides:
    """Test slide markdown parsing."""

    def test_basic_slide_parsing(self):
        content = """# Presentation

## Slide 1
Title slide content

## Slide 2
Learning objectives
Generate ideas

**Speaker Notes:**
Teacher instructions here

---

## Slide 3
Activity content
"""
        slides = parse_slides_from_markdown(content)

        assert len(slides) == 3
        assert slides[0]["slide_number"] == 1
        assert "Title slide content" in slides[0]["text"]
        assert slides[1]["slide_number"] == 2
        assert "Teacher instructions here" in slides[1]["notes"]
        assert slides[2]["slide_number"] == 3

    def test_empty_content(self):
        slides = parse_slides_from_markdown("")
        assert slides == []

    def test_no_slides(self):
        slides = parse_slides_from_markdown("Just some text without slide markers")
        assert slides == []


class TestExtractTables:
    """Test markdown table extraction."""

    def test_basic_table(self):
        content = """Some text

| Header 1 | Header 2 |
| --- | --- |
| Cell 1 | Cell 2 |
| Cell 3 | Cell 4 |

More text"""
        tables = extract_tables_from_markdown(content)
        assert len(tables) == 1
        assert tables[0]["headers"] == ["Header 1", "Header 2"]
        assert len(tables[0]["rows"]) == 2

    def test_no_tables(self):
        tables = extract_tables_from_markdown("No tables here")
        assert tables == []


class TestBuildLessonEntry:
    """Test full lesson KB entry building with mocked LLM cache."""

    def _make_lesson_data(self, tmp_path, slides_md=""):
        """Helper to create lesson_data dict."""
        docs = []
        if slides_md:
            md_file = tmp_path / "slides.md"
            md_file.write_text(slides_md, encoding="utf-8")
            docs.append({
                "path": "term2/Lesson 5/Teachers Slides.md",
                "full_path": str(md_file),
                "content_type": "teachers_slides",
                "term": 2,
                "lessons": [5],
                "format": "md",
                "char_count": len(slides_md),
                "slide_count": slides_md.count("## Slide "),
                "content_preview": slides_md[:1000],
            })

        return {
            "lesson": 5,
            "term": 2,
            "document_count": len(docs),
            "image_count": 0,
            "native_count": 0,
            "link_count": 0,
            "video_ref_count": 0,
            "documents": docs,
            "images": [],
            "native_content": [],
            "links": [],
            "video_refs": [],
        }

    def test_returns_none_without_llm_cache(self, tmp_path, monkeypatch):
        """No LLM cache → returns None."""
        import build_kb
        monkeypatch.setattr(build_kb, "LLM_CACHE_DIR", tmp_path / "empty_cache")

        lesson_data = self._make_lesson_data(tmp_path)
        entry = build_lesson_entry(2, 5, lesson_data)
        assert entry is None

    def test_builds_entry_from_llm_cache(self, tmp_path, monkeypatch):
        """With LLM cache, builds a complete KB entry."""
        import build_kb

        cache_dir = tmp_path / "llm_cache"
        cache_dir.mkdir()
        monkeypatch.setattr(build_kb, "LLM_CACHE_DIR", cache_dir)

        # Write a mock LLM extraction cache file
        extraction = {
            "lesson_title": "Brainstorming and Concept Generation",
            "learning_objectives": ["Generate creative game concepts"],
            "description_of_activities": "Students brainstorm ideas",
            "core_topics": ["brainstorming", "concept generation"],
            "teacher_notes": [{"slide": 1, "notes": "Demo the tool"}],
            "slides_summary": "10 slides covering brainstorming",
            "videos": [{"url": "https://youtube.com/watch?v=abc", "title": "Tutorial", "type": "youtube"}],
            "resources": ["https://example.com/resource"],
            "success_criteria": ["I can generate 3+ game concepts"],
            "big_question": "How do we generate creative ideas?",
            "uae_link": "UAE innovation and creativity",
            "endstar_tools": ["Triggers", "NPCs"],
            "keywords": ["brainstorming", "concept", "game design"],
            "activity_type": "group",
            "assessment_signals": ["peer review"],
            "curriculum_alignment": [],
            "ai_focus": [],
            "artifacts": ["concept document"],
            "grade_band": "G9-G10",
        }
        cache_file = cache_dir / "term2_lesson5.json"
        cache_file.write_text(json.dumps({
            "term": 2,
            "lesson_num": 5,
            "source_hash": "abc123",
            "extraction": extraction,
        }, indent=2), encoding="utf-8")

        slides_md = """# Test
## Slide 1
Brainstorming

## Slide 2
Learning Objectives

**Speaker Notes:**
Demo the tool
"""
        lesson_data = self._make_lesson_data(tmp_path, slides_md=slides_md)
        entry = build_lesson_entry(2, 5, lesson_data)

        assert entry is not None
        assert entry["lesson_title"] == "Brainstorming and Concept Generation"
        assert entry["metadata"]["term_id"] == 2
        assert entry["metadata"]["lesson_id"] == 5
        assert "Generate creative game concepts" in entry["metadata"]["learning_objectives"]
        assert entry["big_question"] == "How do we generate creative ideas?"
        assert isinstance(entry["slides"], list)
        assert isinstance(entry["metadata"]["videos"], list)
        assert isinstance(entry["metadata"]["resources"], list)

    def test_schema_has_required_fields(self, tmp_path, monkeypatch):
        """Entry must have all required top-level and metadata fields."""
        import build_kb

        cache_dir = tmp_path / "llm_cache"
        cache_dir.mkdir()
        monkeypatch.setattr(build_kb, "LLM_CACHE_DIR", cache_dir)

        # Minimal extraction
        cache_file = cache_dir / "term1_lesson1.json"
        cache_file.write_text(json.dumps({
            "term": 1, "lesson_num": 1, "source_hash": "x",
            "extraction": {"lesson_title": "Test Lesson"},
        }, indent=2), encoding="utf-8")

        lesson_data = self._make_lesson_data(tmp_path)
        entry = build_lesson_entry(1, 1, lesson_data)

        assert entry is not None
        # Top-level fields
        for field in ("lesson_title", "metadata", "generated_at", "pipeline_version",
                       "big_question", "uae_link", "slides", "teacher_notes",
                       "rubrics", "data_tables", "schedule_tables"):
            assert field in entry, f"Missing top-level field: {field}"

        # Metadata fields
        m = entry["metadata"]
        for field in ("term_id", "lesson_id", "title", "grade_band",
                       "core_topics", "endstar_tools", "learning_objectives",
                       "videos", "resources", "keywords", "images"):
            assert field in m, f"Missing metadata field: {field}"

        # Types
        assert isinstance(m["core_topics"], list)
        assert isinstance(m["videos"], list)
        assert isinstance(m["resources"], list)
        assert isinstance(m["images"], list)
