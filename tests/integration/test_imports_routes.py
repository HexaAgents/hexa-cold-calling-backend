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
    def test_get_recent_imports(self, client, mock_supabase, monkeypatch):
        # Decouple from the chained-mock dance; the repo function is what
        # the route actually depends on.
        from app.routers import imports as imports_router

        second = {**SAMPLE_BATCH, "id": "batch-2", "filename": "second.csv"}
        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_recent_batches",
            lambda db: [
                {**SAMPLE_BATCH, "has_filtered_csv": True},
                {**second, "has_filtered_csv": False},
            ],
        )

        resp = client.get("/imports/recent")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["id"] == "batch-1"
        assert body[0]["has_filtered_csv"] is True
        assert body[1]["filename"] == "second.csv"
        assert body[1]["has_filtered_csv"] is False

    def test_get_recent_imports_empty(self, client, mock_supabase, monkeypatch):
        from app.routers import imports as imports_router

        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_recent_batches",
            lambda db: [],
        )

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


class TestDownloadFilteredCsv:
    def test_download_returns_csv_with_attachment_name(
        self, client, mock_supabase, monkeypatch,
    ):
        from app.routers import imports as imports_router

        csv_text = "Company Name,Website\r\nACME Corp,https://acme.com\r\n"
        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_filtered_csv",
            lambda db, batch_id: (csv_text, "leads.csv"),
        )

        resp = client.get("/imports/batch-1/filtered-csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "leads.filtered.csv" in resp.headers["content-disposition"]
        assert resp.text == csv_text

    def test_download_missing_returns_404(self, client, mock_supabase, monkeypatch):
        from app.routers import imports as imports_router

        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_filtered_csv",
            lambda db, batch_id: None,
        )

        resp = client.get("/imports/batch-1/filtered-csv")
        assert resp.status_code == 404
        assert "not available" in resp.json()["detail"].lower()

    def test_download_preserves_extension_when_no_csv_suffix(
        self, client, mock_supabase, monkeypatch,
    ):
        from app.routers import imports as imports_router

        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_filtered_csv",
            lambda db, batch_id: ("Company Name\r\nACME\r\n", "no_extension"),
        )

        resp = client.get("/imports/batch-1/filtered-csv")
        assert resp.status_code == 200
        assert "no_extension.filtered.csv" in resp.headers["content-disposition"]


class TestDownloadDiscardedCsv:
    def test_download_returns_csv_with_attachment_name(
        self, client, mock_supabase, monkeypatch,
    ):
        from app.routers import imports as imports_router

        csv_text = "Company Name,Website\r\nBad Co,https://bad.com\r\n"
        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_discarded_csv",
            lambda db, batch_id: (csv_text, "leads.csv"),
        )

        resp = client.get("/imports/batch-1/discarded-csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "leads.discarded.csv" in resp.headers["content-disposition"]
        assert resp.text == csv_text

    def test_download_missing_returns_404(self, client, mock_supabase, monkeypatch):
        from app.routers import imports as imports_router

        monkeypatch.setattr(
            imports_router.import_batch_repo,
            "get_discarded_csv",
            lambda db, batch_id: None,
        )

        resp = client.get("/imports/batch-1/discarded-csv")
        assert resp.status_code == 404
        assert "not available" in resp.json()["detail"].lower()
