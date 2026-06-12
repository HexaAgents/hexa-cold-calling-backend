from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.contact_repo import get_all_companies, get_contacts_by_company


SUMMARY_ACME = {
    "company_name": "ACME Corp",
    "website": "https://acme.com",
    "company_linkedin_url": "https://linkedin.com/company/acme",
    "company_description": "Industrial supplier",
    "employees": "50",
    "industry_tag": "Electrical Supplies",
    "city": "Dallas",
    "state": "Texas",
    "country": "US",
    "contact_count": 2,
    "avg_score": 85,
}


def _rpc_db(data):
    db = MagicMock()
    db.rpc.return_value.execute.return_value = MagicMock(data=data)
    return db


class TestGetAllCompanies:
    def test_returns_rpc_summaries(self):
        db = _rpc_db([SUMMARY_ACME])

        result = get_all_companies(db)

        db.rpc.assert_called_once_with("get_company_summaries", {"p_search": None})
        assert len(result) == 1
        assert result[0]["company_name"] == "ACME Corp"
        assert result[0]["contact_count"] == 2
        assert result[0]["avg_score"] == 85

    def test_passes_search_to_rpc(self):
        db = _rpc_db([SUMMARY_ACME])

        result = get_all_companies(db, search="ACME")

        db.rpc.assert_called_once_with("get_company_summaries", {"p_search": "ACME"})
        assert result[0]["company_name"] == "ACME Corp"

    def test_returns_empty_when_rpc_returns_none(self):
        db = _rpc_db(None)

        assert get_all_companies(db) == []


class TestGetContactsByCompany:
    def test_returns_contacts(self):
        db = MagicMock()
        full_contacts = [{"id": "c-1", "company_name": "ACME Corp", "score": 90}]
        db.table.return_value.select.return_value.eq.return_value \
            .neq.return_value.or_.return_value \
            .order.return_value.execute.return_value = MagicMock(data=full_contacts)

        result = get_contacts_by_company(db, "ACME Corp")

        assert len(result) == 1
        assert result[0]["company_name"] == "ACME Corp"

    def test_returns_empty_for_unknown_company(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .neq.return_value.or_.return_value \
            .order.return_value.execute.return_value = MagicMock(data=[])

        result = get_contacts_by_company(db, "Unknown Corp")

        assert result == []
