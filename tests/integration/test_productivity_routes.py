from __future__ import annotations

from unittest.mock import MagicMock


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


def _make_mock_user(uid, full_name, email="user@example.com"):
    user = MagicMock()
    user.id = uid
    user.email = email
    user.user_metadata = {"full_name": full_name}
    return user


class TestProductivity:
    def test_returns_users_and_rows(self, client, mock_supabase):
        mock_supabase.auth.admin.list_users.return_value = [
            _make_mock_user("u1", "Alice Johnson"),
            _make_mock_user("u2", "Bob Smith"),
        ]

        mock_supabase.table.return_value \
            .select.return_value \
            .gte.return_value \
            .execute.return_value = _make_execute_result([
                {"user_id": "u1", "call_date": "2026-04-21"},
                {"user_id": "u1", "call_date": "2026-04-21"},
                {"user_id": "u2", "call_date": "2026-04-21"},
                {"user_id": "u1", "call_date": "2026-04-20"},
            ])

        resp = client.get("/productivity?days=7")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["users"]) == 2
        assert body["users"][0]["first_name"] == "Alice"
        assert body["users"][1]["first_name"] == "Bob"

        assert len(body["rows"]) == 2
        row_21 = next(r for r in body["rows"] if r["date"] == "2026-04-21")
        assert row_21["counts"]["u1"] == 2
        assert row_21["counts"]["u2"] == 1

        row_20 = next(r for r in body["rows"] if r["date"] == "2026-04-20")
        assert row_20["counts"]["u1"] == 1
        assert "u2" not in row_20["counts"]

    def test_empty_call_logs(self, client, mock_supabase):
        mock_supabase.auth.admin.list_users.return_value = [
            _make_mock_user("u1", "Alice Johnson"),
        ]
        mock_supabase.table.return_value \
            .select.return_value \
            .gte.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.get("/productivity?days=30")
        assert resp.status_code == 200

        body = resp.json()
        assert body["users"][0]["first_name"] == "Alice"
        assert body["rows"] == []

    def test_default_days_param(self, client, mock_supabase):
        mock_supabase.auth.admin.list_users.return_value = []
        mock_supabase.table.return_value \
            .select.return_value \
            .gte.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.get("/productivity")
        assert resp.status_code == 200

    def test_rows_sorted_descending(self, client, mock_supabase):
        mock_supabase.auth.admin.list_users.return_value = [
            _make_mock_user("u1", "Alice"),
        ]
        mock_supabase.table.return_value \
            .select.return_value \
            .gte.return_value \
            .execute.return_value = _make_execute_result([
                {"user_id": "u1", "call_date": "2026-04-18"},
                {"user_id": "u1", "call_date": "2026-04-20"},
                {"user_id": "u1", "call_date": "2026-04-19"},
            ])

        resp = client.get("/productivity?days=7")
        body = resp.json()
        dates = [r["date"] for r in body["rows"]]
        assert dates == sorted(dates, reverse=True)

    def test_user_without_full_name_uses_email(self, client, mock_supabase):
        user = MagicMock()
        user.id = "u1"
        user.email = "alice@example.com"
        user.user_metadata = {}
        mock_supabase.auth.admin.list_users.return_value = [user]
        mock_supabase.table.return_value \
            .select.return_value \
            .gte.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.get("/productivity")
        assert resp.status_code == 200
        assert resp.json()["users"][0]["first_name"] == "alice@example.com"
