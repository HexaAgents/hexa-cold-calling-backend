from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories import company_flag_repo


def _mock_db(rows: list[dict]) -> MagicMock:
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=rows
    )
    db.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=rows)
    db.table.return_value.delete.return_value.eq.return_value.execute.return_value = MagicMock(
        data=rows
    )
    return db


class TestCompanyFlagKey:
    def test_normalizes_case_and_whitespace(self):
        assert company_flag_repo.company_flag_key("  ACME Corp  ") == "acme corp"

    def test_empty(self):
        assert company_flag_repo.company_flag_key("") == ""
        assert company_flag_repo.company_flag_key(None) == ""


class TestGetFlag:
    def test_returns_row(self):
        row = {"id": "f-1", "company_key": "acme corp", "reason": "Too big"}
        db = _mock_db([row])

        assert company_flag_repo.get_flag(db, "ACME Corp") == row
        db.table.return_value.select.return_value.eq.assert_called_once_with(
            "company_key", "acme corp"
        )

    def test_returns_none_when_missing(self):
        db = _mock_db([])
        assert company_flag_repo.get_flag(db, "ACME Corp") is None

    def test_blank_name_short_circuits(self):
        db = _mock_db([])
        assert company_flag_repo.get_flag(db, "   ") is None
        db.table.assert_not_called()


class TestUpsertFlag:
    def test_payload_includes_normalized_key(self):
        row = {"id": "f-1"}
        db = _mock_db([row])

        result = company_flag_repo.upsert_flag(
            db,
            company_name="  ACME Corp ",
            reason="Already has an AI provider",
            details=None,
            flagged_by="u-1",
            flagged_by_name="Jane",
        )

        assert result == row
        payload = db.table.return_value.upsert.call_args.args[0]
        assert payload["company_key"] == "acme corp"
        assert payload["company_name"] == "ACME Corp"
        assert payload["reason"] == "Already has an AI provider"
        assert payload["flagged_by"] == "u-1"
        assert db.table.return_value.upsert.call_args.kwargs["on_conflict"] == "company_key"


class TestDeleteFlag:
    def test_returns_true_when_deleted(self):
        db = _mock_db([{"id": "f-1"}])
        assert company_flag_repo.delete_flag(db, "ACME Corp") is True

    def test_returns_false_when_missing(self):
        db = _mock_db([])
        assert company_flag_repo.delete_flag(db, "ACME Corp") is False

    def test_blank_name_short_circuits(self):
        db = _mock_db([])
        assert company_flag_repo.delete_flag(db, "") is False
        db.table.assert_not_called()
