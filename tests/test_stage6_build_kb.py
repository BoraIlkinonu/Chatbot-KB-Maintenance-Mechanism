"""
Stage 6 Tests: KB Field Population
Tests extract_endstar_tools(), build_video_entries(), build_resource_entries(), build_lesson_kb()
"""

import pytest
from pathlib import Path

from build_kb import (
    extract_endstar_tools, build_video_entries, build_resource_entries,
    build_lesson_kb, parse_slides_from_markdown,
)


class TestExtractEndstarTools:
    """Test Endstar platform tool keyword matching."""

    def test_single_word_match(self):
        """Scenario 3: Endstar tool mentions populated from keyword matching."""
        text = "Students will use Triggers to create game events"
        tools = extract_endstar_tools(text)
        assert "Triggers" in tools

    def test_partial_match_rejected(self):
        """Scenario 4: 'logical' should not match 'logic'."""
        text = "This is a logical approach to the problem"
        tools = extract_endstar_tools(text)
        assert "Logic" not in tools, "'logical' should not match 'logic'"

    def test_exact_word_match(self):
        """'logic' is ambiguous — needs Endstar context to match."""
        text = "Use logic blocks to control game flow in the Endstar platform"
        tools = extract_endstar_tools(text)
        assert "Logic" in tools

    def test_logic_without_context(self):
        """'logic' without Endstar context should NOT match (ambiguous)."""
        text = "Use logic blocks to control game flow"
        tools = extract_endstar_tools(text)
        assert "Logic" not in tools

    def test_case_insensitive(self):
        """Scenario 5: 'TRIGGERS' matches 'Triggers'."""
        text = "Add TRIGGERS to the scene"
        tools = extract_endstar_tools(text)
        assert "Triggers" in tools

    def test_multi_word_keyword(self):
        """Scenario 10: 'rule block' matched as substring."""
        text = "Create a rule block for player movement"
        tools = extract_endstar_tools(text)
        assert "Rule Blocks" in tools

    def test_npc_dialogue(self):
        """Scenario 10: 'NPC dialogue' matched."""
        text = "Write NPC dialogue for the quest giver"
        tools = extract_endstar_tools(text)
        assert "NPC dialogue" in tools

    def test_multiple_tools_found(self):
        text = "Use triggers and NPCs with custom interactions and mechanics in the Endstar platform"
        tools = extract_endstar_tools(text)
        assert "Triggers" in tools
        assert "NPCs" in tools
        assert "Interactions" in tools
        assert "Mechanics" in tools

    def test_no_tools_found(self):
        text = "This lesson is about design briefs and research"
        tools = extract_endstar_tools(text)
        assert tools == []

    def test_deduplicated_results(self):
        """NPC and NPCs both map to 'NPCs' — no duplicate."""
        text = "NPC characters and NPCs in the game"
        tools = extract_endstar_tools(text)
        assert tools.count("NPCs") == 1


class TestBuildVideoEntries:
    """Test video entry building from consolidated video references."""

    def test_video_files_and_links(self):
        """Scenario 1: Video files + video links → metadata.videos[] populated."""
        video_refs = [
            {"type": "video_file", "title": "demo", "filename": "demo.mp4",
             "path": "/path/demo.mp4", "url": "", "video_id": ""},
            {"type": "video_link", "title": "Tutorial", "url": "https://youtube.com/watch?v=abc",
             "video_id": "", "filename": ""},
        ]

        videos = build_video_entries(video_refs)

        assert len(videos) == 2
        titles = [v["title"] for v in videos]
        assert "demo" in titles
        assert "Tutorial" in titles

        # Check schema
        for v in videos:
            assert "video_id" in v
            assert "title" in v
            assert "url" in v
            assert "order" in v
            assert "type" in v

    def test_dedup_by_url(self):
        """Scenario 1: Deduplicated by URL/filename."""
        video_refs = [
            {"type": "video_link", "title": "Vid 1", "url": "https://youtube.com/watch?v=same",
             "video_id": "", "filename": ""},
            {"type": "video_link", "title": "Vid 2", "url": "https://youtube.com/watch?v=same",
             "video_id": "", "filename": ""},
        ]

        videos = build_video_entries(video_refs)
        assert len(videos) == 1, "Duplicate URLs should be deduped"

    def test_empty_refs(self):
        """Scenario 8: Empty arrays, not null."""
        videos = build_video_entries([])
        assert videos == []
        assert isinstance(videos, list)


