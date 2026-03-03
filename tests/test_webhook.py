"""
Tests for drive_scanner.webhook — payload building and delivery.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from drive_scanner.webhook import build_payload, deliver_webhook, _build_change_entry, SCHEMA_VERSION


class TestBuildPayload:
    def test_empty_scan_no_changes(self):
        """Scan with no terms produces valid empty payload."""
        result = build_payload(
            {"scan_timestamp": "2026-03-03T20:00:00Z", "terms": {}},
            {}, {}
        )
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["event_type"] == "drive_scan_complete"
        assert result["has_changes"] is False
        assert result["summary"]["total_files_scanned"] == 0
        assert result["changes"] == {}
        assert result["activity"] == {}
        assert result["revisions"] == {}

    def test_payload_with_changes(self):
        """Payload correctly groups changes by term."""
        scan_results = {
            "scan_timestamp": "2026-03-03T20:00:00Z",
            "terms": {
                "term1": {
                    "changes": [
                        {
                            "id": "f1", "name": "Lesson 5.pptx",
                            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            "change_type": "NEW",
                            "folder_path": "Week 3", "modified_time": "2026-03-01",
                            "web_link": "", "size": 100, "md5": "abc",
                            "is_native_google": False, "native_type": None,
                            "owner_name": "Alan", "last_modifier_name": "Houssem",
                            "version": "5", "head_revision_id": "r1",
                        },
                        {
                            "id": "f2", "name": "Lesson 6.pptx",
                            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            "change_type": "UNCHANGED",
                            "folder_path": "Week 3", "modified_time": "2026-02-01",
                            "web_link": "", "size": 200, "md5": "def",
                            "is_native_google": False, "native_type": None,
                            "owner_name": "Alan", "last_modifier_name": "Alan",
                            "version": "3", "head_revision_id": "r2",
                        },
                    ],
                },
            },
        }
        result = build_payload(scan_results, {}, {})
        assert result["has_changes"] is True
        assert result["summary"]["total_files_scanned"] == 2
        assert result["summary"]["total_changed"] == 1
        assert result["summary"]["new"] == 1
        assert "term1" in result["changes"]
        assert len(result["changes"]["term1"]) == 1
        assert result["changes"]["term1"][0]["file_name"] == "Lesson 5.pptx"

    def test_payload_includes_activity(self):
        """Activity data is included in payload."""
        activity = {"term3": [{"timestamp": "2026-03-03T10:14:04Z", "actors": [], "actions": [], "targets": []}]}
        result = build_payload(
            {"scan_timestamp": "2026-03-03T20:00:00Z", "terms": {}},
            activity, {}
        )
        assert "term3" in result["activity"]

    def test_payload_includes_revisions(self):
        """Revision data is included in payload."""
        revisions = {
            "file_1": {
                "name": "Lesson 13.pptx",
                "term": "term3",
                "folder_path": "Week 7",
                "revisions": [{"id": "r1", "time": "2026-02-23T09:13:25Z"}],
            }
        }
        result = build_payload(
            {"scan_timestamp": "2026-03-03T20:00:00Z", "terms": {}},
            {}, revisions
        )
        assert "file_1" in result["revisions"]
        assert result["revisions"]["file_1"]["file_name"] == "Lesson 13.pptx"

    def test_summary_counts_all_change_types(self):
        """Summary correctly counts each change type."""
        changes = [
            {"id": "1", "name": "a", "change_type": "NEW", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": ""},
            {"id": "2", "name": "b", "change_type": "MODIFIED", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": ""},
            {"id": "3", "name": "c", "change_type": "DELETED", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": ""},
            {"id": "4", "name": "d", "change_type": "RENAMED", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": "", "previous_name": "old_d"},
            {"id": "5", "name": "e", "change_type": "METADATA_CHANGED", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": ""},
            {"id": "6", "name": "f", "change_type": "UNCHANGED", "folder_path": "", "modified_time": "", "web_link": "", "size": 0, "md5": "", "is_native_google": False, "native_type": None, "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "", "mime_type": ""},
        ]
        scan = {"scan_timestamp": "T", "terms": {"term1": {"changes": changes}}}
        result = build_payload(scan, {}, {})
        s = result["summary"]
        assert s["total_files_scanned"] == 6
        assert s["total_changed"] == 5
        assert s["new"] == 1
        assert s["modified"] == 1
        assert s["deleted"] == 1
        assert s["renamed"] == 1
        assert s["metadata_changed"] == 1


class TestBuildChangeEntry:
    def test_lesson_extraction(self):
        """Change entry extracts lesson numbers from file path."""
        change = {
            "id": "f1", "name": "Lesson 5.pptx", "mime_type": "", "change_type": "NEW",
            "folder_path": "Week 3", "modified_time": "", "web_link": "", "size": 0,
            "md5": "", "is_native_google": False, "native_type": None,
            "owner_name": "", "last_modifier_name": "", "version": "", "head_revision_id": "",
        }
        entry = _build_change_entry(change)
        assert entry["lessons"] == [5]

    def test_previous_md5_included(self):
        """MODIFIED changes include previous_md5."""
        change = {
            "id": "f1", "name": "f.pptx", "mime_type": "", "change_type": "MODIFIED",
            "folder_path": "", "modified_time": "", "web_link": "", "size": 0,
            "md5": "new", "previous_md5": "old", "is_native_google": False,
            "native_type": None, "owner_name": "", "last_modifier_name": "",
            "version": "", "head_revision_id": "",
        }
        entry = _build_change_entry(change)
        assert entry["previous_md5"] == "old"

    def test_previous_name_included(self):
        """RENAMED changes include previous_name."""
        change = {
            "id": "f1", "name": "new.pptx", "mime_type": "", "change_type": "RENAMED",
            "folder_path": "", "modified_time": "", "web_link": "", "size": 0,
            "md5": "", "previous_name": "old.pptx", "is_native_google": False,
            "native_type": None, "owner_name": "", "last_modifier_name": "",
            "version": "", "head_revision_id": "",
        }
        entry = _build_change_entry(change)
        assert entry["previous_name"] == "old.pptx"


class TestDeliverWebhook:
    def test_no_url_returns_false(self):
        """No webhook URL configured → returns failure tuple."""
        with patch("drive_scanner.webhook.EXTERNAL_WEBHOOK_URL", ""):
            success, status, error = deliver_webhook({"test": True})
            assert success is False
            assert "No webhook URL" in error

    def test_explicit_url_override(self):
        """Explicit URL overrides env var."""
        with patch("drive_scanner.webhook.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            success, status, error = deliver_webhook(
                {"test": True},
                webhook_url="https://example.com/hook"
            )
            assert success is True
            assert status == 200

    def test_delivery_failure_returns_error(self):
        """Network error returns failure with error message."""
        with patch("drive_scanner.webhook.urllib.request.urlopen", side_effect=Exception("Connection refused")):
            success, status, error = deliver_webhook(
                {"test": True},
                webhook_url="https://example.com/hook"
            )
            assert success is False
            assert "Connection refused" in error

    def test_payload_serialized_as_json(self):
        """Payload is correctly serialized as JSON in the request."""
        with patch("drive_scanner.webhook.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            payload = {"schema_version": "1.0", "has_changes": True}
            deliver_webhook(payload, webhook_url="https://example.com/hook")

            call_args = mock_open.call_args
            request_obj = call_args[0][0]
            sent_data = json.loads(request_obj.data.decode("utf-8"))
            assert sent_data == payload
