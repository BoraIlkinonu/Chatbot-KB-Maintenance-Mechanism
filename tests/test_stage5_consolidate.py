"""
Stage 5 Tests: Consolidation — merge, dedup, assignment scenarios.
Tests path parsing, duplicate detection, link/video collection, and term/lesson assignment.
"""

import pytest
from pathlib import Path

from consolidate import (
    extract_term_from_path, extract_lesson_from_path, determine_content_type,
    normalize_name, levenshtein_ratio, detect_duplicates,
    collect_all_links, collect_all_video_refs, is_video_url, load_video_files,
)
from config import WEEK_LESSON_MAP


class TestExtractTermFromPath:
    """Test term number extraction from file paths."""

    def test_term_key_prefix(self):
        assert extract_term_from_path("term1/Lesson 1/slides.pptx") == 1
        assert extract_term_from_path("term2/Lesson 5/handout.pdf") == 2
        assert extract_term_from_path("term3/Week 3/doc.docx") == 3

    def test_descriptive_folder_names(self):
        assert extract_term_from_path("Term 1 - Foundations/file.pptx") == 1
        assert extract_term_from_path("Term 2 - Accelerator/file.pptx") == 2
        assert extract_term_from_path("Mastery/file.pptx") == 3

    def test_no_term_returns_none(self):
        assert extract_term_from_path("random/path/file.pptx") is None
        assert extract_term_from_path("file.pptx") is None

    def test_backslash_paths(self):
        assert extract_term_from_path("term1\\Lesson 1\\slides.pptx") == 1


class TestExtractLessonFromPath:
    """Test lesson number extraction from file paths."""

    def test_explicit_lesson_number(self):
        assert extract_lesson_from_path("Lesson 5/slides.pptx") == [5]
        assert extract_lesson_from_path("Lesson_12/file.pdf") == [12]
        assert extract_lesson_from_path("lesson-3/doc.docx") == [3]

    def test_lesson_range(self):
        result = extract_lesson_from_path("Lessons 3-5/file.pptx")
        assert result == [3, 4, 5]

    def test_week_folder_mapping(self):
        """Scenario 11: Week folder → multi-lesson mapping."""
        result = extract_lesson_from_path("Week 3/slides.pptx")
        assert result == WEEK_LESSON_MAP[3], f"Week 3 should map to {WEEK_LESSON_MAP[3]}"

        result = extract_lesson_from_path("Week 1/file.pdf")
        assert result == WEEK_LESSON_MAP[1]

    def test_portfolio_all_lessons(self):
        """Scenario 12: Portfolio file → all lessons."""
        result = extract_lesson_from_path("Portfolio/overview.pptx", term=2)
        assert len(result) > 5, "Portfolio should map to all lessons in term"

    def test_no_lesson_returns_empty(self):
        """Scenario 3: File with no lesson number → goes to unassigned."""
        result = extract_lesson_from_path("random_file.pptx")
        assert result == []

    def test_lesson_number_bounds(self):
        """Lesson number within term bounds."""
        # Term 2 has max 12 lessons
        result = extract_lesson_from_path("Lesson 15/file.pptx", term=2)
        # Should not match because 15 > 12
        assert result == []


class TestDetermineContentType:
    """Test content type classification."""

    def test_teachers_slides(self):
        assert determine_content_type("term1/Lesson 1/Teachers Slides.md") == "teachers_slides"

    def test_students_slides(self):
        assert determine_content_type("term2/Lesson 5/Students Slides.md") == "students_slides"

    def test_lesson_plan(self):
        assert determine_content_type("term3/Lesson 3/Lesson Plan.md") == "lesson_plan"

    def test_portfolio(self):
        assert determine_content_type("term1/Portfolio/overview.md") == "portfolio"

    def test_other(self):
        assert determine_content_type("term1/random_file.md") == "other"


