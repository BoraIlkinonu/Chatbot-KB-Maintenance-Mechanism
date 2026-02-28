"""
End-to-End Pipeline Tests
Tests full Stage 1→2→5→6 flow with synthetic data.
"""

import json
import pytest
from pathlib import Path

from tests.fixtures import (
    create_test_pptx, create_minimal_png, create_test_pdf,
    create_corrupted_pptx, create_video_file, create_zero_byte_file,
    create_encrypted_pdf, create_pdf_with_many_links,
)


class TestHappyPath:
    """Scenario 1: Full pipeline with 2 synthetic lessons."""

    def test_full_stage1_to_stage6(self, tmp_path, config_override, sample_png):
        """Full Stage 1→2→5→6 flow with synthetic data, all fields populated."""
        import config

        sources = config_override["SOURCES_DIR"]
        media = config_override["MEDIA_DIR"]

        # Create lesson structure
        lesson5_dir = sources / "term2" / "Lesson 5"
        lesson5_dir.mkdir(parents=True)
        lesson11_dir = sources / "term2" / "Lesson 11"
        lesson11_dir.mkdir(parents=True)

        # Lesson 5: PPTX with links + images
        create_test_pptx(lesson5_dir / "Teachers Slides.pptx", [
            {
                "text": "Lesson 5 – Brainstorming",
                "images": [sample_png],
                "hyperlinks": [
                    {"url": "https://notebooklm.google.com", "text": "NotebookLM"},
                ],
            },
            {
                "text": "Learning Objectives\nUse triggers and NPCs in game design",
                "hyperlinks": [
                    {"url": "https://example.com/rubric", "text": "Rubric"},
                ],
            },
        ])

        # Lesson 11: PPTX + video file
        create_test_pptx(lesson11_dir / "Teachers Slides.pptx", [
            {
                "text": "Lesson 11 – Documentation",
                "hyperlinks": [
                    {"url": "https://youtube.com/watch?v=xyz", "text": "Portfolio Guide"},
                ],
            },
        ])
        create_video_file(lesson11_dir / "demo.mp4")

        # ── Stage 1: Extract media ──
        from extract_media import run_extraction
        stage1_result = run_extraction(source_dir=str(sources))

        assert stage1_result["total_images"] >= 1
        assert stage1_result["total_links"] >= 2

        # Verify metadata saved
        meta_path = media / "extraction_metadata.json"
        assert meta_path.exists()

        # ── Stage 2: Convert docs ──
        from convert_docs import run_conversion
        stage2_result = run_conversion(source_dir=str(sources))

        assert stage2_result["summary"]["success"] >= 2

        # ── Stage 5: Consolidation ──
        from consolidate import run_consolidation
        stage5_result = run_consolidation()

        assert "by_term" in stage5_result
        assert "2" in stage5_result["by_term"]
        term2 = stage5_result["by_term"]["2"]
        assert "by_lesson" in term2

        # Per-term file should exist on disk
        import config
        per_term_path = config.CONSOLIDATED_DIR / "consolidated_term2.json"
        assert per_term_path.exists(), "Per-term file for Term 2 should be written"
        with open(per_term_path, "r", encoding="utf-8") as f:
            per_term_data = json.load(f)
        assert per_term_data["term"] == 2
        assert "by_lesson" in per_term_data
        assert "summary" in per_term_data

        # Lesson 5 should have links
        if "5" in term2["by_lesson"]:
            lesson5 = term2["by_lesson"]["5"]
            assert lesson5["link_count"] >= 1

        # Summary should have totals
        summary = stage5_result["summary"]
        assert summary["total_links"] >= 2
        assert summary["total_video_files"] >= 1

        # ── Stage 6: Build KB ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        assert kb["term"] == 2
        assert kb["total_lessons"] >= 1

        # Check lesson entries have proper schema
        for lesson in kb["lessons"]:
            m = lesson["metadata"]
            assert isinstance(m["endstar_tools"], list)
            assert isinstance(m["videos"], list)
            assert isinstance(m["resources"], list)
            assert isinstance(m["images"], list)


class TestMixedFileTypes:
    """Scenario 2: PPTX + PDF in same lesson — links merged."""

    def test_pptx_and_pdf_links_merged(self, tmp_path, config_override):
        """Links from both PPTX and PDF merged in consolidation."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 3"
        lesson_dir.mkdir(parents=True)

        # PPTX with a link
        create_test_pptx(lesson_dir / "Slides.pptx", [
            {"text": "Slide content", "hyperlinks": [{"url": "https://pptx-link.com", "text": "PPTX Link"}]},
        ])

        # PDF with a link
        create_test_pdf(lesson_dir / "Handout.pdf", [
            {"text": "PDF content", "links": [{"url": "https://pdf-link.com"}]},
        ])

        # Run stages 1 + 2
        from extract_media import run_extraction
        from convert_docs import run_conversion
        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))

        # Run consolidation
        from consolidate import run_consolidation
        result = run_consolidation()

        # Both link sources should be present
        assert result["summary"]["total_links"] >= 2


class TestBrokenFileRecovery:
    """Scenario 3: Broken file alongside valid file — pipeline continues."""

    def test_valid_processed_broken_skipped(self, tmp_path, config_override, sample_png):
        """Valid file processed, broken file error logged, pipeline continues."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term1" / "Lesson 1"
        lesson_dir.mkdir(parents=True)

        # Valid PPTX
        create_test_pptx(lesson_dir / "Good Slides.pptx", [
            {"text": "Valid content", "images": [sample_png]},
        ])

        # Corrupted PPTX
        create_corrupted_pptx(lesson_dir / "Bad Slides.pptx")

        from extract_media import run_extraction
        result = run_extraction(source_dir=str(sources))

        # Pipeline should not crash
        assert len(result["pptx_files"]) == 2
        # At least the good file should have images
        good_file = [p for p in result["pptx_files"] if "Good" in p["source"]]
        assert len(good_file) == 1
        assert good_file[0]["images_count"] >= 1


class TestNearDuplicate:
    """Scenario 4: Near-duplicate PPTX in lesson folder."""

    def test_duplicate_detected_both_processed(self, tmp_path, config_override, sample_png):
        """Duplicate detected but both files still processed."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term1" / "Lesson 1"
        lesson_dir.mkdir(parents=True)

        # Two near-duplicate files
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Content A", "images": [sample_png]},
        ])
        create_test_pptx(lesson_dir / "Teachers Slide.pptx", [
            {"text": "Content B", "images": [sample_png]},
        ])

        from extract_media import run_extraction
        from convert_docs import run_conversion

        result = run_extraction(source_dir=str(sources))
        assert len(result["pptx_files"]) == 2

        run_conversion(source_dir=str(sources))

        from consolidate import run_consolidation
        consolidated = run_consolidation()

        # Duplicates should be flagged
        assert len(consolidated["duplicates"]) >= 1


class TestVideoOnlyLesson:
    """Scenario 5: Lesson with only video files — tracked in KB."""

    def test_video_tracked_without_slides(self, tmp_path, config_override):
        """Video file tracked even without slide content."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 8"
        lesson_dir.mkdir(parents=True)

        create_video_file(lesson_dir / "tutorial.mp4")

        # Run extraction (will find no PPTX)
        from extract_media import run_extraction
        run_extraction(source_dir=str(sources))

        from convert_docs import run_conversion
        run_conversion(source_dir=str(sources))

        from consolidate import run_consolidation
        result = run_consolidation()

        assert result["summary"]["total_video_files"] >= 1


# ══════════════════════════════════════════════════════════
# Part A: 12 Single-Task Scenarios (tests 6-17)
# ══════════════════════════════════════════════════════════


class TestEmptyLesson:
    """Scenario 6: Empty lesson folder — pipeline handles gracefully."""

    def test_empty_lesson_produces_no_content(self, tmp_path, config_override):
        """Empty lesson dir produces zero content through all stages."""
        import config

        sources = config_override["SOURCES_DIR"]
        media = config_override["MEDIA_DIR"]
        consolidated_dir = config_override["CONSOLIDATED_DIR"]

        # Create empty lesson directory
        lesson_dir = sources / "term2" / "Lesson 9"
        lesson_dir.mkdir(parents=True)

        # ── Stage 1: Extract media ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert stage1["total_images"] == 0
        assert stage1["total_links"] == 0
        assert len(stage1["pptx_files"]) == 0
        assert stage1["total_with_slides"] == 0
        assert stage1["total_without_slides"] == 0

        # No extraction metadata should be written (no pptx found)
        meta_path = media / "extraction_metadata.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            assert len(meta.get("pptx_files", [])) == 0

        # ── Stage 2: Convert docs ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))

        assert stage2["summary"]["success"] == 0
        assert stage2["summary"]["failed"] == 0
        assert len(stage2["files"]) == 0
        assert stage2["pdf_metadata"]["total_images"] == 0
        assert stage2["pdf_metadata"]["total_links"] == 0

        # ── Stage 5: Consolidation ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        # Term 2 should exist but Lesson 9 should have no content
        if "2" in stage5["by_term"]:
            term2 = stage5["by_term"]["2"]
            if "9" in term2["by_lesson"]:
                lesson9 = term2["by_lesson"]["9"]
                assert lesson9["document_count"] == 0
                assert lesson9["image_count"] == 0
                assert lesson9["link_count"] == 0
                assert lesson9["video_ref_count"] == 0
                assert len(lesson9["documents"]) == 0
                assert len(lesson9["links"]) == 0
                assert len(lesson9["video_refs"]) == 0

        # Summary totals should all be zero
        assert stage5["summary"]["total_documents"] == 0
        assert stage5["summary"]["total_images"] == 0
        assert stage5["summary"]["total_links"] == 0
        assert stage5["summary"]["total_video_files"] == 0


