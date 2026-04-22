from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


SAMPLE_CONTACT = {
    "id": "c-1",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@acme.com",
    "person_linkedin_url": "https://linkedin.com/in/jane",
    "company_name": "ACME Corp",
    "website": "https://www.acme.com",
    "enrichment_status": "pending_enrichment",
}

SAMPLE_CONTACT_2 = {
    "id": "c-2",
    "first_name": "Bob",
    "last_name": "Smith",
    "email": "bob@beta.com",
    "person_linkedin_url": None,
    "company_name": "Beta Inc",
    "website": "https://beta.io",
    "enrichment_status": "pending_enrichment",
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestExtractDomain:
    def test_simple_url(self):
        from app.services.apollo_service import _extract_domain
        assert _extract_domain("https://acme.com") == "acme.com"

    def test_www_stripped(self):
        from app.services.apollo_service import _extract_domain
        assert _extract_domain("https://www.acme.com") == "acme.com"

    def test_no_scheme(self):
        from app.services.apollo_service import _extract_domain
        assert _extract_domain("acme.com") == "acme.com"

    def test_empty_string(self):
        from app.services.apollo_service import _extract_domain
        assert _extract_domain("") == ""

    def test_with_path(self):
        from app.services.apollo_service import _extract_domain
        assert _extract_domain("https://www.acme.com/about") == "acme.com"


class TestEnrichContacts:
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_returns_error_when_no_api_key(self, mock_httpx, mock_repo, mock_settings):
        mock_settings.apollo_api_key = ""
        mock_settings.backend_public_url = "https://example.com"
        db = MagicMock()

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, None)

        assert "error" in result
        mock_httpx.post.assert_not_called()

    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_returns_error_when_no_backend_url(self, mock_httpx, mock_repo, mock_settings):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = ""
        db = MagicMock()

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, None)

        assert "error" in result

    @patch("app.services.apollo_service.time")
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_enriches_pending_contacts(self, mock_httpx, mock_repo, mock_settings, mock_time):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = "https://backend.example.com"
        mock_time.sleep = MagicMock()

        db = MagicMock()
        db.table.return_value.select.return_value \
            .eq.return_value.execute.return_value = _make_execute_result([SAMPLE_CONTACT])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "matches": [{"id": "apollo-person-1", "first_name": "Jane"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp
        mock_repo.update_contact.return_value = None

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, None)

        assert result["enriched"] == 1
        assert result["total"] == 1
        mock_repo.update_contact.assert_called_once()
        update_args = mock_repo.update_contact.call_args[0]
        assert update_args[1] == "c-1"
        assert update_args[2]["enrichment_status"] == "enriching"
        assert update_args[2]["apollo_person_id"] == "apollo-person-1"

    @patch("app.services.apollo_service.time")
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_enriches_specific_contact_ids(self, mock_httpx, mock_repo, mock_settings, mock_time):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = "https://backend.example.com"
        mock_time.sleep = MagicMock()

        db = MagicMock()
        db.table.return_value.select.return_value \
            .in_.return_value.execute.return_value = _make_execute_result([SAMPLE_CONTACT])

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"matches": [{"id": "ap-1"}]}
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp
        mock_repo.update_contact.return_value = None

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, ["c-1"])

        assert result["total"] == 1
        db.table.return_value.select.return_value.in_.assert_called_once()

    @patch("app.services.apollo_service.time")
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_api_failure_marks_contacts_failed(self, mock_httpx, mock_repo, mock_settings, mock_time):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = "https://backend.example.com"
        mock_time.sleep = MagicMock()

        db = MagicMock()
        db.table.return_value.select.return_value \
            .eq.return_value.execute.return_value = _make_execute_result([SAMPLE_CONTACT])

        mock_httpx.post.side_effect = Exception("Connection refused")
        mock_repo.update_contact.return_value = None

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, None)

        mock_repo.update_contact.assert_called_once()
        update_args = mock_repo.update_contact.call_args[0]
        assert update_args[2]["enrichment_status"] == "enrichment_failed"

    @patch("app.services.apollo_service.time")
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_no_contacts_returns_zero(self, mock_httpx, mock_repo, mock_settings, mock_time):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = "https://backend.example.com"

        db = MagicMock()
        db.table.return_value.select.return_value \
            .eq.return_value.execute.return_value = _make_execute_result([])

        from app.services.apollo_service import enrich_contacts
        result = enrich_contacts(db, None)

        assert result == {"enriched": 0, "total": 0}
        mock_httpx.post.assert_not_called()

    @patch("app.services.apollo_service.time")
    @patch("app.services.apollo_service.settings")
    @patch("app.services.apollo_service.contact_repo")
    @patch("app.services.apollo_service.httpx")
    def test_webhook_url_constructed_correctly(self, mock_httpx, mock_repo, mock_settings, mock_time):
        mock_settings.apollo_api_key = "key-123"
        mock_settings.backend_public_url = "https://backend.example.com/"
        mock_time.sleep = MagicMock()

        db = MagicMock()
        db.table.return_value.select.return_value \
            .eq.return_value.execute.return_value = _make_execute_result([SAMPLE_CONTACT])

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"matches": [None]}
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp
        mock_repo.update_contact.return_value = None

        from app.services.apollo_service import enrich_contacts
        enrich_contacts(db, None)

        call_kwargs = mock_httpx.post.call_args
        assert call_kwargs.kwargs["json"]["webhook_url"] == "https://backend.example.com/apollo/webhook/phone"