class TestDuplicateDetection:
    """Test 3-layer duplicate detection."""

    def test_exact_name_duplicate(self):
        items = [
            {"name": "Lesson 5 Teachers Slides.pptx", "id": "a", "md5": "abc"},
            {"name": "Lesson 5 Teachers Slides.pptx", "id": "b", "md5": "def"},
        ]
        dups = detect_duplicates(items)
        assert len(dups) >= 1
        assert dups[0]["type"] == "exact_name"

    def test_near_duplicate_fuzzy_name(self):
        """Scenario 1: Near-duplicate files (85%+ name similarity)."""
        items = [
            {"name": "Lesson 5 Teachers Slides.pptx", "id": "a", "md5": "abc"},
            {"name": "Lesson 5 Teacher Slides.pptx", "id": "b", "md5": "def"},
        ]
        dups = detect_duplicates(items)
        fuzzy_dups = [d for d in dups if d["type"] == "fuzzy_name"]
        assert len(fuzzy_dups) >= 1, "Near-duplicate names should be detected"

    def test_md5_duplicate(self):
        """Scenario 2: Same MD5 hash detected as duplicate."""
        items = [
            {"name": "file_a.pptx", "id": "a", "md5": "same_hash"},
            {"name": "completely_different_name.pptx", "id": "b", "md5": "same_hash"},
        ]
        dups = detect_duplicates(items)
        md5_dups = [d for d in dups if d["type"] == "md5_content"]
        assert len(md5_dups) >= 1, "MD5 duplicates should be detected"

    def test_no_duplicates(self):
        items = [
            {"name": "file_a.pptx", "id": "a", "md5": "hash_a"},
            {"name": "file_b.pptx", "id": "b", "md5": "hash_b"},
            {"name": "file_c.pptx", "id": "c", "md5": "hash_c"},
        ]
        dups = detect_duplicates(items)
        assert dups == []


