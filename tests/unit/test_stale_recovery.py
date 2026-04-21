from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.import_batch_repo import is_stale, recover_stale_imports


# ---------------------------------------------------------------------------
# is_stale tests
# ---------------------------------------------------------------------------

def _make_batch(status="processing", minutes_ago=15, use_updated_at=True):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    batch = {
        "id": "batch-1",
        "status": status,
        "created_at": ts,
    }
    if use_updated_at:
        batch["updated_at"] = ts
    return batch


class TestIsStale:
    def test_stale_processing_batch(self):
        batch = _make_batch(status="processing", minutes_ago=15)
        assert is_stale(batch) is True

    def test_recent_processing_batch_not_stale(self):
        batch = _make_batch(status="processing", minutes_ago=2)
        assert is_stale(batch) is False

    def test_completed_batch_never_stale(self):
        batch = _make_batch(status="completed", minutes_ago=60)
        assert is_stale(batch) is False

    def test_failed_batch_never_stale(self):
        batch = _make_batch(status="failed", minutes_ago=60)
        assert is_stale(batch) is False

    def test_falls_back_to_created_at_when_no_updated_at(self):
        batch = _make_batch(status="processing", minutes_ago=15, use_updated_at=False)
        assert is_stale(batch) is True

    def test_custom_threshold(self):
        batch = _make_batch(status="processing", minutes_ago=6)
        assert is_stale(batch, stale_minutes=5) is True
        assert is_stale(batch, stale_minutes=10) is False


# ---------------------------------------------------------------------------
# recover_stale_imports tests
# ---------------------------------------------------------------------------

class TestRecoverStaleImports:
    def test_marks_old_processing_batches_failed(self):
        db = MagicMock()

        select_result = MagicMock()
        select_result.data = [{"id": "stale-1"}, {"id": "stale-2"}]

        db.table.return_value \
            .select.return_value \
            .eq.return_value \
            .lt.return_value \
            .execute.return_value = select_result

        update_result = MagicMock()
        update_result.data = [{}]
        db.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = update_result

        recovered = recover_stale_imports(db)

        assert recovered == ["stale-1", "stale-2"]

    def test_no_stale_batches_returns_empty(self):
        db = MagicMock()

        select_result = MagicMock()
        select_result.data = []

        db.table.return_value \
            .select.return_value \
            .eq.return_value \
            .lt.return_value \
            .execute.return_value = select_result

        recovered = recover_stale_imports(db)

        assert recovered == []
        db.table.return_value.update.assert_not_called()


# ---------------------------------------------------------------------------
# Status endpoint stale detection (integration)
# ---------------------------------------------------------------------------

class TestStatusEndpointStaleDetection:
    def test_stale_batch_marked_failed_on_status_poll(self, client, mock_supabase):
        stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        stale_batch = {
            "id": "batch-stale",
            "user_id": "test-user-id",
            "filename": "old.csv",
            "total_rows": 100,
            "processed_rows": 30,
            "stored_rows": 20,
            "discarded_rows": 10,
            "status": "processing",
            "created_at": stale_ts,
            "updated_at": stale_ts,
        }

        single_result = MagicMock()
        single_result.data = stale_batch

        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = single_result

        update_result = MagicMock()
        update_result.data = [{**stale_batch, "status": "failed"}]
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = update_result

        resp = client.get("/imports/batch-stale/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_fresh_batch_not_marked_failed(self, client, mock_supabase):
        fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        fresh_batch = {
            "id": "batch-fresh",
            "user_id": "test-user-id",
            "filename": "new.csv",
            "total_rows": 100,
            "processed_rows": 30,
            "stored_rows": 20,
            "discarded_rows": 10,
            "status": "processing",
            "created_at": fresh_ts,
            "updated_at": fresh_ts,
        }

        single_result = MagicMock()
        single_result.data = fresh_batch

        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = single_result

        resp = client.get("/imports/batch-fresh/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"
