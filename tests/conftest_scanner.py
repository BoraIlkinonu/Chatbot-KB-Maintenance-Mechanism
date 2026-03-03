"""
Shared fixtures for drive_scanner tests.
Separate from main pipeline's conftest.py to avoid conflicts.
"""

import pytest


@pytest.fixture
def sample_files():
    """Sample file metadata list simulating a Drive scan."""
    return [
        {
            "id": "file_1",
            "name": "Lesson 5.pptx",
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "size": 17010823,
            "md5": "8b76f362abc123",
            "created_time": "2026-01-15T10:00:00.000Z",
            "modified_time": "2026-03-01T14:22:00.000Z",
            "version": "58",
            "head_revision_id": "0B6Qn123",
            "web_link": "https://docs.google.com/presentation/d/file_1/edit",
            "extension": "pptx",
            "parent_id": "folder_1",
            "folder_path": "Teacher Resources/Curriculum Content/Week 3",
            "shared": True,
            "description": "",
            "last_modifier_email": "houssem@example.com",
            "last_modifier_name": "Houssem Ben Amor",
            "owner_email": "alan@example.com",
            "owner_name": "Alan Mc Girr",
            "is_native_google": False,
            "native_type": None,
        },
        {
            "id": "file_2",
            "name": "Lesson 13.pptx",
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "size": 14284949,
            "md5": "def456789",
            "created_time": "2026-01-10T08:00:00.000Z",
            "modified_time": "2026-02-28T09:13:25.000Z",
            "version": "42",
            "head_revision_id": "0B6Qn456",
            "web_link": "https://docs.google.com/presentation/d/file_2/edit",
            "extension": "pptx",
            "parent_id": "folder_2",
            "folder_path": "Teacher Resources/Curriculum Content/Week 7",
            "shared": True,
            "description": "",
            "last_modifier_email": "ciaran@example.com",
            "last_modifier_name": "Ciaran OBrien",
            "owner_email": "alan@example.com",
            "owner_name": "Alan Mc Girr",
            "is_native_google": False,
            "native_type": None,
        },
        {
            "id": "file_3",
            "name": "LP4 Draft.docx",
            "mime_type": "application/vnd.google-apps.document",
            "size": 0,
            "md5": "",
            "created_time": "2026-02-01T12:00:00.000Z",
            "modified_time": "2026-03-02T16:45:00.000Z",
            "version": "15",
            "head_revision_id": "",
            "web_link": "https://docs.google.com/document/d/file_3/edit",
            "extension": "",
            "parent_id": "folder_3",
            "folder_path": "Teacher Resources/Lesson Plans",
            "shared": True,
            "description": "",
            "last_modifier_email": "teacher@example.com",
            "last_modifier_name": "Teacher User",
            "owner_email": "alan@example.com",
            "owner_name": "Alan Mc Girr",
            "is_native_google": True,
            "native_type": "google_doc",
        },
    ]


@pytest.fixture
def previous_files_by_id(sample_files):
    """Build a previous scan lookup from sample_files with older timestamps."""
    prev = {}
    for f in sample_files:
        prev_file = {**f}
        # Make the previous scan slightly older
        prev_file["modified_time"] = "2026-02-15T10:00:00.000Z"
        prev[f["id"]] = prev_file
    return prev
