from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestScheduleCall:
    @patch("app.repositories.scheduled_call_repo.create_scheduled_call")
    def test_creates_scheduled_call(self, mock_create, client, mock_supabase):
        mock_create.return_value = {
            "id": "sc-1",
            "contact_id": "c-1",
            "user_id": "test-user-id",
            "scheduled_at": "2026-05-01T10:00:00Z",
            "notes": "Discuss pricing",
            "status": "pending",
            "created_at": "2026-04-27T00:00:00Z",
        }

        resp = client.post("/calls/schedule", json={
            "contact_id": "c-1",
            "scheduled_at": "2026-05-01T10:00:00Z",
            "notes": "Discuss pricing",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "sc-1"
        assert body["status"] == "pending"


class TestListScheduledCalls:
    @patch("app.repositories.scheduled_call_repo.get_scheduled_calls")
    def test_returns_enriched_calls(self, mock_get, client, mock_supabase):
        mock_get.return_value = [
            {
                "id": "sc-1",
                "contact_id": "c-1",
                "user_id": "test-user-id",
                "scheduled_at": "2026-05-01T10:00:00Z",
                "notes": None,
                "status": "pending",
                "created_at": "2026-04-27T00:00:00Z",
            },
        ]
        mock_supabase.table.return_value.select.return_value.in_.return_value \
            .execute.return_value = MagicMock(
                data=[{"id": "c-1", "first_name": "Jane", "last_name": "Doe", "company_name": "ACME"}]
            )
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": "test-user-id", "raw_user_meta_data": {"full_name": "Test User"}, "email": "test@test.com"}]
        )

        resp = client.get("/calls/scheduled")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["contact_name"] == "Jane Doe"
        assert body[0]["user_name"] == "Test User"

    @patch("app.repositories.scheduled_call_repo.get_scheduled_calls")
    def test_returns_empty(self, mock_get, client, mock_supabase):
        mock_get.return_value = []

        resp = client.get("/calls/scheduled")

        assert resp.status_code == 200
        assert resp.json() == []

    @patch("app.repositories.scheduled_call_repo.get_scheduled_calls")
    def test_mine_filter(self, mock_get, client, mock_supabase):
        mock_get.return_value = []

        resp = client.get("/calls/scheduled?mine=true")

        assert resp.status_code == 200
        mock_get.assert_called_once_with(mock_supabase, user_id="test-user-id")


class TestCompleteScheduledCall:
    @patch("app.repositories.scheduled_call_repo.update_scheduled_call")
    @patch("app.repositories.scheduled_call_repo.get_scheduled_call")
    def test_marks_completed(self, mock_get, mock_update, client, mock_supabase):
        mock_get.return_value = {"id": "sc-1", "status": "pending"}
        mock_update.return_value = {"id": "sc-1", "status": "completed"}

        resp = client.post("/calls/scheduled/sc-1/complete")

        assert resp.status_code == 200
        assert resp.json()["detail"] == "Marked as completed"
        mock_update.assert_called_once_with(mock_supabase, "sc-1", {"status": "completed"})

    @patch("app.repositories.scheduled_call_repo.get_scheduled_call")
    def test_not_found(self, mock_get, client, mock_supabase):
        mock_get.return_value = None

        resp = client.post("/calls/scheduled/bad-id/complete")

        assert resp.status_code == 404


class TestCancelScheduledCall:
    @patch("app.repositories.scheduled_call_repo.update_scheduled_call")
    @patch("app.repositories.scheduled_call_repo.get_scheduled_call")
    def test_cancels(self, mock_get, mock_update, client, mock_supabase):
        mock_get.return_value = {"id": "sc-1", "status": "pending"}
        mock_update.return_value = {"id": "sc-1", "status": "cancelled"}

        resp = client.post("/calls/scheduled/sc-1/cancel")

        assert resp.status_code == 200
        assert resp.json()["detail"] == "Cancelled"

    @patch("app.repositories.scheduled_call_repo.get_scheduled_call")
    def test_not_found(self, mock_get, client, mock_supabase):
        mock_get.return_value = None

        resp = client.post("/calls/scheduled/bad-id/cancel")

        assert resp.status_code == 404
