from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestEnrichEndpoint:
    @patch("app.services.apollo_service.enrich_contacts")
    def test_enrich_all(self, mock_enrich, client, mock_supabase):
        resp = client.post("/apollo/enrich", json={"enrich_all": True})
        assert resp.status_code == 200
        assert resp.json()["status"] == "enrichment_started"

    def test_enrich_requires_params(self, client, mock_supabase):
        resp = client.post("/apollo/enrich", json={})
        assert resp.status_code == 400

    @patch("app.services.apollo_service.enrich_contacts")
    def test_enrich_specific_ids(self, mock_enrich, client, mock_supabase):
        resp = client.post("/apollo/enrich", json={"contact_ids": ["c-1", "c-2"]})
        assert resp.status_code == 200
        assert resp.json()["status"] == "enrichment_started"


class TestEnrichStatus:
    def test_returns_counts(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([], count=5)

        resp = client.get("/apollo/enrich/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "pending_enrichment" in body
        assert "enriching" in body
        assert "enriched" in body
        assert "enrichment_failed" in body


class TestPhoneWebhook:
    def test_webhook_updates_contact(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{"id": "c-1"}])
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{"id": "c-1"}])

        payload = {
            "people": [
                {
                    "id": "apollo-person-1",
                    "status": "success",
                    "phone_numbers": [
                        {
                            "sanitized_number": "+15551234567",
                            "type_cd": "mobile",
                            "raw_number": "+1 555-123-4567",
                        },
                        {
                            "sanitized_number": "+15559876543",
                            "type_cd": "work",
                            "raw_number": "+1 555-987-6543",
                        },
                    ],
                }
            ]
        }

        resp = client.post("/apollo/webhook/phone", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["updated"] >= 0

    def test_webhook_empty_people(self, client, mock_supabase):
        resp = client.post("/apollo/webhook/phone", json={"people": []})
        assert resp.status_code == 200
        assert resp.json()["status"] == "no people in payload"

    def test_webhook_no_phone_numbers_still_marks_enriched(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{"id": "c-1"}])
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([{"id": "c-1"}])

        payload = {
            "people": [{"id": "apollo-person-1", "phone_numbers": []}]
        }

        resp = client.post("/apollo/webhook/phone", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_webhook_invalid_payload(self, client, mock_supabase):
        resp = client.post("/apollo/webhook/phone", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 200

    def test_webhook_person_without_id_skipped(self, client, mock_supabase):
        payload = {"people": [{"phone_numbers": []}]}
        resp = client.post("/apollo/webhook/phone", json=payload)
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0
