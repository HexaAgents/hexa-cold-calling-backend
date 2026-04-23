from __future__ import annotations

from unittest.mock import MagicMock


SAMPLE_BATCH = {
    "id": "batch-1",
    "user_id": "test-user-id",
    "filename": "test.csv",
    "total_rows": 1,
    "processed_rows": 0,
    "stored_rows": 0,
    "discarded_rows": 0,
    "status": "processing",
    "created_at": "2025-01-01T00:00:00",
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestUploadCSV:
    def test_upload_csv_valid(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_BATCH])

        resp = client.post(
            "/imports/upload",
            files={"file": ("leads.csv", b"Company Name\nACME Corp", "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["batch_id"] == "batch-1"
        assert body["total_rows"] == 1
        assert body["status"] == "processing"

    def test_upload_non_csv(self, client, mock_supabase):
        resp = client.post(
            "/imports/upload",
            files={"file": ("data.txt", b"some text", "text/plain")},
        )
        assert resp.status_code == 400
        assert "CSV" in resp.json()["detail"]

    def test_upload_empty(self, client, mock_supabase):
        resp = client.post(
            "/imports/upload",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()


class TestRecentImports:
    def test_get_recent_imports(self, client, mock_supabase):
        second = {**SAMPLE_BATCH, "id": "batch-2", "filename": "second.csv"}
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .limit.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_BATCH, second])

        resp = client.get("/imports/recent")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body) == 2
        assert body[0]["id"] == "batch-1"
        assert body[1]["filename"] == "second.csv"

    def test_get_recent_imports_empty(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .limit.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.get("/imports/recent")
        assert resp.status_code == 200
        assert resp.json() == []


COMPLETED_BATCH = {**SAMPLE_BATCH, "status": "completed"}
FAILED_BATCH = {**SAMPLE_BATCH, "status": "failed"}


class TestDeleteImportBatch:
    def test_delete_completed_batch(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(COMPLETED_BATCH)
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{"id": "c-1"}])

        resp = client.delete("/imports/batch-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["batch_id"] == "batch-1"
        assert "deleted_contacts" in body

    def test_delete_failed_batch(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(FAILED_BATCH)
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.delete("/imports/batch-1")
        assert resp.status_code == 200

    def test_delete_processing_batch_rejected(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_BATCH)

        resp = client.delete("/imports/batch-1")
        assert resp.status_code == 409
        assert "still processing" in resp.json()["detail"]

    def test_delete_batch_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(None)

        resp = client.delete("/imports/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Import batch not found"