class TestBuildResourceEntries:
    """Test resource entry building from consolidated links."""

    def test_hyperlinks_to_resources(self):
        """Scenario 2: Hyperlinks populated, formatted as 'Label - URL'."""
        links = [
            {"url": "https://example.com/rubric", "text": "Assessment Rubric"},
            {"url": "https://notebooklm.google.com", "text": "NotebookLM"},
        ]

        resources = build_resource_entries(links)

        assert len(resources) == 2
        assert any("Assessment Rubric" in r for r in resources)
        assert any("notebooklm" in r.lower() for r in resources)

    def test_video_urls_filtered(self):
        """Scenario 6: YouTube/Vimeo links NOT in resources."""
        links = [
            {"url": "https://youtube.com/watch?v=abc", "text": "Video"},
            {"url": "https://vimeo.com/123", "text": "Another Video"},
            {"url": "https://example.com/resource", "text": "Resource"},
        ]

        resources = build_resource_entries(links)

        for r in resources:
            assert "youtube.com" not in r, "YouTube URLs should not be in resources"
            assert "vimeo.com" not in r, "Vimeo URLs should not be in resources"
        assert len(resources) == 1

    def test_duplicate_urls_deduped(self):
        """Scenario 7: Same URL from different sources merged."""
        links = [
            {"url": "https://example.com/same", "text": "Link from PPTX"},
            {"url": "https://example.com/same", "text": "Link from native"},
        ]

        resources = build_resource_entries(links)
        assert len(resources) == 1

    def test_no_links_empty_list(self):
        """Scenario 8: Lesson with zero links → empty list, not null."""
        resources = build_resource_entries([])
        assert resources == []
        assert isinstance(resources, list)

    def test_url_only_when_no_text(self):
        """Links without descriptive text — just the URL."""
        links = [
            {"url": "https://example.com/page", "text": ""},
        ]

        resources = build_resource_entries(links)
        assert len(resources) == 1
        assert resources[0] == "https://example.com/page"

    def test_short_text_uses_url_only(self):
        """Links with very short text (<=3 chars) — just URL."""
        links = [
            {"url": "https://example.com/page", "text": "OK"},
        ]

        resources = build_resource_entries(links)
        assert len(resources) == 1
        assert resources[0] == "https://example.com/page"


