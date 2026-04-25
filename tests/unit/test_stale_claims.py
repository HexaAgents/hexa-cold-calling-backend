from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.repositories.contact_repo import release_stale_claims, STALE_CLAIM_HOURS


class TestReleaseStaleClaimsRepo:
    def test_releases_stale_contacts(self):
        db = MagicMock()
        db.table.return_value.update.return_value.not_.is_.return_value \
            .is_.return_value.lt.return_value.execute.return_value = MagicMock(
                data=[{"id": "c-1"}, {"id": "c-2"}]
            )

        count = release_stale_claims(db)

        assert count == 2
        db.table.assert_called_with("contacts")
        update_call = db.table.return_value.update.call_args[0][0]
        assert update_call["assigned_to"] is None
        assert update_call["assigned_at"] is None

    def test_returns_zero_when_nothing_stale(self):
        db = MagicMock()
        db.table.return_value.update.return_value.not_.is_.return_value \
            .is_.return_value.lt.return_value.execute.return_value = MagicMock(data=[])

        count = release_stale_claims(db)

        assert count == 0

    def test_uses_correct_cutoff_time(self):
        db = MagicMock()
        db.table.return_value.update.return_value.not_.is_.return_value \
            .is_.return_value.lt.return_value.execute.return_value = MagicMock(data=[])

        now = datetime.now(timezone.utc)
        release_stale_claims(db)

        lt_call = db.table.return_value.update.return_value.not_.is_.return_value \
            .is_.return_value.lt
        cutoff_str = lt_call.call_args[0][1]
        cutoff = datetime.fromisoformat(cutoff_str)
        expected = now - timedelta(hours=STALE_CLAIM_HOURS)
        assert abs((cutoff - expected).total_seconds()) < 5

    def test_stale_claim_hours_is_ten(self):
        assert STALE_CLAIM_HOURS == 10


class TestReleaseStaleClaimsCalledByRoutes:
    @patch("app.routers.calls.contact_repo")
    def test_claim_next_calls_release_stale(self, mock_repo, client, mock_supabase):
        mock_repo.release_stale_claims.return_value = 0
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=[])

        client.post("/calls/next")

        mock_repo.release_stale_claims.assert_called_once_with(mock_supabase)

    @patch("app.routers.calls.contact_repo")
    def test_my_queue_calls_release_stale(self, mock_repo, client, mock_supabase):
        mock_repo.release_stale_claims.return_value = 0
        mock_repo.get_user_queue.return_value = []

        client.get("/calls/my-queue")

        mock_repo.release_stale_claims.assert_called_once_with(mock_supabase)
