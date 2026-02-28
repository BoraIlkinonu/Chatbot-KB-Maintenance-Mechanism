"""
Shared pytest fixtures for KB Maintenance Pipeline tests.
Provides temp directories, config overrides, and common test data.
"""

import sys
import json
import pytest
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: requires Claude CLI for LLM judge calls")

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.fixtures import (
    create_test_pptx, create_minimal_png, create_test_pdf,
    build_slides_api_response, build_docs_api_response, create_video_file,
)


# ──────────────────────────────────────────────────────────
# Temporary directory fixtures
# ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_sources(tmp_path):
    """Temporary sources/ directory with term subdirs."""
    sources = tmp_path / "sources"
    for term in ("term1", "term2", "term3"):
        (sources / term).mkdir(parents=True)
    return sources


@pytest.fixture
def tmp_media(tmp_path):
    """Temporary media/ directory."""
    d = tmp_path / "media"
    d.mkdir()
    return d


@pytest.fixture
def tmp_converted(tmp_path):
    """Temporary converted/ directory."""
    d = tmp_path / "converted"
    d.mkdir()
    return d


@pytest.fixture
def tmp_native(tmp_path):
    """Temporary native_extracts/ directory."""
    d = tmp_path / "native_extracts"
    d.mkdir()
    return d


@pytest.fixture
def tmp_consolidated(tmp_path):
    """Temporary consolidated/ directory."""
    d = tmp_path / "consolidated"
    d.mkdir()
    return d


