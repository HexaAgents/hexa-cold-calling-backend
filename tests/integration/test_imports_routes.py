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
