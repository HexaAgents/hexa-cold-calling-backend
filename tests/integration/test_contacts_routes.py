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
    "company_description": "Distributes industrial supplies and MRO products. Serves mid-market clients across Europe.",
    "exa_scrape_success": True,
    "scoring_failed": False,
    "call_occasion_count": 2,
    "times_called": 3,
    "call_outcome": "no_answer",
    "messaging_status": None,
    "sms_sent": False,
    "sms_sent_after_calls": None,
    "sms_scheduled_at": None,
    "enrichment_status": None,
    "apollo_person_id": None,
    "assigned_to": None,
    "assigned_at": None,
    "created_at": "2025-01-01T00:00:00",
}


class TestGetLocations:
    def test_returns_distinct_locations(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .not_.return_value \
            .neq.return_value \
            .execute.return_value = _make_execute_result([
                {"city": "Berlin"}, {"city": "Munich"}, {"city": "Berlin"},
            ])

        resp = client.get("/contacts/locations")
        assert resp.status_code == 200
        body = resp.json()
        assert "cities" in body
        assert "states" in body
        assert "countries" in body


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


class TestDeletePhoneNumber:
    def test_delete_mobile_phone(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{**SAMPLE_CONTACT, "mobile_phone": None}])

        resp = client.request(
            "DELETE", "/contacts/c-1/phone-number",
            json={"phone_type": "mobile_phone"},
        )
        assert resp.status_code == 200
        assert "mobile_phone" in resp.json()["detail"]

    def test_delete_work_direct_phone(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{**SAMPLE_CONTACT, "work_direct_phone": None}])

        resp = client.request(
            "DELETE", "/contacts/c-1/phone-number",
            json={"phone_type": "work_direct_phone"},
        )
        assert resp.status_code == 200
        assert "work_direct_phone" in resp.json()["detail"]

    def test_delete_corporate_phone(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{**SAMPLE_CONTACT, "corporate_phone": None}])

        resp = client.request(
            "DELETE", "/contacts/c-1/phone-number",
            json={"phone_type": "corporate_phone"},
        )
        assert resp.status_code == 200
        assert "corporate_phone" in resp.json()["detail"]

    def test_delete_phone_invalid_type(self, client, mock_supabase):
        resp = client.request(
            "DELETE", "/contacts/c-1/phone-number",
            json={"phone_type": "fax_number"},
        )
        assert resp.status_code == 422

    def test_delete_phone_contact_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.request(
            "DELETE", "/contacts/nonexistent/phone-number",
            json={"phone_type": "mobile_phone"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Contact not found"


class TestListContactsWithSearch:
    def test_search_by_name(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .or_.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_CONTACT], count=1)

        resp = client.get("/contacts?search=Jane")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["contacts"][0]["first_name"] == "Jane"

    def test_search_by_phone(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .or_.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_CONTACT], count=1)

        resp = client.get("/contacts?search=%2B491234")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_search_with_outcome_filter(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .or_.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result([], count=0)

        resp = client.get("/contacts?search=ACME&outcome_filter=interested")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_search_empty_string_ignored(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .range.return_value \
            .execute.return_value = _make_execute_result([], count=0)

        resp = client.get("/contacts?search=")
        assert resp.status_code == 200