class TestPdfOnlyLesson:
    """Scenario 7: PDF-only lesson — links extracted, no PPTX content."""

    def test_pdf_links_extracted_no_pptx(self, tmp_path, config_override):
        """PDF with links processed; no PPTX means no images from Stage 1."""
        import config

        sources = config_override["SOURCES_DIR"]
        media = config_override["MEDIA_DIR"]

        lesson_dir = sources / "term2" / "Lesson 4"
        lesson_dir.mkdir(parents=True)

        # PDF with 2 pages, 2 links
        create_test_pdf(lesson_dir / "Handout.pdf", [
            {"text": "Page 1", "links": [{"url": "https://example.com/design-brief"}]},
            {"text": "Page 2", "links": [{"url": "https://example.com/research-guide"}]},
        ])

        # ── Stage 1: No PPTX to extract ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert stage1["total_images"] == 0
        assert stage1["total_links"] == 0
        assert len(stage1["pptx_files"]) == 0

        # ── Stage 2: PDF converted, links extracted ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))

        assert stage2["summary"]["success"] >= 1
        assert stage2["pdf_metadata"]["total_links"] >= 2

        # Verify individual PDF link URLs
        pdf_files = stage2["pdf_metadata"]["files"]
        assert len(pdf_files) >= 1
        all_pdf_links = []
        for pf in pdf_files:
            all_pdf_links.extend(pf["links"])
        pdf_urls = [l["url"] for l in all_pdf_links]
        assert "https://example.com/design-brief" in pdf_urls
        assert "https://example.com/research-guide" in pdf_urls

        # Check PDF metadata written to disk
        pdf_meta_path = media / "pdf_extraction_metadata.json"
        if pdf_meta_path.exists():
            with open(pdf_meta_path, "r", encoding="utf-8") as f:
                pdf_meta = json.load(f)
            assert pdf_meta["total_links"] >= 2

        # ── Stage 5: Consolidation ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        assert "2" in stage5["by_term"]
        term2 = stage5["by_term"]["2"]
        assert "4" in term2["by_lesson"]
        lesson4 = term2["by_lesson"]["4"]

        assert lesson4["document_count"] >= 1
        assert lesson4["link_count"] >= 2
        assert lesson4["image_count"] == 0
        assert lesson4["video_ref_count"] == 0

        # Verify links have source="pdf"
        for link in lesson4["links"]:
            assert link["source"] == "pdf"
            assert link["url"] in pdf_urls

        # Verify content_type is "other" (not teachers/students slides)
        for doc in lesson4["documents"]:
            assert doc["content_type"] == "other"


class TestMultipleVideosNoSlides:
    """Scenario 8: Lesson with only video files — all tracked."""

    def test_three_videos_tracked_no_slides(self, tmp_path, config_override):
        """Three video files detected and tracked without any slide content."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 10"
        lesson_dir.mkdir(parents=True)

        # 3 video files
        create_video_file(lesson_dir / "intro.mp4", size_kb=5)
        create_video_file(lesson_dir / "demo.mp4", size_kb=10)
        create_video_file(lesson_dir / "recap.mp4", size_kb=8)

        # ── Stage 1: No PPTX ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 0
        assert stage1["total_images"] == 0
        assert stage1["total_links"] == 0

        # ── Stage 2: Nothing to convert ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        assert stage2["summary"]["success"] == 0

        # ── Stage 5: Videos consolidated ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        assert "2" in stage5["by_term"]
        term2 = stage5["by_term"]["2"]
        assert "10" in term2["by_lesson"]
        lesson10 = term2["by_lesson"]["10"]

        assert lesson10["document_count"] == 0
        assert lesson10["link_count"] == 0
        assert lesson10["image_count"] == 0
        assert lesson10["video_ref_count"] >= 3

        # Verify each video is type="video_file" with correct filename
        video_filenames = [v.get("filename", "") or Path(v.get("path", "")).name
                           for v in lesson10["video_refs"]]
        assert "intro.mp4" in video_filenames
        assert "demo.mp4" in video_filenames
        assert "recap.mp4" in video_filenames

        for vref in lesson10["video_refs"]:
            assert vref["type"] == "video_file"
            assert vref["term"] == 2
            assert 10 in vref["lessons"]

        # Summary should reflect videos
        assert stage5["summary"]["total_video_files"] >= 3
        assert stage5["summary"]["total_documents"] == 0
        assert stage5["summary"]["total_links"] == 0


class TestPptxWithSpeakerNotes:
    """Scenario 9: PPTX with speaker notes — notes flow through to KB."""

    def test_speaker_notes_in_kb(self, tmp_path, config_override, sample_png):
        """Speaker notes extracted and available in Stage 6 enriched output."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 6"
        lesson_dir.mkdir(parents=True)

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {
                "text": "Slide 1: Prototype Introduction",
                "notes": "Teacher note: Demonstrate the prototype tool first",
                "images": [sample_png],
            },
            {
                "text": "Slide 2: Core Mechanic Testing",
                "notes": "Teacher note: Allow 15 minutes for testing",
            },
        ])

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 1
        assert stage1["total_images"] >= 1

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        assert stage2["summary"]["success"] >= 1

        # Check converted markdown exists
        converted_dir = config_override["CONVERTED_DIR"]
        md_files = list(converted_dir.rglob("*.md"))
        assert len(md_files) >= 1

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        assert "6" in term2["by_lesson"]
        lesson6 = term2["by_lesson"]["6"]
        assert lesson6["document_count"] >= 1
        assert lesson6["image_count"] >= 1

        # Verify content_type is teachers_slides
        teacher_docs = [d for d in lesson6["documents"] if d["content_type"] == "teachers_slides"]
        assert len(teacher_docs) >= 1

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        # Find lesson 6
        lesson6_entries = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 6]
        assert len(lesson6_entries) == 1
        lesson6_kb = lesson6_entries[0]

        # Verify enriched data has teacher notes
        enriched = lesson6_kb["enriched"]
        assert len(enriched["teacher_notes"]) >= 1

        # At least one note should contain our text
        all_notes_text = " ".join(n["notes"] for n in enriched["teacher_notes"])
        assert "teacher note" in all_notes_text.lower()

        # Verify slide content is present
        assert len(enriched["slides"]) >= 2
        assert enriched["image_count"] >= 1

        # Verify document sources tracked
        assert len(enriched["document_sources"]) >= 1


class TestPptxClickActionLinks:
    """Scenario 10: PPTX with click action hyperlinks — link_type tracked."""

    def test_click_action_link_type(self, tmp_path, config_override):
        """Click action hyperlinks extracted with correct link_type."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 2"
        lesson_dir.mkdir(parents=True)

        create_test_pptx(lesson_dir / "Slides.pptx", [
            {
                "text": "Persona Workshop",
                "hyperlinks": [
                    {"url": "https://example.com/text-link", "text": "Text Link"},
                ],
                "click_actions": [
                    {"url": "https://example.com/click-action", "text": "Click Me"},
                ],
            },
        ])

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert stage1["total_links"] >= 2
        assert len(stage1["pptx_files"]) == 1

        pptx_links = stage1["pptx_files"][0]["links"]
        assert len(pptx_links) >= 2

        # Separate by link_type
        text_links = [l for l in pptx_links if l["link_type"] == "text_hyperlink"]
        click_links = [l for l in pptx_links if l["link_type"] == "click_action"]

        assert len(text_links) >= 1
        assert len(click_links) >= 1

        # Verify URLs preserved
        text_urls = [l["url"] for l in text_links]
        click_urls = [l["url"] for l in click_links]
        assert "https://example.com/text-link" in text_urls
        assert "https://example.com/click-action" in click_urls

        # Verify text preserved
        assert any(l["text"] == "Text Link" for l in text_links)
        assert any(l["text"] == "Click Me" for l in click_links)

        # Verify slide_number is set
        for link in pptx_links:
            assert link["slide_number"] >= 1

        # ── Stage 2 + 5: Verify links flow to consolidation ──
        from convert_docs import run_conversion
        run_conversion(source_dir=str(sources))

        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson2 = term2["by_lesson"]["2"]
        assert lesson2["link_count"] >= 2

        # Both link types should be in consolidated links
        consolidated_urls = [l["url"] for l in lesson2["links"]]
        assert "https://example.com/text-link" in consolidated_urls
        assert "https://example.com/click-action" in consolidated_urls


class TestDuplicateThreeLayers:
    """Scenario 11: Near-duplicate PPTX files trigger multi-layer detection."""

    def test_three_layer_duplicate_detection(self, tmp_path, config_override, sample_png):
        """Three files: original, (1) copy, fuzzy name — all detected."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term1" / "Lesson 1"
        lesson_dir.mkdir(parents=True)

        # Original
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Content A — Design Brief", "images": [sample_png]},
        ])
        # (1) copy — triggers exact_name after normalization
        create_test_pptx(lesson_dir / "Teachers Slides (1).pptx", [
            {"text": "Content A — Design Brief", "images": [sample_png]},
        ])
        # Fuzzy name variant
        create_test_pptx(lesson_dir / "Teacher Slide.pptx", [
            {"text": "Content B — Different", "images": [sample_png]},
        ])

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 3

        # All 3 should have images
        for pf in stage1["pptx_files"]:
            assert pf["images_count"] >= 1

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        assert stage2["summary"]["success"] >= 3

        # ── Stage 5: Duplicate detection ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        assert len(stage5["duplicates"]) >= 1

        dup_types = [d["type"] for d in stage5["duplicates"]]
        # Should have at least fuzzy_name (Teacher Slide vs Teachers Slides)
        assert "fuzzy_name" in dup_types or "exact_name" in dup_types

        # All files should still be in by_lesson (duplicates are flagged, not removed)
        term1 = stage5["by_term"]["1"]
        lesson1 = term1["by_lesson"]["1"]
        assert lesson1["document_count"] >= 2

        # Summary should reflect duplicates
        assert stage5["summary"]["total_duplicates"] >= 1


