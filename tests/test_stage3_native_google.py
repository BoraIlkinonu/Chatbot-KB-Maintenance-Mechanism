"""
Stage 3 Tests: Native Google Slides/Docs Extraction
Tests extract_slides(), extract_doc() with mock API response dicts.
No real API calls — we test the parsing logic only.
"""

import pytest

from tests.fixtures import build_slides_api_response, build_docs_api_response
from extract_native_google import extract_slides, extract_doc


class MockService:
    """Mock Google API service that returns a preset response."""

    def __init__(self, response):
        self._response = response

    def presentations(self):
        return self

    def documents(self):
        return self

    def get(self, **kwargs):
        return self

    def execute(self):
        return self._response


class MockErrorService:
    """Mock Google API service that raises an exception."""

    def __init__(self, error_msg="API Error"):
        self._error_msg = error_msg

    def presentations(self):
        return self

    def documents(self):
        return self

    def get(self, **kwargs):
        return self

    def execute(self):
        raise Exception(self._error_msg)


class TestExtractSlides:
    """Test Google Slides content extraction."""

    def test_slides_with_embedded_video(self):
        """Scenario 1: Embedded video populates slide_content['videos']."""
        response = build_slides_api_response([
            {
                "texts": ["Slide with video"],
                "videos": [
                    {"url": "https://youtube.com/watch?v=abc", "source": "YOUTUBE", "video_id": "abc"},
                ],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert "error" not in result
        assert result["total_videos"] == 1
        assert len(result["slides"]) == 1
        assert len(result["slides"][0]["videos"]) == 1
        assert result["slides"][0]["videos"][0]["url"] == "https://youtube.com/watch?v=abc"
        assert result["slides"][0]["videos"][0]["video_id"] == "abc"

    def test_slides_with_text_hyperlinks(self):
        """Scenario 2: Text hyperlinks extracted from textRun.style.link.url."""
        response = build_slides_api_response([
            {
                "texts": ["Some content"],
                "links": [
                    {"url": "https://example.com/resource", "text": "Click here"},
                    {"url": "https://example.com/tool", "text": "Tool link"},
                ],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert result["total_links"] == 2
        urls = [l["url"] for s in result["slides"] for l in s["links"]]
        assert "https://example.com/resource" in urls
        assert "https://example.com/tool" in urls

    def test_slides_with_table_cell_links(self):
        """Scenario 3: Links in table cells captured."""
        response = build_slides_api_response([
            {
                "texts": [],
                "table_links": [
                    ["Header 1", {"text": "Resource", "url": "https://table-link.com"}],
                    ["Data", "More data"],
                ],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert result["total_links"] >= 1
        urls = [l["url"] for s in result["slides"] for l in s["links"]]
        assert "https://table-link.com" in urls

    def test_slides_with_speaker_notes_links(self):
        """Scenario 4: Links in speaker notes captured."""
        response = build_slides_api_response([
            {
                "texts": ["Main content"],
                "notes": "See the resource below",
                "notes_links": [
                    {"url": "https://notes-link.com", "text": "Notes Resource"},
                ],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert result["total_links"] >= 1
        urls = [l["url"] for s in result["slides"] for l in s["links"]]
        assert "https://notes-link.com" in urls

    def test_slides_no_links_no_videos(self):
        """Scenario 7: No links or videos — empty lists returned, counts are 0."""
        response = build_slides_api_response([
            {"texts": ["Just text content"]},
            {"texts": ["More text"]},
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert result["total_links"] == 0
        assert result["total_videos"] == 0
        for slide in result["slides"]:
            assert slide["links"] == []
            assert slide["videos"] == []

    def test_slides_api_error(self):
        """Scenario 8: API error returns error dict, doesn't crash."""
        service = MockErrorService("403 Forbidden")
        result = extract_slides(service, "test_id", "test.pptx")

        assert "error" in result
        assert "403" in result["error"]
        assert result["file_id"] == "test_id"

    def test_slides_multiple_videos_across_slides(self):
        """Multiple videos across different slides are all captured."""
        response = build_slides_api_response([
            {
                "texts": ["Slide 1"],
                "videos": [{"url": "https://youtube.com/watch?v=a", "source": "YOUTUBE", "video_id": "a"}],
            },
            {
                "texts": ["Slide 2"],
                "videos": [{"url": "https://youtube.com/watch?v=b", "source": "YOUTUBE", "video_id": "b"}],
            },
            {
                "texts": ["Slide 3"],
                "videos": [{"url": "https://vimeo.com/123", "source": "VIMEO", "video_id": "123"}],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        assert result["total_videos"] == 3

    def test_slides_link_has_slide_number(self):
        """Links include correct slide_number."""
        response = build_slides_api_response([
            {"texts": ["Slide 1"]},
            {
                "texts": ["Slide 2"],
                "links": [{"url": "https://example.com", "text": "Link"}],
            },
        ])
        service = MockService(response)
        result = extract_slides(service, "test_id", "test.pptx")

        links = result["slides"][1]["links"]
        assert len(links) >= 1
        assert links[0]["slide_number"] == 2


class TestExtractDoc:
    """Test Google Docs content extraction."""

    def test_doc_with_hyperlinks(self, mock_docs_api_response):
        """Scenario 5: Links extracted from textRun.textStyle.link.url, total_links correct."""
        service = MockService(mock_docs_api_response)
        result = extract_doc(service, "test_id", "test_doc")

        assert "error" not in result
        assert result["total_links"] >= 1
        urls = [l["url"] for l in result["links"]]
        assert "https://example.com/objectives" in urls

    def test_doc_with_table_cell_links(self):
        """Scenario 6: Links in table cells captured."""
        response = build_docs_api_response([
            {"text": "Title", "style": "HEADING_1"},
            {
                "text": "",
                "style": "NORMAL_TEXT",
                "table": [
                    ["Header", {"text": "Resource Link", "url": "https://table-doc-link.com"}],
                    ["Data", "More data"],
                ],
            },
        ])
        service = MockService(response)
        result = extract_doc(service, "test_id", "test_doc")

        assert result["total_links"] >= 1
        urls = [l["url"] for l in result["links"]]
        assert "https://table-doc-link.com" in urls

    def test_doc_no_links(self):
        """Doc with no links returns empty links list."""
        response = build_docs_api_response([
            {"text": "Just plain text", "style": "NORMAL_TEXT"},
        ])
        service = MockService(response)
        result = extract_doc(service, "test_id", "test_doc")

        assert result["total_links"] == 0
        assert result["links"] == []

    def test_doc_api_error(self):
        """API error returns error dict, doesn't crash."""
        service = MockErrorService("404 Not Found")
        result = extract_doc(service, "test_id", "test_doc")

        assert "error" in result
        assert "404" in result["error"]

    def test_doc_content_blocks_parsed(self, mock_docs_api_response):
        """Content blocks extracted with correct styles."""
        service = MockService(mock_docs_api_response)
        result = extract_doc(service, "test_id", "test_doc")

        assert len(result["content_blocks"]) >= 3
        styles = [b["style"] for b in result["content_blocks"]]
        assert "HEADING_1" in styles
        assert "HEADING_2" in styles
        assert "HEADING_3" in styles
