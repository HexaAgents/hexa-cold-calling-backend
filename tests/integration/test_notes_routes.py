from __future__ import annotations

from unittest.mock import MagicMock


SAMPLE_NOTE = {
    "id": "note-1",
    "contact_id": "c-1",
    "user_id": "test-user-id",
    "content": "Initial call — left voicemail",
    "note_date": "2025-01-15",
    "created_at": "2025-01-15T10:00:00",
    "updated_at": None,
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestCreateNote:
    def test_create_note(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_NOTE])

        resp = client.post("/contacts/c-1/notes", json={"content": "test note"})
        assert resp.status_code == 201
        assert resp.json()["id"] == "note-1"
        assert resp.json()["contact_id"] == "c-1"


class TestGetNotes:
    def test_get_notes(self, client, mock_supabase):
        second = {**SAMPLE_NOTE, "id": "note-2", "content": "Follow-up"}
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .order.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_NOTE, second])

        resp = client.get("/contacts/c-1/notes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestUpdateNote:
    def test_update_note(self, client, mock_supabase):
        updated = {**SAMPLE_NOTE, "content": "updated content"}
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([updated])

        resp = client.patch("/notes/note-1", json={"content": "updated content"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "updated content"


class TestDeleteNote:
    def test_delete_note(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_NOTE])

        resp = client.delete("/notes/note-1")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Note deleted"

    def test_delete_note_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.delete("/notes/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Note not found"