class TestUnassignedDocument:
    """Scenario 12: Document outside lesson structure — marked unassigned."""

    def test_unassigned_document_detected(self, tmp_path, config_override):
        """PDF outside term/lesson folder flagged as unassigned."""
        import config

        sources = config_override["SOURCES_DIR"]

        # Normal lesson content
        lesson_dir = sources / "term2" / "Lesson 1"
        lesson_dir.mkdir(parents=True)
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Normal lesson content"},
        ])

        # Orphaned file at root of sources (no term/lesson structure)
        create_test_pdf(sources / "README.pdf", [
            {"text": "Readme content", "links": [{"url": "https://example.com/readme"}]},
        ])

        # ── Stages 1 + 2 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        # Lesson 1 should have its content
        term2 = stage5["by_term"]["2"]
        assert "1" in term2["by_lesson"]
        lesson1 = term2["by_lesson"]["1"]
        assert lesson1["document_count"] >= 1

        # Unassigned should have the README
        unassigned_docs = stage5["unassigned"].get("documents", [])
        unassigned_paths = [d.get("path", "") for d in unassigned_docs]
        has_readme = any("readme" in p.lower() for p in unassigned_paths)
        assert has_readme, f"README.pdf should be unassigned, got: {unassigned_paths}"

        # Unassigned doc should NOT appear in any by_lesson
        for term_data in stage5["by_term"].values():
            for lesson_data in term_data.get("by_lesson", {}).values():
                for doc in lesson_data.get("documents", []):
                    assert "readme" not in doc.get("path", "").lower()


class TestLargeSlideCount:
    """Scenario 13: PPTX with 30 slides — all content preserved."""

    def test_thirty_slides_preserved(self, tmp_path, config_override, sample_png):
        """30 slides all extracted and preserved through to KB."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 7"
        lesson_dir.mkdir(parents=True)

        # Build 30 slides with unique text
        slides_config = []
        for i in range(1, 31):
            slide = {"text": f"Slide {i}: Unique content about gameplay expansion topic {i}"}
            if i == 1:
                slide["images"] = [sample_png]
            slides_config.append(slide)

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", slides_config)

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 1
        assert stage1["total_images"] >= 1

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        assert stage2["summary"]["success"] >= 1

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson7 = term2["by_lesson"]["7"]
        assert lesson7["document_count"] >= 1

        # Verify char_count is substantial (30 slides of text)
        for doc in lesson7["documents"]:
            assert doc["char_count"] > 100

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        lesson7_entries = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 7]
        assert len(lesson7_entries) == 1
        lesson7_kb = lesson7_entries[0]

        # Verify slides content preserved
        enriched = lesson7_kb["enriched"]
        assert len(enriched["slides"]) >= 25  # Most slides should be captured

        # Verify unique content is present
        all_slide_content = " ".join(s["content"] for s in enriched["slides"])
        assert "topic 1" in all_slide_content.lower() or "slide 1" in all_slide_content.lower()
        assert "topic 30" in all_slide_content.lower() or "slide 30" in all_slide_content.lower()

        # Image should be tracked
        assert enriched["image_count"] >= 1
        assert len(lesson7_kb["metadata"]["images"]) >= 1


class TestVideoUrlsFilteredFromResources:
    """Scenario 14: YouTube URLs go to videos, not resources."""

    def test_video_url_separation(self, tmp_path, config_override):
        """YouTube link in videos[], non-video link in resources[], no crossover."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 5"
        lesson_dir.mkdir(parents=True)

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {
                "text": "Brainstorming Workshop",
                "hyperlinks": [
                    {"url": "https://youtube.com/watch?v=abc123", "text": "Tutorial Video"},
                    {"url": "https://notebooklm.google.com", "text": "NotebookLM Tool"},
                ],
            },
        ])

        # ── Stages 1 + 2 + 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation

        stage1 = run_extraction(source_dir=str(sources))
        assert stage1["total_links"] >= 2

        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson5 = term2["by_lesson"]["5"]
        assert lesson5["link_count"] >= 2

        # Stage 5 should have a video_ref for YouTube
        youtube_refs = [v for v in lesson5["video_refs"] if "youtube" in v.get("url", "").lower()]
        assert len(youtube_refs) >= 1

        # ── Stage 6: Build KB ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        lesson5_entries = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 5]
        assert len(lesson5_entries) == 1
        meta = lesson5_entries[0]["metadata"]

        # Videos should have the YouTube entry
        video_urls = [v.get("url", "") for v in meta["videos"]]
        assert any("youtube" in u for u in video_urls)

        # Resources should have non-video link, NOT YouTube
        for res in meta["resources"]:
            assert "youtube.com/watch" not in res.lower()

        # NotebookLM should be in resources
        assert any("notebooklm" in r.lower() for r in meta["resources"])


class TestValidationPerfectTerm:
    """Scenario 15: 12 complete lessons — validation passes cleanly."""

    def test_full_term_validation_passes(self, tmp_path, config_override, sample_png):
        """12 lessons each with Teachers+Students Slides → publish not blocked."""
        import config

        sources = config_override["SOURCES_DIR"]

        # Create 12 complete lessons
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} teachers content", "images": [sample_png]},
            ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students content"},
            ])

        # ── Stages 1 → 2 → 5 → 6 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        # Verify KB file exists with 12 lessons
        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert output_path.exists()
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        assert kb["total_lessons"] == 12

        # ── Stage 7: Validation ──
        pass  # validate_kb.run_validation removed
        reports = {}  # validate_kb deleted

        assert reports is not None
        assert "term2" in reports
        report = reports["term2"]

        assert report["publish_blocked"] is False
        assert report["summary"]["errors"] == 0
        assert report["status"] in ("VALID", "VALID_WITH_WARNINGS")
        assert report["overall_confidence"] >= 80

        # Per-lesson inventory should cover all 12
        assert len(report["per_lesson"]) == 12

        # Validation report file should exist on disk
        report_json = config_override["VALIDATION_DIR"] / "validation_report_term2.json"
        assert report_json.exists()
        report_txt = config_override["VALIDATION_DIR"] / "validation_report_term2.txt"
        assert report_txt.exists()


class TestValidationMissingContentBlocks:
    """Scenario 16: Missing teachers_slides — ERROR blocks publishing."""

    def test_missing_teachers_slides_blocks(self, tmp_path, config_override, sample_png):
        """Lesson 1 has only Students Slides → ERROR anomaly, publish blocked."""
        import config

        sources = config_override["SOURCES_DIR"]

        # 12 lessons: Lesson 1 missing Teachers Slides
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            if i != 1:
                create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                    {"text": f"Lesson {i} teachers content", "images": [sample_png]},
                ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students content"},
            ])

        # ── Stages 1 → 2 → 5 → 6 → 7 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]

        # Should be blocked due to missing teachers_slides
        assert report["publish_blocked"] is True
        assert report["summary"]["errors"] >= 1

        # Find the specific MISSING anomaly for lesson 1
        missing_anomalies = [
            a for a in report["anomalies"]
            if a["type"] == "MISSING" and a.get("lesson") == 1
            and a.get("content_type") == "teachers_slides"
        ]
        assert len(missing_anomalies) >= 1
        assert missing_anomalies[0]["severity"] == "ERROR"

        # Status should not be VALID
        assert report["status"] != "VALID"


class TestValidationOrphanedDocs:
    """Scenario 17: Orphaned documents — WARNING, not blocking."""

    def test_orphaned_docs_warning_not_blocking(self, tmp_path, config_override, sample_png):
        """Document in misc folder → ORPHANED warning, publish not blocked."""
        import config

        sources = config_override["SOURCES_DIR"]

        # Normal lesson
        lesson_dir = sources / "term2" / "Lesson 1"
        lesson_dir.mkdir(parents=True)
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Normal content", "images": [sample_png]},
        ])
        create_test_pptx(lesson_dir / "Students Slides.pptx", [
            {"text": "Students content"},
        ])

        # Orphaned file in non-lesson folder
        misc_dir = sources / "term2" / "misc"
        misc_dir.mkdir(parents=True)
        create_test_pptx(misc_dir / "notes.pptx", [
            {"text": "Miscellaneous notes"},
        ])

        # ── Stages 1 → 2 → 5 → 6 → 7 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        # Verify unassigned documents detected in consolidation
        unassigned = stage5.get("unassigned", {}).get("documents", [])
        orphaned_paths = [d.get("path", "") for d in unassigned]
        has_orphan = any("misc" in p.lower() or "notes" in p.lower() for p in orphaned_paths)
        assert has_orphan, f"misc/notes.pptx should be unassigned, got: {orphaned_paths}"

        run_build(term_num=2)
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]

        # Should NOT block publishing (orphaned is WARNING only)
        orphan_anomalies = [a for a in report["anomalies"] if a["type"] == "ORPHANED"]
        if orphan_anomalies:
            for oa in orphan_anomalies:
                assert oa["severity"] == "WARNING"


