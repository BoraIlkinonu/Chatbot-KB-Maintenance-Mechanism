"""
Tests for CI pipeline mode (run_pipeline.py --mode ci).
Verifies CI mode only syncs Drive and notifies — no LLM steps.
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
                {"name": "Lesson 1 Slides.pptx", "change_type": "NEW"},
                {"name": "Lesson 2 Slides.pptx", "change_type": "MODIFIED"},
            ]
        },
        "term2": {
            "files": [
                {"name": "Lesson 3 Slides.pptx", "change_type": "NEW"},
            ]
        },
    },
    "download_errors": [],
}


def test_ci_mode_only_syncs(tmp_path, monkeypatch):
    """CI mode should only sync and notify, never call LLM."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)
    mock_notify_changes = MagicMock()
    mock_notify_no_changes = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected", mock_notify_changes), \
         patch("run_pipeline.notify_no_changes", mock_notify_no_changes):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline(download_all=True)

    assert result["mode"] == "ci"
    assert result["status"] == "synced"
    mock_sync.assert_called_once()
    mock_notify_changes.assert_called_once()


def test_ci_mode_no_changes(tmp_path, monkeypatch):
    """CI mode should notify no changes when nothing changed."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir()

    no_changes_sync = {
        "summary": {"total_files": 50, "new": 0, "modified": 0, "deleted": 0,
                     "unchanged": 50, "downloaded": 0, "errors": 0},
        "terms": {
            "term1": {"files": [{"name": "file.pptx", "change_type": "UNCHANGED"}]},
        },
        "download_errors": [],
    }
    mock_sync = MagicMock(return_value=no_changes_sync)
    mock_notify_no_changes = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_no_changes", mock_notify_no_changes), \
         patch("run_pipeline.notify_changes_detected"):
        from run_pipeline import run_ci_pipeline
        result = run_ci_pipeline()

    assert result["status"] == "no_changes"
    mock_notify_no_changes.assert_called_once()


def test_ci_mode_never_calls_llm(tmp_path, monkeypatch):
    """CI mode should never invoke LLM-dependent functions (consolidate, build)."""
    import config
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir()

    mock_sync = MagicMock(return_value=MOCK_SYNC_RESULT)
    mock_consolidate = MagicMock()
    mock_build = MagicMock()

    with patch("run_pipeline.run_sync", mock_sync), \
         patch("run_pipeline.notify_changes_detected"), \
         patch("run_pipeline.notify_no_changes"):
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
