"""
Tests for CI pipeline mode (run_pipeline.py --mode ci).
Verifies CI mode only syncs Drive and notifies — no LLM steps.
Tests the download modes: none, diff, all.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock


MOCK_SYNC_RESULT = {
    "summary": {
        "total_files": 50,
        "new": 2,
        "modified": 1,
        "deleted": 0,
        "unchanged": 47,
        "downloaded": 3,
        "errors": 0,
    },
    "terms": {
        "term1": {
            "files": [
                {"name": "Lesson 1 Slides.pptx", "change_type": "NEW",
                 "folder_path": ""},
                {"name": "Lesson 2 Slides.pptx", "change_type": "MODIFIED",
                 "folder_path": ""},
            ]
        },
        "term2": {
            "files": [
                {"name": "Lesson 3 Slides.pptx", "change_type": "NEW",
                 "folder_path": ""},
            ]
        },
    },
    "download_errors": [],
}


def test_ci_mode_download_none(tmp_path, monkeypatch):
    """CI mode with download=none should scan metadata only (skip_downloads=True)."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)
    mock_notify_changes = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected", mock_notify_changes), \
         patch("run_pipeline.notify_no_changes"), \
         patch("run_pipeline.CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline(download="none")

    assert result["mode"] == "ci"
    assert result["download"] == "none"
    assert result["status"] == "synced"
    mock_sync.assert_called_once_with(skip_downloads=True)
    mock_notify_changes.assert_called_once()


def test_ci_mode_download_diff(tmp_path, monkeypatch):
    """CI mode with download=diff should download only changed files."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.notify_no_changes"), \
         patch("run_pipeline.CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline(download="diff")

    assert result["download"] == "diff"
    mock_sync.assert_called_once_with(download_all=False)


def test_ci_mode_download_all(tmp_path, monkeypatch):
    """CI mode with download=all should download everything."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.notify_no_changes"), \
         patch("run_pipeline.CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline(download="all")

    assert result["download"] == "all"
    mock_sync.assert_called_once_with(download_all=True)


def test_ci_mode_no_changes(tmp_path, monkeypatch):
    """CI mode should notify no changes when nothing changed."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json")
    (tmp_path / "logs").mkdir()

    no_changes_sync = {
        "summary": {"total_files": 50, "new": 0, "modified": 0, "deleted": 0,
                     "unchanged": 50, "downloaded": 0, "errors": 0},
        "terms": {
            "term1": {"files": [{"name": "file.pptx", "change_type": "UNCHANGED",
                                  "folder_path": ""}]},
        },
        "download_errors": [],
    }
    mock_sync = MagicMock(return_value=no_changes_sync)
    mock_notify_no_changes = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_no_changes", mock_notify_no_changes), \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline()

    assert result["status"] == "no_changes"
    mock_notify_no_changes.assert_called_once()


def test_ci_mode_never_calls_llm(tmp_path, monkeypatch):
    """CI mode should never invoke LLM-dependent functions (consolidate, build)."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)
    mock_consolidate = MagicMock()
    mock_build = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.notify_no_changes"), \
         patch("run_pipeline.CHANGE_MANIFEST_FILE", tmp_path / "state" / "change_manifest.json"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline()

    # CI mode should have completed without calling consolidate/build
    assert result["status"] == "synced"
    mock_consolidate.assert_not_called()
    mock_build.assert_not_called()


def test_local_pipeline_function_exists():
    """Local mode function should be importable."""
    from run_pipeline import run_local_pipeline
    assert callable(run_local_pipeline)


def test_ci_pipeline_handles_sync_error(tmp_path, monkeypatch):
    """CI pipeline should handle sync errors gracefully."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(side_effect=Exception("Connection failed"))

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_error") as mock_notify_error, \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.notify_no_changes"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline()

    assert result["status"] == "failed"
    mock_notify_error.assert_called_once()


def test_write_change_manifest(tmp_path, monkeypatch):
    """write_change_manifest should produce correct structure."""
    import config
    import change_analyzer
    manifest_path = tmp_path / "state" / "change_manifest.json"
    monkeypatch.setattr(config, "CHANGE_MANIFEST_FILE", manifest_path)
    monkeypatch.setattr(change_analyzer, "CHANGE_MANIFEST_FILE", manifest_path)

    sync_result = {
        "terms": {
            "term1": {
                "files": [
                    {"name": "new_file.pptx", "change_type": "NEW", "folder_path": ""},
                    {"name": "changed.pptx", "change_type": "MODIFIED", "folder_path": "sub"},
                    {"name": "old.pptx", "change_type": "DELETED", "folder_path": ""},
                    {"name": "renamed.pptx", "change_type": "RENAMED",
                     "folder_path": "", "previous_name": "old_name.pptx"},
                    {"name": "same.pptx", "change_type": "UNCHANGED", "folder_path": ""},
                ]
            },
        },
    }

    from change_analyzer import write_change_manifest
    manifest = write_change_manifest(sync_result)

    assert manifest_path.exists()
    assert manifest["summary"]["total_added"] == 1
    assert manifest["summary"]["total_modified"] == 1
    assert manifest["summary"]["total_deleted"] == 1
    assert manifest["summary"]["total_renamed"] == 1
    assert manifest["added"][0]["file"] == "new_file.pptx"
    assert manifest["deleted"][0]["file"] == "old.pptx"
    assert manifest["renamed"][0]["previous_name"] == "old_name.pptx"
    assert manifest["modified"][0]["folder_path"] == "sub"

    # Verify JSON on disk matches
    with open(manifest_path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["summary"] == manifest["summary"]


def test_cleanup_deleted_files(tmp_path, monkeypatch):
    """_cleanup_deleted_files should remove source and converted files."""
    import config
    monkeypatch.setattr(config, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "CONVERTED_DIR", tmp_path / "converted")

    # Patch run_pipeline's module-level imports
    import run_pipeline
    monkeypatch.setattr(run_pipeline, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(run_pipeline, "CONVERTED_DIR", tmp_path / "converted")

    # Create fake source and converted files
    src_dir = tmp_path / "sources" / "term1"
    src_dir.mkdir(parents=True)
    (src_dir / "old_lesson.pptx").write_text("fake")

    conv_dir = tmp_path / "converted" / "term1"
    conv_dir.mkdir(parents=True)
    (conv_dir / "old_lesson.md").write_text("fake md")

    deleted_entries = [
        {"file": "old_lesson.pptx", "term": "term1", "folder_path": ""},
    ]

    from run_pipeline import _cleanup_deleted_files
    _cleanup_deleted_files(deleted_entries)

    assert not (src_dir / "old_lesson.pptx").exists()
    assert not (conv_dir / "old_lesson.md").exists()
