from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.import_batch_repo import (
    _attach_csv_flags,
    get_recent_batches,
)


def _make_result(data):
    result = MagicMock()
    result.data = data
    return result


class TestAttachCsvFlags:
    def test_flags_set_from_id_only_queries(self):
        """Flags come from id-only non-null queries (input, filtered,
        discarded — in _CSV_FLAGS order) without fetching CSV payloads."""
        db = MagicMock()
        chain = db.table.return_value.select.return_value.in_.return_value.not_.is_.return_value
        chain.execute.side_effect = [
            _make_result([{"id": "b-1"}]),                  # input_csv
            _make_result([{"id": "b-1"}, {"id": "b-2"}]),   # filtered_csv
            _make_result([]),                               # discarded_csv
        ]

        batches = [{"id": "b-1"}, {"id": "b-2"}]
        result = _attach_csv_flags(db, batches)

        assert result[0]["has_input_csv"] is True
        assert result[0]["has_filtered_csv"] is True
        assert result[0]["has_discarded_csv"] is False
        assert result[1]["has_input_csv"] is False
        assert result[1]["has_filtered_csv"] is True
        assert result[1]["has_discarded_csv"] is False

        # Only id is selected — the CSV text columns are never fetched.
        for c in db.table.return_value.select.call_args_list:
            assert c[0][0] == "id"

    def test_empty_batches_no_queries(self):
        db = MagicMock()
        assert _attach_csv_flags(db, []) == []
        db.table.assert_not_called()


class TestGetRecentBatches:
    def test_returns_all_batches_without_limit(self):
        """The full import history is returned — no .limit() on the query."""
        db = MagicMock()
        query = db.table.return_value.select.return_value.order.return_value
        query.execute.return_value = _make_result(
            [{"id": f"b-{i}"} for i in range(25)]
        )
        # Flag queries return nothing.
        db.table.return_value.select.return_value.in_.return_value.not_.is_.return_value.execute.return_value = _make_result([])

        batches = get_recent_batches(db)

        assert len(batches) == 25
        query.limit.assert_not_called()
        db.table.return_value.select.return_value.order.assert_called_once_with(
            "created_at", desc=True
        )