class TestLevenshteinRatio:
    """Test Levenshtein similarity calculation."""

    def test_identical_strings(self):
        assert levenshtein_ratio("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert levenshtein_ratio("", "") == 0
        assert levenshtein_ratio("hello", "") == 0

    def test_similar_strings(self):
        ratio = levenshtein_ratio("teachers slides", "teacher slides")
        assert ratio >= 0.85, f"Ratio {ratio} should be >= 0.85"

    def test_different_strings(self):
        ratio = levenshtein_ratio("hello world", "completely different")
        assert ratio < 0.5


class TestNormalizeName:
    """Test filename normalization for fuzzy matching."""

    def test_removes_copy_numbers(self):
        assert "file" in normalize_name("file (1).pptx")
        assert "file" in normalize_name("file (2).pptx")

    def test_normalizes_separators(self):
        result = normalize_name("my-file_name here.pptx")
        assert " " in result
        assert "-" not in result
        assert "_" not in result

    def test_removes_extension(self):
        result = normalize_name("document.pptx")
        assert ".pptx" not in result


class TestIsVideoUrl:
    """Test video URL pattern matching."""

    def test_youtube_watch(self):
        """Scenario 6: YouTube URL classified as video_ref."""
        assert is_video_url("https://www.youtube.com/watch?v=abc123") is True

    def test_youtube_short(self):
        assert is_video_url("https://youtu.be/abc123") is True

    def test_vimeo(self):
        assert is_video_url("https://vimeo.com/123456") is True

    def test_drive_video(self):
        assert is_video_url("https://drive.google.com/file/d/abc123") is True

    def test_non_video_url(self):
        assert is_video_url("https://example.com/page") is False
        assert is_video_url("https://google.com/docs/d/abc") is False


class TestCollectAllLinks:
    """Test link merging from all sources."""

    def test_merge_pptx_and_native_links(self):
        """Scenario 7: Duplicate URLs across sources — both kept in links."""
        pptx_links = [
            {"url": "https://example.com", "text": "Link", "source": "pptx",
             "term": 1, "lessons": [1]},
        ]
        native_extractions = [
            {
                "native_type": "google_slides",
                "file_name": "Slides.gslides",
                "source_path": "term1/Lesson 1/Slides",
                "term": "term1",
                "slides": [
                    {"links": [{"url": "https://example.com", "text": "Same Link", "slide_number": 1}]},
                ],
            },
        ]
        pdf_links = []

        all_links = collect_all_links(pptx_links, native_extractions, pdf_links)

        assert len(all_links) >= 2, "Same URL from different sources should both be kept"
        sources = [l.get("source") for l in all_links]
        assert "pptx" in sources
        assert "native_slides" in sources

    def test_native_doc_links_collected(self):
        native_extractions = [
            {
                "native_type": "google_doc",
                "file_name": "Lesson Plan.gdoc",
                "source_path": "term3/Lesson 3/Lesson Plan",
                "term": "term3",
                "links": [
                    {"url": "https://doc-link.com", "text": "Doc Link"},
                ],
            },
        ]

        all_links = collect_all_links([], native_extractions, [])

        assert len(all_links) >= 1
        assert all_links[0]["source"] == "native_doc"
        assert all_links[0]["url"] == "https://doc-link.com"

    def test_empty_sources(self):
        """Scenario 9: Empty native extractions — no crash, empty links."""
        all_links = collect_all_links([], [], [])
        assert all_links == []

    def test_links_without_term(self):
        """Scenario 8: Links with no term assignment — still collected."""
        pptx_links = [
            {"url": "https://example.com", "text": "No term", "source": "pptx",
             "term": None, "lessons": []},
        ]
        all_links = collect_all_links(pptx_links, [], [])
        assert len(all_links) == 1


class TestCollectAllVideoRefs:
    """Test video reference merging from all sources."""

    def test_video_files_collected(self):
        """Scenario 4: Video file in lesson folder mapped to correct term/lesson."""
        video_files = [
            {
                "filename": "demo.mp4", "path": "/sources/term2/Lesson 5/demo.mp4",
                "relative_path": "term2/Lesson 5/demo.mp4",
                "size_bytes": 10000, "extension": ".mp4",
                "term": 2, "lessons": [5], "source": "video_file",
            },
        ]

        refs = collect_all_video_refs(video_files, [], [])

        assert len(refs) >= 1
        assert refs[0]["type"] == "video_file"
        assert refs[0]["term"] == 2
        assert 5 in refs[0]["lessons"]

    def test_embedded_videos_collected(self):
        native_extractions = [
            {
                "native_type": "google_slides",
                "file_name": "Slides.gslides",
                "source_path": "term3/Lesson 6/Slides",
                "term": "term3",
                "slides": [
                    {"videos": [{"url": "https://youtube.com/watch?v=xyz", "video_id": "xyz", "slide_number": 3}]},
                ],
            },
        ]

        refs = collect_all_video_refs([], native_extractions, [])

        assert len(refs) >= 1
        assert refs[0]["type"] == "embedded_video"
        assert refs[0]["url"] == "https://youtube.com/watch?v=xyz"

    def test_youtube_links_become_video_refs(self):
        """Scenario 6: YouTube URL in links classified as video_ref."""
        all_links = [
            {"url": "https://youtube.com/watch?v=abc", "text": "Tutorial",
             "source": "pptx", "source_file": "slides.pptx", "term": 2, "lessons": [5]},
        ]

        refs = collect_all_video_refs([], [], all_links)

        assert len(refs) >= 1
        assert refs[0]["type"] == "video_link"
        assert refs[0]["url"] == "https://youtube.com/watch?v=abc"

    def test_duplicate_video_urls_deduped(self):
        """Same YouTube URL from multiple links — only one video_ref."""
        all_links = [
            {"url": "https://youtube.com/watch?v=same", "text": "Link 1",
             "source": "pptx", "source_file": "a.pptx", "term": 1, "lessons": [1]},
            {"url": "https://youtube.com/watch?v=same", "text": "Link 2",
             "source": "pdf", "source_file": "b.pdf", "term": 1, "lessons": [1]},
        ]

        refs = collect_all_video_refs([], [], all_links)

        video_link_refs = [r for r in refs if r["type"] == "video_link"]
        assert len(video_link_refs) == 1, "Duplicate video URLs should be deduped"

    def test_video_file_ambiguous_path(self):
        """Scenario 5: Video file in ambiguous path — term detected but no lesson."""
        video_files = [
            {
                "filename": "overview.mp4", "path": "/sources/term2/overview.mp4",
                "relative_path": "term2/overview.mp4",
                "size_bytes": 5000, "extension": ".mp4",
                "term": 2, "lessons": [], "source": "video_file",
            },
        ]

        refs = collect_all_video_refs(video_files, [], [])

        assert len(refs) >= 1
        assert refs[0]["term"] == 2
        assert refs[0]["lessons"] == []


class TestLoadVideoFiles:
    """Test video file scanning from sources directory."""

    def test_finds_video_files(self, tmp_path, monkeypatch):
        """Scenario 4: Video files in lesson folder found and mapped."""
        import config
        import consolidate
        sources = tmp_path / "sources"
        lesson_dir = sources / "term2" / "Lesson 11"
        lesson_dir.mkdir(parents=True)

        from tests.fixtures import create_video_file
        create_video_file(lesson_dir / "demo.mp4")

        monkeypatch.setattr(config, "SOURCES_DIR", sources)
        monkeypatch.setattr(consolidate, "SOURCES_DIR", sources)

        videos = load_video_files()

        assert len(videos) >= 1
        assert videos[0]["filename"] == "demo.mp4"
        assert videos[0]["term"] == 2
        assert 11 in videos[0]["lessons"]

    def test_no_videos_in_empty_dir(self, tmp_path, monkeypatch):
        import config
        import consolidate
        sources = tmp_path / "sources"
        sources.mkdir()
        monkeypatch.setattr(config, "SOURCES_DIR", sources)
        monkeypatch.setattr(consolidate, "SOURCES_DIR", sources)

        videos = load_video_files()
        assert videos == []