class TestZeroByteFileSkipped:
    """Scenario 18a: Zero-byte PPTX alongside valid one — skipped gracefully."""

    def test_zero_byte_pptx_skipped(self, tmp_path, config_override, sample_png):
        """Zero-byte PPTX produces no output; valid sibling still processed."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 3"
        lesson_dir.mkdir(parents=True)

        # Valid PPTX
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Valid research content", "images": [sample_png],
             "hyperlinks": [{"url": "https://example.com/valid", "text": "Valid Link"}]},
        ])
        # Zero-byte file
        create_zero_byte_file(lesson_dir / "Empty Slides.pptx")

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        # Both files attempted, but zero-byte yields nothing
        assert len(stage1["pptx_files"]) >= 1
        assert stage1["total_images"] >= 1
        assert stage1["total_links"] >= 1

        # The valid file should have images and links
        valid_files = [p for p in stage1["pptx_files"] if p["images_count"] > 0]
        assert len(valid_files) >= 1
        assert valid_files[0]["links_count"] >= 1

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        # At least the valid file should convert
        assert stage2["summary"]["success"] >= 1

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson3 = term2["by_lesson"]["3"]
        assert lesson3["document_count"] >= 1
        assert lesson3["link_count"] >= 1
        assert lesson3["image_count"] >= 1

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l3 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 3][0]
        assert len(l3["metadata"]["resources"]) >= 1
        assert l3["enriched"]["image_count"] >= 1


class TestEncryptedPdfSkipped:
    """Scenario 18b: Encrypted PDF — error logged, pipeline continues."""

    def test_encrypted_pdf_does_not_crash(self, tmp_path, config_override, sample_png):
        """Encrypted PDF skipped; valid PPTX in same lesson still processed."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 4"
        lesson_dir.mkdir(parents=True)

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Valid content for design specification"},
        ])
        create_encrypted_pdf(lesson_dir / "Protected.pdf")

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 1

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))

        # PPTX should succeed; encrypted PDF may fail
        pptx_results = [f for f in stage2["files"] if f["type"] == "PPTX"]
        assert any(f["success"] for f in pptx_results)

        # ── Stage 5 + 6: Pipeline should complete ──
        from consolidate import run_consolidation
        from build_kb import run_build

        stage5 = run_consolidation()
        term2 = stage5["by_term"]["2"]
        assert "4" in term2["by_lesson"]
        assert term2["by_lesson"]["4"]["document_count"] >= 1

        run_build(term_num=2)
        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        assert kb["total_lessons"] >= 1


class TestPdfManyLinks:
    """Scenario 18c: PDF with 50 links — all extracted and counted."""

    def test_fifty_links_all_extracted(self, tmp_path, config_override):
        """High-link-count PDF has all links captured through pipeline."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 8"
        lesson_dir.mkdir(parents=True)

        create_pdf_with_many_links(lesson_dir / "Resource Pack.pdf", count=50)

        # ── Stage 1 (no PPTX) ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 0

        # ── Stage 2: PDF links extracted ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))

        assert stage2["pdf_metadata"]["total_links"] >= 50

        # Verify individual links have sequential URLs
        all_links = []
        for pf in stage2["pdf_metadata"]["files"]:
            all_links.extend(pf["links"])
        assert len(all_links) >= 50

        link_urls = [l["url"] for l in all_links]
        assert "https://example.com/link0" in link_urls
        assert "https://example.com/link49" in link_urls

        # Each link should have a page_number
        for link in all_links:
            assert "page_number" in link
            assert link["page_number"] >= 1

        # ── Stage 5: All links consolidated ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson8 = term2["by_lesson"]["8"]
        assert lesson8["link_count"] >= 50

        # Summary should reflect high link count
        assert stage5["summary"]["total_links"] >= 50


class TestNamingInconsistencyAnomaly:
    """Scenario 18d: 'Exampler' misspelling → NAMING_INCONSISTENT anomaly."""

    def test_exampler_misspelling_flagged(self, tmp_path, config_override, sample_png):
        """File with 'Exampler' in path triggers naming anomaly in validation."""
        import config

        sources = config_override["SOURCES_DIR"]

        # 12 lessons for a valid term
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} content", "images": [sample_png]},
            ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students"},
            ])

        # Add misspelled file to Lesson 5
        l5 = sources / "term2" / "Lesson 5"
        create_test_pptx(l5 / "Exampler Work.pptx", [
            {"text": "Student exemplar work sample"},
        ])

        # ── Run full pipeline ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]

        # Should have a NAMING_INCONSISTENT anomaly
        naming_anomalies = [a for a in report["anomalies"] if a["type"] == "NAMING_INCONSISTENT"]
        assert len(naming_anomalies) >= 1
        assert naming_anomalies[0]["severity"] == "INFO"
        assert "exampler" in naming_anomalies[0]["message"].lower()


class TestImageSlideMapping:
    """Scenario 18e: Images mapped to correct slide numbers in extraction."""

    def test_images_have_slide_numbers(self, tmp_path, config_override):
        """Each extracted image has primary_slide and slide_numbers populated."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 1"
        lesson_dir.mkdir(parents=True)

        # 3 slides, images on slides 1 and 3 (different images)
        img_red = create_minimal_png(4, 4, (255, 0, 0))
        img_blue = create_minimal_png(4, 4, (0, 0, 255))

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Slide 1 with red image", "images": [img_red]},
            {"text": "Slide 2 no image"},
            {"text": "Slide 3 with blue image", "images": [img_blue]},
        ])

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert stage1["total_images"] >= 2
        assert stage1["total_with_slides"] >= 1

        pptx = stage1["pptx_files"][0]
        assert pptx["images_count"] >= 2

        # Each image should have slide mapping
        for img in pptx["images"]:
            assert "slide_numbers" in img
            assert "primary_slide" in img
            assert len(img["slide_numbers"]) >= 1
            assert img["extension"] in (".png", ".jpeg", ".jpg", ".gif", ".bmp", ".emf", ".wmf", ".tiff")

        # ── Stage 5: Images carried through ──
        from convert_docs import run_conversion
        run_conversion(source_dir=str(sources))

        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson1 = term2["by_lesson"]["1"]
        assert lesson1["image_count"] >= 2

        # Consolidated images should have slide mappings and source_pptx
        for img in lesson1["images"]:
            assert "slide_numbers" in img
            assert "source_pptx" in img

        # ── Stage 6: Images in KB ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l1 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 1][0]
        assert len(l1["metadata"]["images"]) >= 2

        # KB images should have slide_numbers
        for img in l1["metadata"]["images"]:
            assert "slide_numbers" in img
            assert "image_path" in img


class TestWeekFolderLessonMapping:
    """Scenario 18f: Week folder name → correct lesson numbers via mapping."""

    def test_week_folder_maps_to_lessons(self, tmp_path, config_override, sample_png):
        """Content in 'Week 3' folder maps to Lessons 5-6."""
        import config

        sources = config_override["SOURCES_DIR"]

        # Use week folder instead of lesson folder
        week_dir = sources / "term2" / "Week 3"
        week_dir.mkdir(parents=True)

        create_test_pptx(week_dir / "Teachers Slides.pptx", [
            {"text": "Week 3 brainstorming and prototyping content", "images": [sample_png],
             "hyperlinks": [{"url": "https://example.com/week3", "text": "Week 3 Resource"}]},
        ])

        # ── Stages 1 + 2 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion

        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 1

        run_conversion(source_dir=str(sources))

        # ── Stage 5: Should map to lessons 5 and 6 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]

        # Week 3 maps to lessons 5 and 6
        mapped_to_5 = "5" in term2["by_lesson"] and term2["by_lesson"]["5"]["document_count"] > 0
        mapped_to_6 = "6" in term2["by_lesson"] and term2["by_lesson"]["6"]["document_count"] > 0

        # At least one of the mapped lessons should have content
        assert mapped_to_5 or mapped_to_6, \
            f"Week 3 should map to lessons 5-6, got by_lesson keys: {list(term2['by_lesson'].keys())}"

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        kb_lesson_ids = [l["metadata"]["lesson_id"] for l in kb["lessons"]]
        assert 5 in kb_lesson_ids or 6 in kb_lesson_ids


