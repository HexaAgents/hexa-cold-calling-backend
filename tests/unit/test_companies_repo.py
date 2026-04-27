from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.contact_repo import get_all_companies, get_contacts_by_company


CONTACT_A1 = {
    "company_name": "ACME Corp",
    "website": "https://acme.com",
    "company_linkedin_url": "https://linkedin.com/company/acme",
    "company_description": "Industrial supplier",
    "employees": "50",
    "industry_tag": "Electrical Supplies",
    "score": 80,
    "city": "Dallas",
    "state": "Texas",
    "country": "US",
    "call_outcome": "interested",
}

CONTACT_A2 = {
    "company_name": "ACME Corp",
    "website": None,
    "company_linkedin_url": None,
    "company_description": None,
    "employees": None,
    "industry_tag": None,
    "score": 90,
    "city": None,
    "state": None,
    "country": None,
    "call_outcome": None,
}

CONTACT_B1 = {
    "company_name": "Beta Inc",
    "website": "https://beta.com",
    "company_linkedin_url": None,
    "company_description": "Pipe fittings",
    "employees": "20",
    "industry_tag": "Plumbing",
    "score": None,
    "city": "Miami",
    "state": "Florida",
    "country": "US",
    "call_outcome": "didnt_pick_up",
}


class TestGetAllCompanies:
    def test_groups_by_company_name(self):
        db = MagicMock()
        db.table.return_value.select.return_value.neq.return_value \
            .or_.return_value.neq.return_value \
            .execute.return_value = MagicMock(data=[CONTACT_A1, CONTACT_A2, CONTACT_B1])

        result = get_all_companies(db)

        assert len(result) == 2
        acme = next(r for r in result if r["company_name"] == "ACME Corp")
        assert acme["contact_count"] == 2
        assert acme["avg_score"] == 85
        assert acme["website"] == "https://acme.com"
        assert acme["industry_tag"] == "Electrical Supplies"

        beta = next(r for r in result if r["company_name"] == "Beta Inc")
        assert beta["contact_count"] == 1
        assert beta["avg_score"] is None

    def test_sorted_by_contact_count_desc(self):
        db = MagicMock()
        db.table.return_value.select.return_value.neq.return_value \
            .or_.return_value.neq.return_value \
            .execute.return_value = MagicMock(data=[CONTACT_A1, CONTACT_A2, CONTACT_B1])

        result = get_all_companies(db)

        assert result[0]["company_name"] == "ACME Corp"
        assert result[1]["company_name"] == "Beta Inc"

    def test_returns_empty_when_no_contacts(self):
        db = MagicMock()
        db.table.return_value.select.return_value.neq.return_value \
            .or_.return_value.neq.return_value \
            .execute.return_value = MagicMock(data=[])

        result = get_all_companies(db)

        assert result == []

    def test_search_filter(self):
        db = MagicMock()
        db.table.return_value.select.return_value.neq.return_value \
            .or_.return_value.neq.return_value \
            .ilike.return_value.execute.return_value = MagicMock(data=[CONTACT_A1])

        result = get_all_companies(db, search="ACME")

        assert len(result) == 1
        assert result[0]["company_name"] == "ACME Corp"

    def test_first_non_null_wins(self):
        """When first contact has nulls, second contact's values fill in."""
        db = MagicMock()
        reversed_order = [CONTACT_A2, CONTACT_A1]
        db.table.return_value.select.return_value.neq.return_value \
            .or_.return_value.neq.return_value \
            .execute.return_value = MagicMock(data=reversed_order)

        result = get_all_companies(db)

        acme = result[0]
        assert acme["website"] == "https://acme.com"
        assert acme["city"] == "Dallas"


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
