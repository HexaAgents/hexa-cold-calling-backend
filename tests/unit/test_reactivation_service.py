from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_rpc_result(data):
    result = MagicMock()
    result.data = data
    return result


class TestReactivateStaleDidntPickupContacts:
    @patch("app.services.reactivation_service.apollo_service")
    def test_reactivates_and_enriches_returned_ids(self, mock_apollo):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result(
            [{"id": "c-1"}, {"id": "c-2"}]
        )
        mock_apollo.enrich_contacts.return_value = {"enriched": 2, "total": 2}

        from app.services.reactivation_service import (
            REACTIVATE_MIN_OCCASIONS,
            REACTIVATE_STALE_DAYS,
            reactivate_stale_didnt_pickup_contacts,
        )

        result = reactivate_stale_didnt_pickup_contacts(db)

        db.rpc.assert_called_once_with(
            "reactivate_stale_didnt_pickup_contacts",
            {
                "p_min_occasions": REACTIVATE_MIN_OCCASIONS,
                "p_stale_days": REACTIVATE_STALE_DAYS,
            },
        )
        mock_apollo.enrich_contacts.assert_called_once_with(db, ["c-1", "c-2"])
        assert result["reactivated"] == 2
        assert result["enrichment"] == {"enriched": 2, "total": 2}

    @patch("app.services.reactivation_service.apollo_service")
    def test_no_eligible_contacts_skips_enrichment(self, mock_apollo):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result([])

        from app.services.reactivation_service import (
            reactivate_stale_didnt_pickup_contacts,
        )

        result = reactivate_stale_didnt_pickup_contacts(db)

        mock_apollo.enrich_contacts.assert_not_called()
        assert result["reactivated"] == 0
        assert result["enrichment"] == {"enriched": 0, "total": 0}

    @patch("app.services.reactivation_service.apollo_service")
    def test_handles_none_rpc_data(self, mock_apollo):
        db = MagicMock()
        db.rpc.return_value.execute.return_value = _make_rpc_result(None)

        from app.services.reactivation_service import (
            reactivate_stale_didnt_pickup_contacts,
        )

        result = reactivate_stale_didnt_pickup_contacts(db)

        mock_apollo.enrich_contacts.assert_not_called()
        assert result["reactivated"] == 0