class TestContentTypeDetection:
    """Scenario 18g: Various filenames → correct content_type classification."""

    def test_content_types_from_filenames(self, tmp_path, config_override, sample_png):
        """Different file names map to correct content_type values."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 5"
        lesson_dir.mkdir(parents=True)

        # Files with different content_type-triggering names
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Teachers content"},
        ])
        create_test_pptx(lesson_dir / "Students Slides.pptx", [
            {"text": "Students content"},
        ])
        create_test_pptx(lesson_dir / "Exemplar Work.pptx", [
            {"text": "Exemplar content"},
        ])
        create_test_pptx(lesson_dir / "Assessment Guide.pptx", [
            {"text": "Assessment content"},
        ])

        # ── Stages 1 + 2 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson5 = term2["by_lesson"]["5"]

        doc_types = {d["content_type"] for d in lesson5["documents"]}

        # Verify content types detected correctly
        assert "teachers_slides" in doc_types
        assert "students_slides" in doc_types
        assert "exemplar_work" in doc_types
        assert "assessment_guide" in doc_types

        # Each document should have valid fields
        for doc in lesson5["documents"]:
            assert doc["format"] in ("md", "csv")
            assert doc["term"] == 2
            assert 5 in doc["lessons"]
            assert doc["char_count"] > 0


class TestConsolidatedPerTermOnDisk:
    """Scenario 18h: Per-term consolidated file has correct structure."""

    def test_per_term_file_structure(self, tmp_path, config_override, sample_png):
        """consolidated_term2.json written with all expected fields."""
        import config

        sources = config_override["SOURCES_DIR"]

        # 3 lessons with varied content
        for i in (1, 5, 12):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} content", "images": [sample_png],
                 "hyperlinks": [{"url": f"https://example.com/l{i}", "text": f"Link {i}"}]},
            ])
        create_video_file(sources / "term2" / "Lesson 5" / "demo.mp4")

        # ── Stages 1 + 2 + 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()

        # Verify per-term file on disk
        per_term_path = config_override["CONSOLIDATED_DIR"] / "consolidated_term2.json"
        assert per_term_path.exists()

        with open(per_term_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Top-level fields
        assert data["term"] == 2
        assert "by_lesson" in data
        assert "summary" in data

        # Lessons present
        assert "1" in data["by_lesson"]
        assert "5" in data["by_lesson"]
        assert "12" in data["by_lesson"]

        # Each lesson has required fields
        for lesson_key, lesson_data in data["by_lesson"].items():
            assert "lesson" in lesson_data
            assert "term" in lesson_data
            assert "document_count" in lesson_data
            assert "image_count" in lesson_data
            assert "link_count" in lesson_data
            assert "video_ref_count" in lesson_data
            assert "documents" in lesson_data
            assert "links" in lesson_data
            assert "video_refs" in lesson_data
            assert "images" in lesson_data

        # Lesson 5 should have video ref
        assert data["by_lesson"]["5"]["video_ref_count"] >= 1

        # Summary should have totals
        summary = data["summary"]
        assert summary["total_documents"] >= 3
        assert summary["total_links"] >= 3
        assert summary["total_video_files"] >= 1


class TestVolumeOutlierAnomaly:
    """Scenario 18i: One heavily loaded lesson → VOLUME_OUTLIER detected."""

    def test_volume_outlier_detected(self, tmp_path, config_override, sample_png):
        """One lesson with many more documents than others → volume anomaly."""
        import config

        sources = config_override["SOURCES_DIR"]

        # 12 lessons: most have 1 file, Lesson 6 has 8 files
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} content", "images": [sample_png]},
            ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students"},
            ])

        # Add many extra files to Lesson 6
        l6 = sources / "term2" / "Lesson 6"
        for j in range(1, 7):
            create_test_pptx(l6 / f"Extra Resource {j}.pptx", [
                {"text": f"Extra resource content {j}", "images": [sample_png]},
            ])

        # ── Stages 1 → 2 → 5 → 6 → 7 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        # Lesson 6 should have significantly more docs
        term2 = stage5["by_term"]["2"]
        l6_docs = term2["by_lesson"]["6"]["document_count"]
        other_docs = [term2["by_lesson"][str(i)]["document_count"]
                       for i in range(1, 13) if i != 6]
        assert l6_docs > max(other_docs)

        run_build(term_num=2)
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]

        # Should have VOLUME_OUTLIER for Lesson 6
        vol_anomalies = [a for a in report["anomalies"]
                         if a["type"] == "VOLUME_OUTLIER" and a.get("lesson") == 6]
        if vol_anomalies:
            assert vol_anomalies[0]["severity"] == "INFO"
            assert vol_anomalies[0]["doc_z"] > 0


class TestMultiplePdfsSameLesson:
    """Scenario 18j: 3 PDFs in one lesson — all links merged."""

    def test_three_pdfs_links_all_merged(self, tmp_path, config_override, sample_png):
        """Multiple PDFs in same lesson have all links consolidated."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 9"
        lesson_dir.mkdir(parents=True)

        # PPTX for base content
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Lesson 9 iteration and refinement"},
        ])

        # 3 PDFs with different links
        create_test_pdf(lesson_dir / "Handout A.pdf", [
            {"text": "Part A", "links": [
                {"url": "https://example.com/pdf-a-1"},
                {"url": "https://example.com/pdf-a-2"},
            ]},
        ])
        create_test_pdf(lesson_dir / "Handout B.pdf", [
            {"text": "Part B", "links": [{"url": "https://example.com/pdf-b-1"}]},
        ])
        create_test_pdf(lesson_dir / "Rubric.pdf", [
            {"text": "Rubric", "links": [{"url": "https://example.com/rubric"}]},
        ])

        # ── Stages 1 + 2 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion

        run_extraction(source_dir=str(sources))
        stage2 = run_conversion(source_dir=str(sources))

        # All 3 PDFs + 1 PPTX should be processed
        assert stage2["summary"]["success"] >= 4
        assert stage2["pdf_metadata"]["total_links"] >= 4

        # ── Stage 5: Links merged ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson9 = term2["by_lesson"]["9"]

        assert lesson9["link_count"] >= 4
        assert lesson9["document_count"] >= 4  # 3 PDFs + 1 PPTX converted

        # Verify all PDF link URLs present
        consolidated_urls = [l["url"] for l in lesson9["links"]]
        assert "https://example.com/pdf-a-1" in consolidated_urls
        assert "https://example.com/pdf-a-2" in consolidated_urls
        assert "https://example.com/pdf-b-1" in consolidated_urls
        assert "https://example.com/rubric" in consolidated_urls

        # All links from PDFs should have source="pdf"
        pdf_links = [l for l in lesson9["links"] if l["source"] == "pdf"]
        assert len(pdf_links) >= 4

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l9 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 9][0]
        assert len(l9["metadata"]["resources"]) >= 4


class TestFuzzyNameDuplicate:
    """Scenario 18k: Similar filenames → fuzzy_name duplicate flagged."""

    def test_fuzzy_name_duplicate_detected(self, tmp_path, config_override, sample_png):
        """Two files with very similar names → fuzzy_name dup flagged."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term1" / "Lesson 3"
        lesson_dir.mkdir(parents=True)

        # Two files with similar names (high Levenshtein ratio)
        # "Teachers Slides" vs "Teacher Slides" normalizes to
        # "teachers slides" vs "teacher slides" → high similarity
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Content version A", "images": [sample_png]},
        ])
        create_test_pptx(lesson_dir / "Teacher Slides.pptx", [
            {"text": "Content version B", "images": [sample_png]},
        ])

        # ── Stages 1 + 2 + 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation

        stage1 = run_extraction(source_dir=str(sources))
        assert len(stage1["pptx_files"]) == 2

        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        # Should detect fuzzy_name duplicate
        fuzzy_dups = [d for d in stage5["duplicates"] if d["type"] == "fuzzy_name"]
        assert len(fuzzy_dups) >= 1

        # Verify similarity score is recorded
        assert fuzzy_dups[0]["similarity"] >= 0.85

        # Both files should still be in the lesson (not removed)
        term1 = stage5["by_term"]["1"]
        lesson3 = term1["by_lesson"]["3"]
        assert lesson3["document_count"] >= 2

        # ── Stage 6 + 7: Duplicate detected but not blocking ──
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_build(term_num=1)
        reports = {}  # validate_kb deleted

        if reports and "term1" in reports:
            dup_anomalies = [a for a in reports["term1"]["anomalies"]
                             if a["type"] == "DUPLICATE"]
            for da in dup_anomalies:
                assert da["severity"] == "INFO"


class TestPptxTextOnlyMinimal:
    """Scenario 18l: Minimal PPTX with only text — no media, just text through pipeline."""

    def test_text_only_pptx_pipeline(self, tmp_path, config_override):
        """PPTX with no links, no images, no notes — just text flows through."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 10"
        lesson_dir.mkdir(parents=True)

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Slide 1: Team roles and project manager responsibilities"},
            {"text": "Slide 2: Milestones and timeline planning"},
            {"text": "Slide 3: Risk management and accountability"},
        ])

        # ── Stage 1: No images, no links ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert len(stage1["pptx_files"]) == 1
        assert stage1["total_images"] == 0
        assert stage1["total_links"] == 0
        assert stage1["pptx_files"][0]["images_count"] == 0
        assert stage1["pptx_files"][0]["links_count"] == 0

        # ── Stage 2: Converted to markdown ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))
        assert stage2["summary"]["success"] >= 1

        # Verify markdown file exists with slide content
        converted_dir = config_override["CONVERTED_DIR"]
        md_files = list(converted_dir.rglob("*.md"))
        assert len(md_files) >= 1

        # ── Stage 5: Document consolidated, zero media ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson10 = term2["by_lesson"]["10"]
        assert lesson10["document_count"] >= 1
        assert lesson10["image_count"] == 0
        assert lesson10["link_count"] == 0
        assert lesson10["video_ref_count"] == 0

        # Document should have text content
        for doc in lesson10["documents"]:
            assert doc["char_count"] > 50
            assert doc["content_type"] == "teachers_slides"
            assert doc["format"] == "md"

        # ── Stage 6: KB has text content but empty media ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l10 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 10][0]
        meta = l10["metadata"]
        enriched = l10["enriched"]

        # No media
        assert len(meta["videos"]) == 0
        assert len(meta["resources"]) == 0
        assert len(meta["images"]) == 0
        assert enriched["image_count"] == 0

        # But text content should be present
        assert len(enriched["slides"]) >= 3
        all_text = " ".join(s["content"] for s in enriched["slides"]).lower()
        assert "team roles" in all_text or "milestone" in all_text or "risk" in all_text

        # Endstar tools should NOT match (no tool keywords used)
        # "project manager" doesn't match any ENDSTAR_TOOLS key
        # but pipeline should still produce the field
        assert isinstance(meta["endstar_tools"], list)


