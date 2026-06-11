from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_rpc_result(data):
    result = MagicMock()
    result.data = data
    return result


class TestReactivateContacts:
    def test_calls_rpc_and_returns_ids(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result(
            [{"id": "c-1"}, {"id": "c-2"}]
        )

        from app.services.reactivation_service import (
            REACTIVATE_MIN_OCCASIONS,
            REACTIVATE_STALE_DAYS,
            reactivate_contacts,
        )

        ids = reactivate_contacts(db)

        db.rpc.assert_called_once_with(
            "reactivate_stale_didnt_pickup_contacts",
            {
                "p_min_occasions": REACTIVATE_MIN_OCCASIONS,
                "p_stale_days": REACTIVATE_STALE_DAYS,
            },
        )
        assert ids == ["c-1", "c-2"]

    def test_no_eligible_contacts_returns_empty_list(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result([])

        from app.services.reactivation_service import reactivate_contacts

        assert reactivate_contacts(db) == []

    def test_handles_none_rpc_data(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result(None)

        from app.services.reactivation_service import reactivate_contacts

        assert reactivate_contacts(db) == []

    def test_never_triggers_enrichment(self):
        """Refeed is DB-only: reactivation must never call Apollo enrichment."""
        with patch("app.services.apollo_service.enrich_contacts") as mock_enrich:
            db = MagicMock()
            db.rpc.return_value.execute.return_value = _make_rpc_result(
                [{"id": "c-1"}]
            )

            from app.services.reactivation_service import reactivate_contacts

            reactivate_contacts(db)
            mock_enrich.assert_not_called()
