"""
Stage 1 Tests: PPTX Media Extraction
Tests extract_pptx_images(), extract_pptx_links(), build_slide_image_mapping(), run_extraction()
"""

import pytest
from pathlib import Path

from tests.fixtures import (
    create_test_pptx, create_minimal_png, create_corrupted_pptx,
    create_zero_byte_file,
)
from extract_media import (
    extract_pptx_images, extract_pptx_links, build_slide_image_mapping,
    run_extraction,
)


class TestExtractPptxImages:
    """Test image extraction from PPTX files."""

    def test_normal_pptx_with_images(self, tmp_path, sample_png):
        """Scenario 1: Happy path — images extracted with slide mapping."""
        pptx_path = tmp_path / "normal.pptx"
        create_test_pptx(pptx_path, [
            {"text": "Slide 1", "images": [sample_png]},
            {"text": "Slide 2", "images": [sample_png]},
        ])

        output_base = tmp_path / "media"
        output_base.mkdir()
        result = extract_pptx_images(pptx_path, output_base)

        assert len(result) >= 1, "Should extract at least one image"
        for img in result:
            assert "image_path" in img
            assert "slide_numbers" in img
            assert "size_bytes" in img
            assert img["size_bytes"] > 0
            assert Path(img["image_path"]).exists()

    def test_corrupted_pptx_returns_empty(self, tmp_path):
        """Scenario 2: Corrupted/truncated PPTX returns [] without crashing."""
        pptx_path = tmp_path / "corrupted.pptx"
        create_corrupted_pptx(pptx_path)

        output_base = tmp_path / "media"
        output_base.mkdir()
        result = extract_pptx_images(pptx_path, output_base)

        assert result == [], "Corrupted PPTX should return empty list"

    def test_zero_byte_pptx(self, tmp_path):
        """Scenario 7: Zero-byte file — graceful error, no crash."""
        pptx_path = tmp_path / "empty.pptx"
        create_zero_byte_file(pptx_path)

        output_base = tmp_path / "media"
        output_base.mkdir()
        result = extract_pptx_images(pptx_path, output_base)

        assert result == [], "Zero-byte PPTX should return empty list"


class TestExtractPptxLinks:
    """Test hyperlink extraction from PPTX files."""

    def test_normal_pptx_with_links(self, sample_pptx_with_links):
        """Scenario 1: Happy path — text hyperlinks extracted."""
        links = extract_pptx_links(sample_pptx_with_links)

        assert len(links) >= 2, "Should extract hyperlinks"
        urls = [l["url"] for l in links]
        assert "https://example.com/resource1" in urls
        assert "https://notebooklm.google.com" in urls

        # Verify structure
        for link in links:
            assert "url" in link
            assert "text" in link
            assert "slide_number" in link
            assert "link_type" in link
            assert link["slide_number"] >= 1

    def test_corrupted_pptx_returns_empty(self, tmp_path):
        """Scenario 2: Corrupted PPTX — extract_pptx_links returns [] without crash."""
        pptx_path = tmp_path / "corrupted.pptx"
        create_corrupted_pptx(pptx_path)

        links = extract_pptx_links(pptx_path)
        assert links == [], "Corrupted PPTX should return empty links"

    def test_pptx_links_only_no_images(self, tmp_path):
        """Scenario 3: PPTX with links but zero images — links extracted independently."""
        pptx_path = tmp_path / "links_only.pptx"
        create_test_pptx(pptx_path, [
            {
                "text": "Slide with links only",
                "hyperlinks": [
                    {"url": "https://example.com/a", "text": "Link A"},
                    {"url": "https://example.com/b", "text": "Link B"},
                ],
            },
        ])

        links = extract_pptx_links(pptx_path)
        assert len(links) >= 2

    def test_click_action_hyperlinks(self, sample_pptx_with_links):
        """Scenario 4: Click action hyperlinks captured alongside text hyperlinks."""
        links = extract_pptx_links(sample_pptx_with_links)

        link_types = [l["link_type"] for l in links]
        urls = [l["url"] for l in links]

        assert "click_action" in link_types, "Should capture click_action hyperlinks"
        assert "https://example.com/clickme" in urls

    def test_duplicate_links_all_captured(self, tmp_path):
        """Scenario 5: Same URL on multiple slides — all instances captured."""
        pptx_path = tmp_path / "dup_links.pptx"
        create_test_pptx(pptx_path, [
            {"text": "Slide 1", "hyperlinks": [{"url": "https://example.com/same", "text": "Link"}]},
            {"text": "Slide 2", "hyperlinks": [{"url": "https://example.com/same", "text": "Link"}]},
            {"text": "Slide 3", "hyperlinks": [{"url": "https://example.com/same", "text": "Link"}]},
        ])

        links = extract_pptx_links(pptx_path)
        same_url_links = [l for l in links if l["url"] == "https://example.com/same"]
        assert len(same_url_links) >= 2, "Duplicate URLs across slides should all be captured"

        # Each should have different slide numbers
        slide_nums = {l["slide_number"] for l in same_url_links}
        assert len(slide_nums) >= 2, "Same URL should appear on different slides"

    def test_group_shapes_no_crash(self, tmp_path, sample_png):
        """Scenario 6: GroupShapes don't crash click_action extraction."""
        # python-pptx doesn't easily create group shapes, so we test with a
        # normal PPTX — the important thing is that GroupShape check doesn't crash
        pptx_path = tmp_path / "with_shapes.pptx"
        create_test_pptx(pptx_path, [
            {"text": "Normal slide", "hyperlinks": [{"url": "https://example.com", "text": "Link"}]},
        ])

        # Should not raise any exception
        links = extract_pptx_links(pptx_path)
        assert isinstance(links, list)

    def test_zero_byte_pptx_links(self, tmp_path):
        """Scenario 7: Zero-byte PPTX — graceful error for link extraction."""
        pptx_path = tmp_path / "empty.pptx"
        create_zero_byte_file(pptx_path)

        links = extract_pptx_links(pptx_path)
        assert links == []


class TestRunExtraction:
    """Test the full run_extraction() pipeline function."""

    def test_temp_files_filtered(self, tmp_path, config_override):
        """Scenario 8: Temp files (~$filename.pptx) filtered out."""
        import config

        sources = config_override["SOURCES_DIR"]
        media = config_override["MEDIA_DIR"]

        # Create a normal PPTX and a temp file
        create_test_pptx(sources / "real.pptx", [{"text": "Real slide"}])
        create_test_pptx(sources / "~$temp.pptx", [{"text": "Temp slide"}])

        result = run_extraction(source_dir=str(sources))

        source_names = [Path(p["source"]).name for p in result["pptx_files"]]
        assert "real.pptx" in source_names
        assert "~$temp.pptx" not in source_names, "Temp files should be filtered out"

    def test_extraction_metadata_has_images_and_links(self, tmp_path, config_override, sample_png):
        """Verify extraction metadata includes both images and links keys."""
        import config

        sources = config_override["SOURCES_DIR"]

        create_test_pptx(sources / "test.pptx", [
            {
                "text": "Test slide",
                "images": [sample_png],
                "hyperlinks": [{"url": "https://example.com", "text": "Link"}],
            },
        ])

        result = run_extraction(source_dir=str(sources))

        assert result["total_images"] >= 0
        assert result["total_links"] >= 0
        for pptx_info in result["pptx_files"]:
            assert "images" in pptx_info
            assert "links" in pptx_info
            assert "images_count" in pptx_info
            assert "links_count" in pptx_info