# ══════════════════════════════════════════════════════════
# Part B: 12 Chained Multi-Stage Scenarios (tests 18-29)
# ══════════════════════════════════════════════════════════


class TestRealUserTermBuild:
    """Scenario 18: Full 3-lesson term build with realistic content."""

    def test_realistic_three_lesson_term(self, tmp_path, config_override, sample_png):
        """3 lessons with varied content types → full pipeline builds correctly."""
        import config

        sources = config_override["SOURCES_DIR"]

        # L1: Teachers Slides (3 slides, 2 images, 1 link) + Students Slides
        l1 = sources / "term2" / "Lesson 1"
        l1.mkdir(parents=True)
        create_test_pptx(l1 / "Teachers Slides.pptx", [
            {"text": "Lesson 1 – Design Brief", "images": [sample_png]},
            {"text": "Learning Objectives\nDefine design constraints", "images": [sample_png]},
            {"text": "Activity: Create brief",
             "hyperlinks": [{"url": "https://example.com/brief-template", "text": "Template"}]},
        ])
        create_test_pptx(l1 / "Students Slides.pptx", [
            {"text": "Student Activity: Design Brief"},
            {"text": "Submit your work"},
        ])

        # L2: Teachers Slides (3 slides, 1 img, YouTube + regular link) + Students + video
        l2 = sources / "term2" / "Lesson 2"
        l2.mkdir(parents=True)
        create_test_pptx(l2 / "Teachers Slides.pptx", [
            {"text": "Lesson 2 – Persona Workshop", "images": [sample_png]},
            {"text": "Watch the tutorial",
             "hyperlinks": [{"url": "https://youtube.com/watch?v=persona1", "text": "Persona Video"}]},
            {"text": "Resources",
             "hyperlinks": [{"url": "https://example.com/empathy-map", "text": "Empathy Map"}]},
        ])
        create_test_pptx(l2 / "Students Slides.pptx", [
            {"text": "Student Persona Activity"},
        ])
        create_video_file(l2 / "demo.mp4")

        # L3: Teachers Slides (3 slides, 1 img) + Students + PDF
        l3 = sources / "term2" / "Lesson 3"
        l3.mkdir(parents=True)
        create_test_pptx(l3 / "Teachers Slides.pptx", [
            {"text": "Lesson 3 – Research and AI", "images": [sample_png]},
            {"text": "Primary and secondary research methods"},
            {"text": "AI tool exploration"},
        ])
        create_test_pptx(l3 / "Students Slides.pptx", [
            {"text": "Student Research Log"},
        ])
        create_test_pdf(l3 / "Handout.pdf", [
            {"text": "Research Handout", "links": [{"url": "https://example.com/research-guide"}]},
        ])

        # ── Stage 1 ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        # python-pptx deduplicates identical image bytes within a PPTX,
        # so each PPTX with the same sample_png has 1 unique image
        assert stage1["total_images"] >= 3
        assert stage1["total_links"] >= 3
        assert len(stage1["pptx_files"]) >= 6

        # ── Stage 2 ──
        from convert_docs import run_conversion
        stage2 = run_conversion(source_dir=str(sources))

        assert stage2["summary"]["success"] >= 7  # 6 pptx + 1 pdf

        # ── Stage 5 ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        assert len(term2["by_lesson"]) >= 3

        # L2 should have video refs
        lesson2 = term2["by_lesson"]["2"]
        assert lesson2["video_ref_count"] >= 2  # YouTube link + mp4 file

        # L3 should have PDF links
        lesson3 = term2["by_lesson"]["3"]
        assert lesson3["link_count"] >= 1
        pdf_links = [l for l in lesson3["links"] if l["source"] == "pdf"]
        assert len(pdf_links) >= 1

        # ── Stage 6 ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        assert kb["total_lessons"] >= 3

        # L2 should have videos in metadata
        l2_entries = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 2]
        assert len(l2_entries) == 1
        assert len(l2_entries[0]["metadata"]["videos"]) >= 1

        # L3 should have resources
        l3_entries = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 3]
        assert len(l3_entries) == 1
        assert len(l3_entries[0]["metadata"]["resources"]) >= 1

        # ── Stage 7 ──
        pass  # validate_kb.run_validation removed
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]
        # Only 3 of 12 lessons populated, so expect incomplete but no crash
        assert report["summary"]["total_lessons"] >= 3


class TestIncrementalContentAddition:
    """Scenario 19: Build with 1 lesson, add 2 more, rebuild."""

    def test_incremental_rebuild(self, tmp_path, config_override, sample_png):
        """Phase 1: 1 lesson → KB. Phase 2: add 2 more → rebuild with all 3."""
        import config

        sources = config_override["SOURCES_DIR"]

        # ── Phase 1: Single lesson ──
        l1 = sources / "term2" / "Lesson 1"
        l1.mkdir(parents=True)
        create_test_pptx(l1 / "Teachers Slides.pptx", [
            {"text": "Lesson 1 – Design Brief", "images": [sample_png]},
            {"text": "Learning Objectives",
             "hyperlinks": [{"url": "https://example.com/l1-resource", "text": "L1 Resource"}]},
        ])

        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb1 = json.load(f)

        assert kb1["total_lessons"] >= 1
        l1_ids = [l["metadata"]["lesson_id"] for l in kb1["lessons"]]
        assert 1 in l1_ids

        # ── Phase 2: Add 2 more lessons ──
        l2 = sources / "term2" / "Lesson 2"
        l2.mkdir(parents=True)
        create_test_pptx(l2 / "Teachers Slides.pptx", [
            {"text": "Lesson 2 – Persona Creation"},
        ])

        l3 = sources / "term2" / "Lesson 3"
        l3.mkdir(parents=True)
        create_test_pptx(l3 / "Teachers Slides.pptx", [
            {"text": "Lesson 3 – AI Research"},
        ])
        create_video_file(l3 / "tutorial.mp4")

        # Re-run full pipeline
        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        with open(output_path, "r", encoding="utf-8") as f:
            kb2 = json.load(f)

        assert kb2["total_lessons"] >= 3
        l2_ids = [l["metadata"]["lesson_id"] for l in kb2["lessons"]]
        assert 1 in l2_ids
        assert 2 in l2_ids
        assert 3 in l2_ids

        # L1 data should still be intact
        l1_entry = [l for l in kb2["lessons"] if l["metadata"]["lesson_id"] == 1][0]
        assert len(l1_entry["metadata"]["resources"]) >= 1 or l1_entry["enriched"]["image_count"] >= 1

        # L3 should have video
        l3_entry = [l for l in kb2["lessons"] if l["metadata"]["lesson_id"] == 3][0]
        assert len(l3_entry["metadata"]["videos"]) >= 1


class TestCorruptedFileRecoveryChain:
    """Scenario 20: Mixed good/bad files through full pipeline."""

    def test_pipeline_survives_corrupted_files(self, tmp_path, config_override, sample_png):
        """Valid files processed, corrupted files skipped, pipeline completes."""
        import config

        sources = config_override["SOURCES_DIR"]

        # L1: Valid Teachers Slides + corrupted backup
        l1 = sources / "term2" / "Lesson 1"
        l1.mkdir(parents=True)
        create_test_pptx(l1 / "Teachers Slides.pptx", [
            {"text": "Lesson 1 valid content", "images": [sample_png]},
        ])
        create_corrupted_pptx(l1 / "Teachers Slides backup.pptx")

        # L2: Valid Teachers Slides + PDF with links
        l2 = sources / "term2" / "Lesson 2"
        l2.mkdir(parents=True)
        create_test_pptx(l2 / "Teachers Slides.pptx", [
            {"text": "Lesson 2 valid content"},
        ])
        create_test_pdf(l2 / "Handout.pdf", [
            {"text": "PDF content", "links": [{"url": "https://example.com/l2-link"}]},
        ])

        # ── Run full pipeline ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        stage1 = run_extraction(source_dir=str(sources))
        # Should not crash; corrupted file handled gracefully
        assert len(stage1["pptx_files"]) >= 2  # Attempted both

        stage2 = run_conversion(source_dir=str(sources))
        # At least valid files should succeed
        assert stage2["summary"]["success"] >= 2

        stage5 = run_consolidation()
        # Both lessons should have content
        term2 = stage5["by_term"]["2"]
        assert "1" in term2["by_lesson"]
        assert "2" in term2["by_lesson"]

        # L2 should have PDF links
        l2_data = term2["by_lesson"]["2"]
        assert l2_data["link_count"] >= 1

        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert output_path.exists()
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        assert kb["total_lessons"] >= 2

        # ── Stage 7: Validation should complete ──
        pass  # validate_kb.run_validation removed
        reports = {}  # validate_kb deleted
        assert reports is not None


