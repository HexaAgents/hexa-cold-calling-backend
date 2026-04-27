from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.scheduled_call_repo import (
    create_scheduled_call,
    get_scheduled_calls,
    get_scheduled_call,
    update_scheduled_call,
)


class TestCreateScheduledCall:
    def test_creates_and_returns(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "sc-1", "status": "pending"}]
        )

        result = create_scheduled_call(db, {"contact_id": "c-1", "user_id": "u-1", "scheduled_at": "2026-05-01T10:00:00Z"})

        assert result["id"] == "sc-1"
        db.table.assert_called_with("scheduled_calls")

    def test_returns_empty_on_no_data(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

        result = create_scheduled_call(db, {})

        assert result == {}


class TestGetScheduledCalls:
    def test_returns_all_pending(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(
                data=[{"id": "sc-1"}, {"id": "sc-2"}]
            )

        result = get_scheduled_calls(db)

        assert len(result) == 2

    def test_filters_by_user(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .order.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"id": "sc-1"}]
            )

        result = get_scheduled_calls(db, user_id="u-1")

        assert len(result) == 1

    def test_returns_empty(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(data=[])

        result = get_scheduled_calls(db)

        assert result == []


class TestGetScheduledCall:
    def test_returns_single(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"id": "sc-1", "status": "pending"}
            )

        result = get_scheduled_call(db, "sc-1")

        assert result["id"] == "sc-1"

    def test_returns_none_when_missing(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data=None)

        result = get_scheduled_call(db, "bad-id")

        assert result is None


class TestUpdateScheduledCall:
    def test_updates_and_returns(self):
        db = MagicMock()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(
                data=[{"id": "sc-1", "status": "completed"}]
            )

        result = update_scheduled_call(db, "sc-1", {"status": "completed"})

        assert result["status"] == "completed"

    def test_returns_none_on_no_data(self):
        db = MagicMock()
        db.table.return_value.update.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])

        result = update_scheduled_call(db, "bad-id", {"status": "completed"})

        assert result is None
