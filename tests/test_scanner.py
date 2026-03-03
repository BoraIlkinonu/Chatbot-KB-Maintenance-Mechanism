"""
Tests for drive_scanner.scanner — detect_changes() unit tests.
"""

import pytest
from drive_scanner.scanner import detect_changes, _sanitize_name


# ──────────────────────────────────────────────────────────
# _sanitize_name
# ──────────────────────────────────────────────────────────

class TestSanitizeName:
    def test_clean_name_unchanged(self):
        assert _sanitize_name("Lesson 5.pptx") == "Lesson 5.pptx"

    def test_illegal_chars_replaced(self):
        assert _sanitize_name('file<>:name') == "file___name"

    def test_trailing_dots_stripped(self):
        assert _sanitize_name("name...") == "name"

    def test_trailing_spaces_stripped(self):
        assert _sanitize_name("name   ") == "name"

    def test_empty_becomes_unnamed(self):
        assert _sanitize_name("") == "_unnamed"

    def test_all_illegal_becomes_unnamed(self):
        assert _sanitize_name("...") == "_unnamed"

    def test_slash_replaced(self):
        assert _sanitize_name("path/file") == "path_file"

    def test_quotes_replaced(self):
        assert _sanitize_name('"quoted"') == "_quoted_"


# ──────────────────────────────────────────────────────────
# detect_changes
# ──────────────────────────────────────────────────────────

class TestDetectChanges:
    def test_all_new_when_no_previous(self):
        """First scan — everything is NEW."""
        files = [
            {"id": "a", "name": "f1.pptx", "md5": "abc", "modified_time": "2026-03-01", "is_native_google": False},
            {"id": "b", "name": "f2.pptx", "md5": "def", "modified_time": "2026-03-01", "is_native_google": False},
        ]
        changes = detect_changes(files, {})
        assert len(changes) == 2
        assert all(c["change_type"] == "NEW" for c in changes)

    def test_unchanged_when_same(self):
        """Files with matching md5 and modified_time are UNCHANGED."""
        current = [
            {"id": "a", "name": "f1.pptx", "md5": "abc", "modified_time": "2026-03-01", "is_native_google": False},
        ]
        previous = {
            "a": {"id": "a", "name": "f1.pptx", "md5": "abc", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "UNCHANGED"

    def test_modified_by_md5(self):
        """Different md5 → MODIFIED."""
        current = [
            {"id": "a", "name": "f1.pptx", "md5": "new_hash", "modified_time": "2026-03-02", "is_native_google": False},
        ]
        previous = {
            "a": {"id": "a", "name": "f1.pptx", "md5": "old_hash", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "MODIFIED"
        assert changes[0]["previous_md5"] == "old_hash"

    def test_modified_native_google_by_timestamp(self):
        """Native Google files with different modified_time → MODIFIED (no md5)."""
        current = [
            {"id": "a", "name": "Doc", "md5": "", "modified_time": "2026-03-02", "is_native_google": True},
        ]
        previous = {
            "a": {"id": "a", "name": "Doc", "md5": "", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert changes[0]["change_type"] == "MODIFIED"

    def test_metadata_changed_non_native(self):
        """Non-native files with changed modified_time but same md5 → METADATA_CHANGED."""
        current = [
            {"id": "a", "name": "f1.pptx", "md5": "same", "modified_time": "2026-03-02", "is_native_google": False},
        ]
        previous = {
            "a": {"id": "a", "name": "f1.pptx", "md5": "same", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert changes[0]["change_type"] == "METADATA_CHANGED"

    def test_renamed(self):
        """Same id, same md5/time, different name → RENAMED."""
        current = [
            {"id": "a", "name": "New Name.pptx", "md5": "abc", "modified_time": "2026-03-01", "is_native_google": False},
        ]
        previous = {
            "a": {"id": "a", "name": "Old Name.pptx", "md5": "abc", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert changes[0]["change_type"] == "RENAMED"
        assert changes[0]["previous_name"] == "Old Name.pptx"

    def test_deleted(self):
        """File in previous but not in current → DELETED."""
        current = []
        previous = {
            "a": {"id": "a", "name": "deleted.pptx", "md5": "abc", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "DELETED"

    def test_mixed_changes(self):
        """Multiple change types in a single diff."""
        current = [
            {"id": "a", "name": "unchanged.pptx", "md5": "aaa", "modified_time": "2026-03-01", "is_native_google": False},
            {"id": "b", "name": "modified.pptx", "md5": "new_b", "modified_time": "2026-03-02", "is_native_google": False},
            {"id": "d", "name": "brand_new.pptx", "md5": "ddd", "modified_time": "2026-03-03", "is_native_google": False},
        ]
        previous = {
            "a": {"id": "a", "name": "unchanged.pptx", "md5": "aaa", "modified_time": "2026-03-01"},
            "b": {"id": "b", "name": "modified.pptx", "md5": "old_b", "modified_time": "2026-03-01"},
            "c": {"id": "c", "name": "deleted.pptx", "md5": "ccc", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        types = {c["id"]: c["change_type"] for c in changes}
        assert types["a"] == "UNCHANGED"
        assert types["b"] == "MODIFIED"
        assert types["d"] == "NEW"
        assert types["c"] == "DELETED"

    def test_empty_md5_no_change_native(self):
        """Native Google files with empty md5 and same modified_time → UNCHANGED."""
        current = [
            {"id": "a", "name": "Doc", "md5": "", "modified_time": "2026-03-01", "is_native_google": True},
        ]
        previous = {
            "a": {"id": "a", "name": "Doc", "md5": "", "modified_time": "2026-03-01"},
        }
        changes = detect_changes(current, previous)
        assert changes[0]["change_type"] == "UNCHANGED"