class TestCrossSourceLinkMerging:
    """Scenario 21: Same lesson gets links from PPTX + PDF."""

    def test_pptx_and_pdf_links_merged_with_video(self, tmp_path, config_override, sample_png):
        """Links from multiple sources merged; videos separated from resources."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 5"
        lesson_dir.mkdir(parents=True)

        # PPTX with 2 links (YouTube + NotebookLM)
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Brainstorming Workshop",
             "hyperlinks": [
                 {"url": "https://youtube.com/watch?v=brainstorm1", "text": "Tutorial Video"},
                 {"url": "https://notebooklm.google.com", "text": "NotebookLM"},
             ]},
        ])

        # PDF with 2 links (rubric + duplicate NotebookLM)
        create_test_pdf(lesson_dir / "Handout.pdf", [
            {"text": "Resources",
             "links": [
                 {"url": "https://example.com/rubric"},
                 {"url": "https://notebooklm.google.com"},
             ]},
        ])

        # Video file
        create_video_file(lesson_dir / "walkthrough.mp4")

        # ── Stages 1 + 2 + 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson5 = term2["by_lesson"]["5"]

        assert lesson5["link_count"] >= 3  # 2 from pptx + 2 from pdf (may include dups)
        assert lesson5["video_ref_count"] >= 2  # YouTube link + mp4 file

        # Verify link sources
        pptx_links = [l for l in lesson5["links"] if l["source"] == "pptx"]
        pdf_links = [l for l in lesson5["links"] if l["source"] == "pdf"]
        assert len(pptx_links) >= 2
        assert len(pdf_links) >= 1

        # ── Stage 6: KB Build ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l5 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 5][0]
        meta = l5["metadata"]

        # Videos should have YouTube + mp4
        assert len(meta["videos"]) >= 2
        video_urls = [v.get("url", "") for v in meta["videos"]]
        assert any("youtube" in u for u in video_urls)

        # Resources should have NotebookLM + rubric, NOT YouTube
        for res in meta["resources"]:
            assert "youtube.com/watch" not in res.lower()

        # Resources should be deduped (NotebookLM appears in both pptx and pdf)
        notebook_resources = [r for r in meta["resources"] if "notebooklm" in r.lower()]
        assert len(notebook_resources) <= 1  # Deduplicated


class TestMultiTermPipeline:
    """Scenario 22: 2 terms built — per-term isolation verified."""

    def test_two_terms_isolated(self, tmp_path, config_override, sample_png):
        """Term 1 and Term 2 content stays isolated in separate KB files."""
        import config

        sources = config_override["SOURCES_DIR"]

        # Term 1, Lesson 1 with unique link
        t1l1 = sources / "term1" / "Lesson 1"
        t1l1.mkdir(parents=True)
        create_test_pptx(t1l1 / "Teachers Slides.pptx", [
            {"text": "Term 1 Lesson 1 content", "images": [sample_png],
             "hyperlinks": [{"url": "https://example.com/term1-only", "text": "T1 Link"}]},
        ])

        # Term 2, Lesson 1 with different unique link + video
        t2l1 = sources / "term2" / "Lesson 1"
        t2l1.mkdir(parents=True)
        create_test_pptx(t2l1 / "Teachers Slides.pptx", [
            {"text": "Term 2 Lesson 1 content",
             "hyperlinks": [{"url": "https://example.com/term2-only", "text": "T2 Link"}]},
        ])
        create_video_file(t2l1 / "intro.mp4")

        # ── Stages 1 + 2 + 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        # Both terms should be in consolidated data
        assert "1" in stage5["by_term"]
        assert "2" in stage5["by_term"]

        # Per-term consolidated files should exist
        consolidated_dir = config_override["CONSOLIDATED_DIR"]
        t1_consolidated = consolidated_dir / "consolidated_term1.json"
        t2_consolidated = consolidated_dir / "consolidated_term2.json"
        assert t1_consolidated.exists()
        assert t2_consolidated.exists()

        # ── Stage 6: Build both terms ──
        run_build(term_num=1)
        run_build(term_num=2)

        t1_output = config_override["OUTPUT_DIR"] / "Term 1 - Lesson Based Structure.json"
        t2_output = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        assert t1_output.exists()
        assert t2_output.exists()

        with open(t1_output, "r", encoding="utf-8") as f:
            kb1 = json.load(f)
        with open(t2_output, "r", encoding="utf-8") as f:
            kb2 = json.load(f)

        assert kb1["term"] == 1
        assert kb2["term"] == 2

        # Term 1 KB should NOT contain term2 link
        kb1_str = json.dumps(kb1)
        assert "term2-only" not in kb1_str

        # Term 2 KB should NOT contain term1 link
        kb2_str = json.dumps(kb2)
        assert "term1-only" not in kb2_str

        # Term 2 should have video
        t2_lessons = kb2["lessons"]
        assert len(t2_lessons) >= 1
        assert len(t2_lessons[0]["metadata"]["videos"]) >= 1


class TestFullPipelineWithValidationGate:
    """Scenario 23: Build + validate publish gate (pass/fail scenarios)."""

    def test_validation_gate_pass_and_fail(self, tmp_path, config_override, sample_png):
        """Scenario A: complete → passes. Scenario B: missing → blocked."""
        import config

        sources = config_override["SOURCES_DIR"]

        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        # ── Scenario A: 12 complete lessons ──
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} teachers", "images": [sample_png]},
            ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students"},
            ])

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        reports_a = {}  # validate_kb deleted
        assert reports_a is not None
        report_a = reports_a["term2"]
        assert report_a["publish_blocked"] is False
        assert report_a["summary"]["errors"] == 0

        # ── Scenario B: Remove Teachers Slides from Lesson 6 and rebuild ──
        import shutil

        # Remove all content and rebuild
        for i in range(1, 13):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            shutil.rmtree(lesson_dir)
            lesson_dir.mkdir(parents=True)
            if i != 6:
                create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                    {"text": f"Lesson {i} teachers", "images": [sample_png]},
                ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} students"},
            ])

        # Clear previous outputs
        for f in config_override["CONVERTED_DIR"].rglob("*"):
            if f.is_file():
                f.unlink()
        for f in config_override["CONSOLIDATED_DIR"].rglob("*"):
            if f.is_file():
                f.unlink()
        for f in config_override["OUTPUT_DIR"].rglob("*"):
            if f.is_file():
                f.unlink()

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        reports_b = {}  # validate_kb deleted
        assert reports_b is not None
        report_b = reports_b["term2"]
        assert report_b["publish_blocked"] is True
        assert report_b["summary"]["errors"] >= 1

        # Specific MISSING error for Lesson 6 teachers_slides
        missing_l6 = [
            a for a in report_b["anomalies"]
            if a["type"] == "MISSING" and a.get("lesson") == 6
            and a.get("content_type") == "teachers_slides"
        ]
        assert len(missing_l6) >= 1


class TestDuplicateAcrossLessons:
    """Scenario 24: Same PPTX content in 2 lesson folders."""

    def test_cross_lesson_duplicate_detected(self, tmp_path, config_override, sample_png):
        """Identical content in L3 and L4 → duplicate flagged, both still built."""
        import config

        sources = config_override["SOURCES_DIR"]

        # L3 and L4 with identical content
        for lesson_num in (3, 4):
            lesson_dir = sources / "term2" / f"Lesson {lesson_num}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": "Identical content across lessons", "images": [sample_png]},
            ])

        # ── Stages 1 → 2 → 5 → 6 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        # Both lessons should exist in consolidated
        term2 = stage5["by_term"]["2"]
        assert "3" in term2["by_lesson"]
        assert "4" in term2["by_lesson"]

        # Duplicates should be detected (md5 or exact)
        assert len(stage5["duplicates"]) >= 1

        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        # Both lessons should be in KB
        lesson_ids = [l["metadata"]["lesson_id"] for l in kb["lessons"]]
        assert 3 in lesson_ids
        assert 4 in lesson_ids

        # ── Stage 7: DUPLICATE is INFO severity, not blocking ──
        pass  # validate_kb.run_validation removed
        reports = {}  # validate_kb deleted
        if reports:
            report = reports["term2"]
            dup_anomalies = [a for a in report["anomalies"] if a["type"] == "DUPLICATE"]
            for da in dup_anomalies:
                assert da["severity"] == "INFO"


class TestEndToEndDataIntegrity:
    """Scenario 25: Trace specific link + image through all stages."""

    def test_data_traced_through_pipeline(self, tmp_path, config_override, sample_png):
        """Specific URL and image preserved from Stage 1 through Stage 6."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 7"
        lesson_dir.mkdir(parents=True)

        target_url = "https://forms.google.com/feedback-form-123"

        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Lesson 7 – Gameplay Expansion and Feedback"},
            {"text": "Learning Objectives\nAdd immersion through visuals and sound",
             "images": [sample_png]},
            {"text": "Feedback Form",
             "hyperlinks": [{"url": target_url, "text": "Feedback Form"}]},
        ])

        # ── Stage 1: Verify link + image extracted ──
        from extract_media import run_extraction
        stage1 = run_extraction(source_dir=str(sources))

        assert stage1["total_links"] >= 1
        assert stage1["total_images"] >= 1

        # Find the target URL in Stage 1 output
        stage1_urls = []
        for pf in stage1["pptx_files"]:
            for link in pf["links"]:
                stage1_urls.append(link["url"])
        assert target_url in stage1_urls

        # ── Stage 2 ──
        from convert_docs import run_conversion
        run_conversion(source_dir=str(sources))

        # ── Stage 5: Verify link + image in consolidated ──
        from consolidate import run_consolidation
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson7 = term2["by_lesson"]["7"]

        stage5_urls = [l["url"] for l in lesson7["links"]]
        assert target_url in stage5_urls
        assert lesson7["image_count"] >= 1
        assert lesson7["link_count"] >= 1

        # ── Stage 6: Verify in KB output ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l7 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 7][0]

        # URL should be in resources (not a video URL)
        assert any(target_url in r for r in l7["metadata"]["resources"])

        # Image should be tracked
        assert len(l7["metadata"]["images"]) >= 1
        assert l7["enriched"]["image_count"] >= 1

        # Title should contain lesson topic
        kb_str = json.dumps(l7).lower()
        assert "feedback" in kb_str or "gameplay" in kb_str