class TestBuildLessonKb:
    """Test full lesson KB entry building."""

    def _make_lesson_data(self, tmp_path, slides_md="", links=None, video_refs=None,
                          native_content=None, images=None):
        """Helper to create lesson_data dict with optional slide markdown file."""
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
            "image_count": len(images or []),
            "native_count": len(native_content or []),
            "link_count": len(links or []),
            "video_ref_count": len(video_refs or []),
            "documents": docs,
            "images": images or [],
            "native_content": native_content or [],
            "links": links or [],
            "video_refs": video_refs or [],
        }

    def test_lesson_with_videos_and_links(self, tmp_path):
        """Scenario 9: All content types populated simultaneously."""
        slides_md = """# Test Slides

## Slide 1
Lesson 5 – Brainstorming and Concept Generation

## Slide 2
Learning Objectives
Generate creative game concepts using triggers and NPCs

**Speaker Notes:**
Teachers should demo the tool

---
"""
        links = [
            {"url": "https://notebooklm.google.com", "text": "NotebookLM",
             "source": "pptx", "term": 2, "lessons": [5]},
            {"url": "https://youtube.com/watch?v=abc", "text": "Tutorial",
             "source": "pptx", "term": 2, "lessons": [5]},
        ]
        video_refs = [
            {"type": "video_link", "title": "Tutorial",
             "url": "https://youtube.com/watch?v=abc", "video_id": "", "filename": ""},
        ]

        lesson_data = self._make_lesson_data(
            tmp_path, slides_md=slides_md, links=links, video_refs=video_refs
        )

        entry = build_lesson_kb(5, lesson_data, 2)

        # Check schema
        assert "lesson_title" in entry
        assert "metadata" in entry
        m = entry["metadata"]
        assert "endstar_tools" in m
        assert "videos" in m
        assert "resources" in m
        assert isinstance(m["endstar_tools"], list)
        assert isinstance(m["videos"], list)
        assert isinstance(m["resources"], list)

        # Videos populated
        assert len(m["videos"]) >= 1

        # Resources populated (NotebookLM, not YouTube)
        resource_text = " ".join(m["resources"]).lower()
        assert "notebooklm" in resource_text

        # Endstar tools from slide content
        assert "Triggers" in m["endstar_tools"]
        assert "NPCs" in m["endstar_tools"]

    def test_lesson_with_zero_content(self, tmp_path):
        """Scenario 8: Empty arrays, not null — schema preserved."""
        lesson_data = self._make_lesson_data(tmp_path)

        entry = build_lesson_kb(1, lesson_data, 1)

        m = entry["metadata"]
        assert isinstance(m["endstar_tools"], list)
        assert isinstance(m["videos"], list)
        assert isinstance(m["resources"], list)
        assert isinstance(m["core_topics"], list)
        assert isinstance(m["learning_objectives"], list)
        assert isinstance(m["images"], list)

    def test_endstar_tools_from_all_text(self, tmp_path):
        """Scenario 3: Endstar tools populated from all lesson text."""
        slides_md = """# Test

## Slide 1
Endstar Mechanics Overview

## Slide 2
Use logic and connections to build interactions
Add triggers for game events
"""
        lesson_data = self._make_lesson_data(tmp_path, slides_md=slides_md)
        entry = build_lesson_kb(6, lesson_data, 3)

        tools = entry["metadata"]["endstar_tools"]
        assert "Mechanics" in tools
        assert "Logic" in tools
        assert "Connections" in tools
        assert "Interactions" in tools
        assert "Triggers" in tools

    def test_video_urls_not_in_resources(self, tmp_path):
        """Scenario 6: Video URLs filtered from resources."""
        links = [
            {"url": "https://youtube.com/watch?v=abc", "text": "Video",
             "source": "pptx", "term": 2, "lessons": [5]},
            {"url": "https://example.com/handout", "text": "Handout",
             "source": "pptx", "term": 2, "lessons": [5]},
        ]
        lesson_data = self._make_lesson_data(tmp_path, links=links)
        entry = build_lesson_kb(5, lesson_data, 2)

        resources = entry["metadata"]["resources"]
        for r in resources:
            assert "youtube.com" not in r

    def test_lesson_title_format(self, tmp_path):
        """Lesson title formatted correctly."""
        slides_md = """# Test

## Slide 1
Lesson 5 – Brainstorming and Concept Generation
"""
        lesson_data = self._make_lesson_data(tmp_path, slides_md=slides_md)
        entry = build_lesson_kb(5, lesson_data, 2)

        assert "Lesson 5" in entry["lesson_title"]

    def test_metadata_term_and_lesson_ids(self, tmp_path):
        """Metadata has correct term_id and lesson_id."""
        lesson_data = self._make_lesson_data(tmp_path)
        entry = build_lesson_kb(7, lesson_data, 3)

        assert entry["metadata"]["term_id"] == 3
        assert entry["metadata"]["lesson_id"] == 7


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
