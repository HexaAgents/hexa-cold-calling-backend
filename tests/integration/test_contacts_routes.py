from __future__ import annotations

from unittest.mock import MagicMock


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
    "city": "Berlin",
    "country": "DE",
    "email": "jane@acme.com",
    "mobile_phone": "+491234567890",
    "work_direct_phone": None,
    "corporate_phone": None,
    "score": 85,
    "company_type": "B2B SaaS",
    "rationale": "Good fit",
    "rejection_reason": None,
    "exa_scrape_success": True,
    "scoring_failed": False,
    "call_occasion_count": 2,
    "call_outcome": "no_answer",
    "messaging_status": None,
    "sms_sent": False,
    "sms_sent_after_calls": None,
    "sms_scheduled_at": None,
    "created_at": "2025-01-01T00:00:00",
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestListContacts:
    def test_list_contacts_empty(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result([], count=0)

        resp = client.get("/contacts")
        assert resp.status_code == 200

        body = resp.json()
        assert body["contacts"] == []
        assert body["total"] == 0

    def test_list_contacts_with_data(self, client, mock_supabase):
        second = {**SAMPLE_CONTACT, "id": "c-2", "company_name": "Beta Inc"}
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result(
                [SAMPLE_CONTACT, second], count=2,
            )

        resp = client.get("/contacts")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body["contacts"]) == 2
        assert body["total"] == 2
        assert body["contacts"][0]["id"] == "c-1"
        assert body["contacts"][1]["company_name"] == "Beta Inc"


class TestGetContact:
    def test_get_contact_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_CONTACT)

        resp = client.get("/contacts/c-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "c-1"
        assert resp.json()["company_name"] == "ACME Corp"

    def test_get_contact_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(None)

        resp = client.get("/contacts/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Contact not found"


class TestUpdateContact:
    def test_update_contact(self, client, mock_supabase):
        updated = {**SAMPLE_CONTACT, "call_outcome": "interested"}
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([updated])

        resp = client.patch("/contacts/c-1", json={"call_outcome": "interested"})
        assert resp.status_code == 200
        assert resp.json()["call_outcome"] == "interested"

    def test_update_contact_empty_body(self, client, mock_supabase):
        resp = client.patch("/contacts/c-1", json={})
        assert resp.status_code == 400
        assert "No fields to update" in resp.json()["detail"]


class TestDeleteContact:
    def test_delete_contact(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_CONTACT])

        resp = client.delete("/contacts/c-1")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Contact deleted"

    def test_delete_contact_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.delete("/contacts/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Contact not found"