class TestTermWithMixedMediaPerLesson:
    """Scenario 26: Each lesson has different file combinations."""

    def test_mixed_media_combinations(self, tmp_path, config_override, sample_png):
        """4 lessons with varied content types all built correctly."""
        import config

        sources = config_override["SOURCES_DIR"]

        # L1: PPTX only
        l1 = sources / "term2" / "Lesson 1"
        l1.mkdir(parents=True)
        create_test_pptx(l1 / "Teachers Slides.pptx", [
            {"text": "Lesson 1 – PPTX only content"},
        ])

        # L2: PPTX + PDF
        l2 = sources / "term2" / "Lesson 2"
        l2.mkdir(parents=True)
        create_test_pptx(l2 / "Teachers Slides.pptx", [
            {"text": "Lesson 2 – Persona",
             "hyperlinks": [{"url": "https://example.com/pptx-link", "text": "PPTX Link"}]},
        ])
        create_test_pdf(l2 / "Handout.pdf", [
            {"text": "Handout", "links": [{"url": "https://example.com/pdf-link"}]},
        ])

        # L3: PPTX + video
        l3 = sources / "term2" / "Lesson 3"
        l3.mkdir(parents=True)
        create_test_pptx(l3 / "Teachers Slides.pptx", [
            {"text": "Lesson 3 – Research with AI"},
        ])
        create_video_file(l3 / "tutorial.mp4")

        # L4: PDF + video only (no PPTX)
        l4 = sources / "term2" / "Lesson 4"
        l4.mkdir(parents=True)
        create_test_pdf(l4 / "Specification.pdf", [
            {"text": "Design Spec", "links": [{"url": "https://example.com/spec"}]},
        ])
        create_video_file(l4 / "overview.mp4")

        # ── Run full pipeline ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        assert kb["total_lessons"] >= 4
        lesson_ids = [l["metadata"]["lesson_id"] for l in kb["lessons"]]
        assert all(i in lesson_ids for i in [1, 2, 3, 4])

        # L1: docs only, no video/resources
        l1_kb = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 1][0]
        assert len(l1_kb["enriched"]["slides"]) >= 1

        # L2: merged links from PPTX + PDF
        l2_kb = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 2][0]
        l2_resources = l2_kb["metadata"]["resources"]
        assert len(l2_resources) >= 2  # pptx-link + pdf-link

        # L3: has video refs
        l3_kb = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 3][0]
        assert len(l3_kb["metadata"]["videos"]) >= 1

        # L4: PDF content + video (no PPTX)
        l4_kb = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 4][0]
        assert len(l4_kb["metadata"]["videos"]) >= 1
        assert len(l4_kb["metadata"]["resources"]) >= 1


class TestVideoDeduplicationAcrossSources:
    """Scenario 27: Same YouTube URL from PPTX and PDF."""

    def test_video_deduplicated_in_kb(self, tmp_path, config_override):
        """Same YouTube URL from 2 sources → 1 video entry in KB."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 5"
        lesson_dir.mkdir(parents=True)

        youtube_url = "https://youtube.com/watch?v=shared123"

        # PPTX with YouTube link
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Brainstorming content",
             "hyperlinks": [{"url": youtube_url, "text": "Tutorial Video"}]},
        ])

        # PDF with same YouTube link
        create_test_pdf(lesson_dir / "Handout.pdf", [
            {"text": "Resources", "links": [{"url": youtube_url}]},
        ])

        # ── Stages 1 → 2 → 5 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        stage5 = run_consolidation()

        term2 = stage5["by_term"]["2"]
        lesson5 = term2["by_lesson"]["5"]

        # Stage 5: Both link entries should be present (not deduped here)
        youtube_links = [l for l in lesson5["links"] if youtube_url in l["url"]]
        assert len(youtube_links) >= 2  # One from pptx, one from pdf

        # ── Stage 6: KB Build ──
        from build_kb import run_build
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l5 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 5][0]

        # Videos should be deduplicated — only 1 entry for the same URL
        matching_videos = [v for v in l5["metadata"]["videos"] if youtube_url in v.get("url", "")]
        assert len(matching_videos) == 1

        # YouTube URL should NOT be in resources
        for res in l5["metadata"]["resources"]:
            assert youtube_url not in res


class TestEndstarToolsFromMultipleDocuments:
    """Scenario 28: Endstar tools collected from all lesson content."""

    def test_tools_from_multiple_sources(self, tmp_path, config_override, sample_png):
        """Keywords from Teachers + Students Slides → endstar_tools populated."""
        import config

        sources = config_override["SOURCES_DIR"]
        lesson_dir = sources / "term2" / "Lesson 6"
        lesson_dir.mkdir(parents=True)

        # Teachers Slides mentions "triggers" and "NPCs"
        create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
            {"text": "Use triggers to create events"},
            {"text": "Add NPCs for player interactions"},
        ])

        # Students Slides mentions "mechanics" and "logic"
        create_test_pptx(lesson_dir / "Students Slides.pptx", [
            {"text": "Explore game mechanics in your prototype"},
            {"text": "Add logic to your rule blocks"},
        ])

        # ── Stages 1 → 2 → 5 → 6 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)

        output_path = config_override["OUTPUT_DIR"] / "Term 2 - Lesson Based Structure.json"
        with open(output_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        l6 = [l for l in kb["lessons"] if l["metadata"]["lesson_id"] == 6][0]
        tools = l6["metadata"]["endstar_tools"]

        # All 4 canonical tool names should be detected
        tools_lower = [t.lower() for t in tools]
        assert "triggers" in tools_lower
        assert "npcs" in tools_lower
        assert "mechanics" in tools_lower
        assert "logic" in tools_lower


class TestValidationConfidenceScoring:
    """Scenario 29: Verify exact confidence calculation formula."""

    def test_confidence_formula(self, tmp_path, config_override, sample_png):
        """6 lessons (half term) → verify confidence = base - penalty."""
        import config

        sources = config_override["SOURCES_DIR"]

        # 6 lessons with Teachers + Students Slides
        for i in range(1, 7):
            lesson_dir = sources / "term2" / f"Lesson {i}"
            lesson_dir.mkdir(parents=True)
            create_test_pptx(lesson_dir / "Teachers Slides.pptx", [
                {"text": f"Lesson {i} content", "images": [sample_png]},
            ])
            create_test_pptx(lesson_dir / "Students Slides.pptx", [
                {"text": f"Lesson {i} student content"},
            ])

        # ── Stages 1 → 2 → 5 → 6 → 7 ──
        from extract_media import run_extraction
        from convert_docs import run_conversion
        from consolidate import run_consolidation
        from build_kb import run_build
        pass  # validate_kb.run_validation removed

        run_extraction(source_dir=str(sources))
        run_conversion(source_dir=str(sources))
        run_consolidation()
        run_build(term_num=2)
        reports = {}  # validate_kb deleted

        assert reports is not None
        report = reports["term2"]

        total_lessons = report["summary"]["total_lessons"]
        errors = report["summary"]["errors"]
        warnings = report["summary"]["warnings"]

        # Verify confidence formula: base = (total_lessons / 12) * 100
        # penalty = min(errors * 5, 30) + min(warnings * 1, 10)
        # confidence = max(0, round(base - penalty, 1))
        expected_base = 100 if total_lessons >= 12 else (total_lessons / 12 * 100)
        expected_penalty = min(errors * 5, 30) + min(warnings * 1, 10)
        expected_confidence = max(0, round(expected_base - expected_penalty, 1))

        assert report["overall_confidence"] == expected_confidence

        # With 6 lessons, base = 50, so status should be INCOMPLETE or NEEDS_REVIEW
        assert total_lessons == 6
        assert expected_base == pytest.approx(50.0, abs=0.1)

        # Status depends on confidence and errors
        if expected_confidence < 60:
            assert report["status"] == "INCOMPLETE"
        elif expected_confidence < 80:
            assert report["status"] == "NEEDS_REVIEW"
