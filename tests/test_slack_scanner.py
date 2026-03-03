"""
Tests for drive_scanner.slack_notify — Slack notification formatting.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from drive_scanner.slack_notify import (
    send_slack, notify_scan_changes, notify_scan_error,
    notify_webhook_delivery, _term_label, _format_timestamp,
)


class TestTermLabel:
    def test_term1(self):
        assert _term_label("term1") == "Term 1"

    def test_term3(self):
        assert _term_label("term3") == "Term 3"

    def test_empty(self):
        assert _term_label("") == ""

    def test_non_matching(self):
        assert _term_label("other") == "other"


class TestFormatTimestamp:
    def test_iso_format(self):
        result = _format_timestamp("2026-03-03T14:22:00.000Z")
        assert "2026-03-03" in result
        assert "14:22" in result

    def test_empty_string(self):
        assert _format_timestamp("") == "unknown time"

    def test_none(self):
        assert _format_timestamp(None) == "unknown time"


class TestSendSlack:
    def test_no_webhook_url(self):
        """No webhook URL → returns False without error."""
        with patch("drive_scanner.slack_notify.SLACK_WEBHOOK_EXTERNAL", ""):
            result = send_slack("test message")
            assert result is False

    def test_successful_delivery(self):
        """Successful POST returns True."""
        with patch("drive_scanner.slack_notify.SLACK_WEBHOOK_EXTERNAL", "https://hooks.slack.com/test"):
            with patch("drive_scanner.slack_notify.urllib.request.urlopen") as mock_open:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_open.return_value = mock_resp

                result = send_slack("test message")
                assert result is True

    def test_network_error_returns_false(self):
        """Network error returns False without raising."""
        with patch("drive_scanner.slack_notify.SLACK_WEBHOOK_EXTERNAL", "https://hooks.slack.com/test"):
            with patch("drive_scanner.slack_notify.urllib.request.urlopen", side_effect=Exception("timeout")):
                result = send_slack("test message")
                assert result is False

    def test_blocks_included_in_payload(self):
        """Blocks are included in the JSON payload."""
        with patch("drive_scanner.slack_notify.SLACK_WEBHOOK_EXTERNAL", "https://hooks.slack.com/test"):
            with patch("drive_scanner.slack_notify.urllib.request.urlopen") as mock_open:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.__enter__ = MagicMock(return_value=mock_resp)
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_open.return_value = mock_resp

                blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]
                send_slack("test", blocks=blocks)

                call_args = mock_open.call_args
                request_obj = call_args[0][0]
                sent = json.loads(request_obj.data.decode("utf-8"))
                assert "blocks" in sent
                assert sent["blocks"] == blocks


class TestNotifyScanChanges:
    def test_no_changes_sends_zzz(self):
        """No changes sends a 'no changes' message."""
        payload = {
            "has_changes": False,
            "summary": {"total_files_scanned": 100},
            "changes": {},
        }
        with patch("drive_scanner.slack_notify.send_slack") as mock_send:
            mock_send.return_value = True
            notify_scan_changes(payload)
            msg = mock_send.call_args[0][0]
            assert "No changes" in msg
            assert "100" in msg

    def test_changes_grouped_by_term(self):
        """Changes are listed grouped by term."""
        payload = {
            "has_changes": True,
            "summary": {"total_changed": 2, "new": 1, "modified": 1, "deleted": 0, "renamed": 0, "metadata_changed": 0},
            "changes": {
                "term1": [
                    {"file_name": "Lesson 5.pptx", "change_type": "NEW", "lessons": [5]},
                ],
                "term3": [
                    {"file_name": "Lesson 13.pptx", "change_type": "MODIFIED", "lessons": [13]},
                ],
            },
        }
        with patch("drive_scanner.slack_notify.send_slack") as mock_send:
            mock_send.return_value = True
            notify_scan_changes(payload)
            msg = mock_send.call_args[0][0]
            assert "Term 1" in msg
            assert "Term 3" in msg
            assert "Lesson 5.pptx" in msg
            assert "Lesson 13.pptx" in msg


class TestNotifyScanError:
    def test_error_formatted(self):
        """Error message is included in notification."""
        with patch("drive_scanner.slack_notify.send_slack") as mock_send:
            mock_send.return_value = True
            notify_scan_error("Authentication failed")
            msg = mock_send.call_args[0][0]
            assert "Authentication failed" in msg
            assert "Error" in msg


class TestNotifyWebhookDelivery:
    def test_success_no_notification(self):
        """Successful delivery does not send Slack notification."""
        result = notify_webhook_delivery(True, 200, None)
        assert result is False

    def test_failure_sends_notification(self):
        """Failed delivery sends Slack notification."""
        with patch("drive_scanner.slack_notify.send_slack") as mock_send:
            mock_send.return_value = True
            notify_webhook_delivery(False, None, "Connection refused")
            msg = mock_send.call_args[0][0]
            assert "Failed" in msg
            assert "Connection refused" in msg
