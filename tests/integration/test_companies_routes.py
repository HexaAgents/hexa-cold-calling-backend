from __future__ import annotations

from unittest.mock import MagicMock, patch


SAMPLE_CONTACT = {
    "id": "c-1",
    "first_name": "Jane",
    "last_name": "Doe",
    "title": "CEO",
    "company_name": "ACME Corp",
    "person_linkedin_url": None,
    "website": "https://acme.com",
    "company_linkedin_url": None,
    "employees": "50",
    "city": "Dallas",
    "state": "Texas",
    "country": "US",
    "timezone": None,
    "email": "jane@acme.com",
    "mobile_phone": "+1234567890",
    "work_direct_phone": None,
    "corporate_phone": None,
    "score": 85,
    "company_type": "distributor",
    "rationale": "Good fit",
    "rejection_reason": None,
    "company_description": "Industrial supplier",
    "industry_tag": "Electrical Supplies",
    "exa_scrape_success": True,
    "scoring_failed": False,
    "call_occasion_count": 0,
    "times_called": 0,
    "call_outcome": None,
    "messaging_status": None,
    "sms_sent": False,
    "sms_sent_after_calls": None,
    "sms_scheduled_at": None,
    "enrichment_status": None,
    "apollo_person_id": None,
    "assigned_to": None,
    "assigned_at": None,
    "retry_at": None,
    "created_at": "2025-01-01T00:00:00",
}


class TestListCompanies:
    @patch("app.repositories.contact_repo.get_all_companies")
    def test_returns_companies(self, mock_get, client, mock_supabase):
        mock_get.return_value = [
            {
                "company_name": "ACME Corp",
                "website": "https://acme.com",
                "company_linkedin_url": None,
                "company_description": "Industrial supplier",
                "employees": "50",
                "industry_tag": "Electrical",
                "city": "Dallas",
                "state": "Texas",
                "country": "US",
                "contact_count": 3,
                "avg_score": 80,
            },
        ]

        resp = client.get("/companies")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["company_name"] == "ACME Corp"
        assert data[0]["contact_count"] == 3

    @patch("app.repositories.contact_repo.get_all_companies")
    def test_returns_empty(self, mock_get, client, mock_supabase):
        mock_get.return_value = []

        resp = client.get("/companies")

        assert resp.status_code == 200
        assert resp.json() == []

    @patch("app.repositories.contact_repo.get_all_companies")
    def test_search(self, mock_get, client, mock_supabase):
        mock_get.return_value = []

        resp = client.get("/companies?search=ACME")

        assert resp.status_code == 200
        mock_get.assert_called_once_with(mock_supabase, search="ACME")


class TestCompanyDetail:
    @patch("app.repositories.contact_repo.get_contacts_by_company")
    def test_returns_detail(self, mock_get, client, mock_supabase):
        mock_get.return_value = [SAMPLE_CONTACT]

        resp = client.get("/companies/detail?company_name=ACME+Corp")

        assert resp.status_code == 200
        data = resp.json()
        assert data["company"]["company_name"] == "ACME Corp"
        assert data["company"]["website"] == "https://acme.com"
        assert len(data["contacts"]) == 1
        assert data["contacts"][0]["first_name"] == "Jane"

    @patch("app.repositories.contact_repo.get_contacts_by_company")
    def test_not_found(self, mock_get, client, mock_supabase):
        mock_get.return_value = []

        resp = client.get("/companies/detail?company_name=Unknown")

        assert resp.status_code == 404

    @patch("app.repositories.contact_repo.get_contacts_by_company")
    def test_aggregates_company_info(self, mock_get, client, mock_supabase):
        contact_no_website = {**SAMPLE_CONTACT, "id": "c-2", "website": None, "employees": None}
        mock_get.return_value = [contact_no_website, SAMPLE_CONTACT]

        resp = client.get("/companies/detail?company_name=ACME+Corp")

        data = resp.json()
        assert data["company"]["website"] == "https://acme.com"
        assert data["company"]["employees"] == "50"


SAMPLE_FLAG = {
    "id": "f-1",
    "company_key": "acme corp",
    "company_name": "ACME Corp",
    "reason": "Already has an AI provider",
    "details": "Mentioned on a call in June",
    "flagged_by": "u-1",
    "flagged_by_name": "Jane Doe",
    "created_at": "2026-06-12T00:00:00+00:00",
    "updated_at": "2026-06-12T00:00:00+00:00",
}


class TestGetCompanyFlag:
    @patch("app.repositories.company_flag_repo.get_flag")
    def test_returns_flag(self, mock_get, client, mock_supabase):
        mock_get.return_value = SAMPLE_FLAG

        resp = client.get("/companies/flag?company_name=ACME+Corp")

        assert resp.status_code == 200
        data = resp.json()
        assert data["reason"] == "Already has an AI provider"
        assert data["flagged_by_name"] == "Jane Doe"
        mock_get.assert_called_once_with(mock_supabase, "ACME Corp")

    @patch("app.repositories.company_flag_repo.get_flag")
    def test_returns_null_when_not_flagged(self, mock_get, client, mock_supabase):
        mock_get.return_value = None

        resp = client.get("/companies/flag?company_name=Unflagged+Co")

        assert resp.status_code == 200
        assert resp.json() is None

    def test_requires_company_name(self, client, mock_supabase):
        resp = client.get("/companies/flag")

        assert resp.status_code == 422


class TestSetCompanyFlag:
    @patch("app.repositories.company_flag_repo.upsert_flag")
    def test_creates_flag(self, mock_upsert, client, mock_supabase):
        mock_upsert.return_value = SAMPLE_FLAG

        resp = client.put(
            "/companies/flag",
            json={
                "company_name": "ACME Corp",
                "reason": "Already has an AI provider",
                "details": "Mentioned on a call in June",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["reason"] == "Already has an AI provider"
        kwargs = mock_upsert.call_args.kwargs
        assert kwargs["company_name"] == "ACME Corp"
        assert kwargs["reason"] == "Already has an AI provider"
        assert kwargs["details"] == "Mentioned on a call in June"
        assert kwargs["flagged_by"]

    @patch("app.repositories.company_flag_repo.upsert_flag")
    def test_details_optional(self, mock_upsert, client, mock_supabase):
        mock_upsert.return_value = {**SAMPLE_FLAG, "details": None}

        resp = client.put(
            "/companies/flag",
            json={"company_name": "ACME Corp", "reason": "Too large for us to service"},
        )

        assert resp.status_code == 200
        assert resp.json()["details"] is None

    def test_rejects_empty_reason(self, client, mock_supabase):
        resp = client.put(
            "/companies/flag",
            json={"company_name": "ACME Corp", "reason": ""},
        )

        assert resp.status_code == 422


class TestRemoveCompanyFlag:
    @patch("app.repositories.company_flag_repo.delete_flag")
    def test_removes_flag(self, mock_delete, client, mock_supabase):
        mock_delete.return_value = True

        resp = client.delete("/companies/flag?company_name=ACME+Corp")

        assert resp.status_code == 200
        mock_delete.assert_called_once_with(mock_supabase, "ACME Corp")

    @patch("app.repositories.company_flag_repo.delete_flag")
    def test_404_when_not_flagged(self, mock_delete, client, mock_supabase):
        mock_delete.return_value = False

        resp = client.delete("/companies/flag?company_name=Unflagged+Co")

        assert resp.status_code == 404