@pytest.fixture
def tmp_output(tmp_path):
    """Temporary output/ directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def tmp_logs(tmp_path):
    """Temporary logs/ directory."""
    d = tmp_path / "logs"
    d.mkdir()
    return d


# ──────────────────────────────────────────────────────────
# Config override fixture
# ──────────────────────────────────────────────────────────

@pytest.fixture
def config_override(tmp_path, monkeypatch):
    """Monkeypatch config.py paths to use temp directories.
    Patches both config module AND the module-level imports in stage scripts."""
    import config

    dirs = {}
    for name in ("SOURCES_DIR", "MEDIA_DIR", "CONVERTED_DIR", "NATIVE_DIR",
                  "CONSOLIDATED_DIR", "OUTPUT_DIR", "LOGS_DIR", "VALIDATION_DIR"):
        d = tmp_path / name.lower().replace("_dir", "")
        d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, d)
        dirs[name] = d

    # Also patch BASE_DIR
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)

    # Patch module-level imports in stage scripts so they use the temp dirs
    import extract_media
    import convert_docs
    import consolidate
    import build_kb

    for module in (extract_media, convert_docs, consolidate, build_kb):
        for name in ("SOURCES_DIR", "MEDIA_DIR", "CONVERTED_DIR", "NATIVE_DIR",
                      "CONSOLIDATED_DIR", "OUTPUT_DIR", "LOGS_DIR", "VALIDATION_DIR"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, dirs.get(name, getattr(config, name)))

    # Also patch BASE_DIR in build_kb
    if hasattr(build_kb, "BASE_DIR"):
        monkeypatch.setattr(build_kb, "BASE_DIR", tmp_path)

    return dirs


# ──────────────────────────────────────────────────────────
# Sample file fixtures
# ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_png():
    """A minimal valid PNG image (2x2 red pixels)."""
    return create_minimal_png(2, 2, (255, 0, 0))


@pytest.fixture
def sample_pptx_with_links(tmp_path):
    """A real PPTX file with hyperlinks and text."""
    path = tmp_path / "test_presentation.pptx"
    create_test_pptx(path, [
        {
            "text": "Lesson 5 – Brainstorming and Concept Generation",
            "notes": "Students will brainstorm ideas",
            "hyperlinks": [
                {"url": "https://example.com/resource1", "text": "Resource 1"},
                {"url": "https://notebooklm.google.com", "text": "NotebookLM"},
            ],
        },
        {
            "text": "Learning Objectives\nGenerate creative game concepts",
            "notes": "Activity instructions for teachers",
            "hyperlinks": [
                {"url": "https://youtube.com/watch?v=abc123", "text": "Tutorial Video"},
            ],
            "click_actions": [
                {"url": "https://example.com/clickme", "text": "Click Action"},
            ],
        },
    ])
    return path


@pytest.fixture
def sample_pptx_with_images(tmp_path, sample_png):
    """A real PPTX file with embedded images."""
    path = tmp_path / "slides_with_images.pptx"
    create_test_pptx(path, [
        {
            "text": "Slide with image",
            "images": [sample_png],
        },
        {
            "text": "Another slide with image",
            "images": [sample_png],
        },
    ])
    return path


@pytest.fixture
def sample_pdf_with_links(tmp_path):
    """A real PDF file with hyperlink annotations."""
    path = tmp_path / "test_document.pdf"
    create_test_pdf(path, [
        {
            "text": "Page 1 content",
            "links": [
                {"url": "https://example.com/link1"},
                {"url": "https://example.com/link2"},
            ],
        },
        {
            "text": "Page 2 content",
            "links": [
                {"url": "https://youtube.com/watch?v=xyz789"},
            ],
        },
    ])
    return path


# ──────────────────────────────────────────────────────────
# Mock API response fixtures
# ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_slides_api_response():
    """Dict mimicking Google Slides API with videos + links."""
    return build_slides_api_response([
        {
            "texts": ["Lesson 3: Research and AI"],
            "links": [
                {"url": "https://example.com/research", "text": "Research Guide"},
            ],
            "videos": [
                {"url": "https://youtube.com/watch?v=vid1", "source": "YOUTUBE", "video_id": "vid1"},
            ],
        },
        {
            "texts": ["Activity: Explore AI tools"],
            "links": [
                {"url": "https://example.com/ai-tool", "text": "AI Tool"},
            ],
            "notes": "Teacher should demo the tool first",
        },
        {
            "texts": ["Summary"],
            "table": [
                ["Criterion", "Basic", "Advanced"],
                ["Research", "One source", "Multiple sources"],
            ],
        },
    ])


@pytest.fixture
def mock_docs_api_response():
    """Dict mimicking Google Docs API with links."""
    return build_docs_api_response([
        {"text": "Lesson Plan", "style": "HEADING_1"},
        {"text": "Lesson 3: Research and AI", "style": "HEADING_2"},
        {"text": "Big Question", "style": "HEADING_3"},
        {"text": "How can we use AI responsibly in research?", "style": "NORMAL_TEXT"},
        {"text": "Learning Objectives", "style": "HEADING_3"},
        {
            "text": "Students will be able to: ",
            "style": "NORMAL_TEXT",
            "links": [
                {"url": "https://example.com/objectives", "text": "full objectives"},
            ],
        },
    ])


# ──────────────────────────────────────────────────────────
# Consolidated data fixture
# ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_consolidated_lesson():
    """Sample consolidated lesson data matching the Stage 5 output format."""
    return {
        "lesson": 5,
        "term": 2,
        "document_count": 2,
        "image_count": 3,
        "native_count": 0,
        "link_count": 4,
        "video_ref_count": 2,
        "documents": [
            {
                "path": "term2/Lesson 5/Teachers Slides.md",
                "full_path": "",  # Will be set in tests
                "content_type": "teachers_slides",
                "term": 2,
                "lessons": [5],
                "format": "md",
                "char_count": 500,
                "slide_count": 10,
                "content_preview": "",
            },
        ],
        "images": [],
        "native_content": [],
        "links": [
            {"url": "https://notebooklm.google.com", "text": "NotebookLM", "source": "pptx",
             "source_file": "term2/Lesson 5/Teachers Slides.pptx", "term": 2, "lessons": [5]},
            {"url": "https://example.com/rubric", "text": "Rubric", "source": "pptx",
             "source_file": "term2/Lesson 5/Teachers Slides.pptx", "term": 2, "lessons": [5]},
            {"url": "https://youtube.com/watch?v=abc123", "text": "Tutorial", "source": "pptx",
             "source_file": "term2/Lesson 5/Teachers Slides.pptx", "term": 2, "lessons": [5]},
            {"url": "https://example.com/resource", "text": "Resource", "source": "pdf",
             "source_file": "term2/Lesson 5/Handout.pdf", "term": 2, "lessons": [5]},
        ],
        "video_refs": [
            {"type": "video_link", "title": "Tutorial", "url": "https://youtube.com/watch?v=abc123",
             "source": "pptx", "term": 2, "lessons": [5]},
            {"type": "video_file", "title": "demo_video", "filename": "demo_video.mp4",
             "path": "/sources/term2/Lesson 5/demo_video.mp4", "url": "", "term": 2, "lessons": [5]},
        ],
    }
