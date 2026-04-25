from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest


SAMPLE_CONTACT = {
    "id": "contact-1",
    "first_name": "Alex",
    "last_name": "Smith",
    "company_name": "ACME Corp",
    "title": "CEO",
    "website": "https://acme.com",
    "email": "alex@acme.com",
    "industry_tag": "Electrical Supplies",
}

SAMPLE_SETTINGS = {
    "email_subject_didnt_pick_up": "Following up, <first_name>",
    "email_template_didnt_pick_up": "Hi <first_name>, I tried calling <company_name>.",
    "email_subject_interested": "Great chatting, <first_name>",
    "email_template_interested": "Hi <first_name>, thanks for your time at <company_name>.",
}

SAMPLE_TOKENS = {
    "access_token": "ya29.valid-token",
    "refresh_token": "1//refresh-token",
    "gmail_address": "sender@example.com",
    "token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
}


class TestGetOAuthUrl:
    @patch("app.services.email_service.settings")
    def test_builds_url_with_client_id(self, mock_settings):
        from app.services.email_service import get_oauth_url

        mock_settings.google_client_id = "test-client-id"

        url = get_oauth_url("user-123", "https://example.com/callback")

        assert "accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
        assert "response_type=code" in url
        assert "access_type=offline" in url
        assert "state=user-123" in url

    @patch("app.services.email_service.settings")
    def test_includes_gmail_scopes(self, mock_settings):
        from app.services.email_service import get_oauth_url

        mock_settings.google_client_id = "test-client-id"

        url = get_oauth_url("user-1", "https://example.com/cb")

        assert "gmail.send" in url
        assert "userinfo.email" in url


class TestExchangeCode:
    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.settings")
    def test_exchanges_code_successfully(self, mock_settings, mock_post):
        from app.services.email_service import exchange_code

        mock_settings.google_client_id = "client-id"
        mock_settings.google_client_secret = "client-secret"
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "ya29.new", "refresh_token": "1//rt"},
            raise_for_status=lambda: None,
        )

        result = exchange_code("auth-code-123", "https://example.com/callback")

        assert result["access_token"] == "ya29.new"
        mock_post.assert_called_once()
        call_data = mock_post.call_args.kwargs["data"]
        assert call_data["code"] == "auth-code-123"
        assert call_data["client_id"] == "client-id"
        assert call_data["grant_type"] == "authorization_code"

    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.settings")
    def test_raises_on_http_error(self, mock_settings, mock_post):
        from app.services.email_service import exchange_code

        mock_settings.google_client_id = "id"
        mock_settings.google_client_secret = "secret"
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "bad", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            exchange_code("bad-code", "https://example.com/cb")


class TestRefreshAccessToken:
    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.settings")
    def test_refreshes_successfully(self, mock_settings, mock_post):
        from app.services.email_service import refresh_access_token

        mock_settings.google_client_id = "id"
        mock_settings.google_client_secret = "secret"
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "ya29.refreshed", "expires_in": 3600},
            raise_for_status=lambda: None,
        )

        result = refresh_access_token("1//old-refresh")

        assert result["access_token"] == "ya29.refreshed"
        call_data = mock_post.call_args.kwargs["data"]
        assert call_data["refresh_token"] == "1//old-refresh"
        assert call_data["grant_type"] == "refresh_token"


class TestGetGmailAddress:
    @patch("app.services.email_service.httpx.get")
    def test_returns_email(self, mock_get):
        from app.services.email_service import get_gmail_address

        mock_get.return_value = MagicMock(
            json=lambda: {"email": "user@gmail.com"},
            raise_for_status=lambda: None,
        )

        assert get_gmail_address("ya29.token") == "user@gmail.com"
        assert "Bearer ya29.token" in mock_get.call_args.kwargs["headers"]["Authorization"]

    @patch("app.services.email_service.httpx.get")
    def test_returns_empty_when_no_email(self, mock_get):
        from app.services.email_service import get_gmail_address

        mock_get.return_value = MagicMock(
            json=lambda: {},
            raise_for_status=lambda: None,
        )

        assert get_gmail_address("ya29.token") == ""


class TestGetValidAccessToken:
    @patch("app.services.email_service.email_repo")
    def test_returns_existing_token_if_not_expired(self, mock_repo):
        from app.services.email_service import _get_valid_access_token

        mock_repo.get_gmail_tokens.return_value = SAMPLE_TOKENS
        db = MagicMock()

        token, address = _get_valid_access_token(db, "user-1")

        assert token == "ya29.valid-token"
        assert address == "sender@example.com"

    @patch("app.services.email_service.refresh_access_token")
    @patch("app.services.email_service.email_repo")
    def test_refreshes_expired_token(self, mock_repo, mock_refresh):
        from app.services.email_service import _get_valid_access_token

        expired_tokens = {
            **SAMPLE_TOKENS,
            "token_expiry": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }
        mock_repo.get_gmail_tokens.return_value = expired_tokens
        mock_refresh.return_value = {"access_token": "ya29.new", "expires_in": 3600}
        db = MagicMock()

        token, address = _get_valid_access_token(db, "user-1")

        assert token == "ya29.new"
        mock_refresh.assert_called_once_with("1//refresh-token")
        mock_repo.upsert_gmail_tokens.assert_called_once()

    @patch("app.services.email_service.email_repo")
    def test_raises_when_not_connected(self, mock_repo):
        from app.services.email_service import _get_valid_access_token

        mock_repo.get_gmail_tokens.return_value = None
        db = MagicMock()

        with pytest.raises(ValueError, match="Gmail not connected"):
            _get_valid_access_token(db, "user-1")

    @patch("app.services.email_service.refresh_access_token")
    @patch("app.services.email_service.email_repo")
    def test_refreshes_when_no_expiry_set(self, mock_repo, mock_refresh):
        from app.services.email_service import _get_valid_access_token

        tokens_no_expiry = {**SAMPLE_TOKENS, "token_expiry": None}
        mock_repo.get_gmail_tokens.return_value = tokens_no_expiry
        mock_refresh.return_value = {"access_token": "ya29.refreshed", "expires_in": 3600}
        db = MagicMock()

        token, _ = _get_valid_access_token(db, "user-1")

        assert token == "ya29.refreshed"
        mock_refresh.assert_called_once()


class TestRenderTemplate:
    def test_all_variables(self):
        from app.services.email_service import render_template

        template = "Hi <first_name> <last_name> at <company_name> (<title>), see <website>. From <your_name>. Industry: <type>."
        result = render_template(template, SAMPLE_CONTACT, sender_name="Bob")

        assert result == "Hi Alex Smith at ACME Corp (CEO), see https://acme.com. From Bob. Industry: Electrical Supplies."

    def test_missing_values_default_to_empty(self):
        from app.services.email_service import render_template

        template = "Hi <first_name>, we help <company_name>."
        result = render_template(template, {"first_name": "Jane"})

        assert result == "Hi Jane, we help ."

    def test_no_placeholders(self):
        from app.services.email_service import render_template

        result = render_template("Static message.", {})
        assert result == "Static message."

    def test_sender_name_variable(self):
        from app.services.email_service import render_template

        result = render_template("Best, <your_name>", {}, sender_name="Alice")
        assert result == "Best, Alice"


class TestGetDraft:
    @patch("app.services.email_service.settings_repo")
    @patch("app.services.email_service.contact_repo")
    def test_renders_draft_successfully(self, mock_contact_repo, mock_settings_repo):
        from app.services.email_service import get_draft

        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_settings_repo.get_settings.return_value = SAMPLE_SETTINGS
        db = MagicMock()

        result = get_draft(db, "contact-1", "didnt_pick_up", sender_name="Bob")

        assert result["to"] == "alex@acme.com"
        assert "Alex" in result["subject"]
        assert "ACME Corp" in result["body"]
        assert result["contact_name"] == "Alex Smith"

    @patch("app.services.email_service.settings_repo")
    @patch("app.services.email_service.contact_repo")
    def test_interested_template(self, mock_contact_repo, mock_settings_repo):
        from app.services.email_service import get_draft

        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_settings_repo.get_settings.return_value = SAMPLE_SETTINGS
        db = MagicMock()

        result = get_draft(db, "contact-1", "interested")

        assert "chatting" in result["subject"]
        assert "thanks" in result["body"]

    @patch("app.services.email_service.contact_repo")
    def test_raises_for_missing_contact(self, mock_contact_repo):
        from app.services.email_service import get_draft

        mock_contact_repo.get_contact.return_value = None
        db = MagicMock()

        with pytest.raises(ValueError, match="not found"):
            get_draft(db, "bad-id", "didnt_pick_up")


class TestSendEmail:
    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.email_repo")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_sends_email_successfully(
        self, mock_get_token, mock_contact_repo, mock_email_repo, mock_post,
    ):
        from app.services.email_service import send_email

        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_email_repo.create_email_log.return_value = {"id": "log-1"}
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "gmail-msg-1"},
            raise_for_status=lambda: None,
        )
        db = MagicMock()

        result = send_email(db, "user-1", "contact-1", "Subject", "Body text")

        assert result["gmail_message_id"] == "gmail-msg-1"
        assert result["email_log"]["id"] == "log-1"
        mock_post.assert_called_once()
        mock_email_repo.create_email_log.assert_called_once()

    @patch("app.services.email_service.contact_repo")
    def test_raises_for_missing_contact(self, mock_contact_repo):
        from app.services.email_service import send_email

        mock_contact_repo.get_contact.return_value = None
        db = MagicMock()

        with pytest.raises(ValueError, match="not found"):
            send_email(db, "user-1", "bad-id", "Subject", "Body")

    @patch("app.services.email_service.contact_repo")
    def test_raises_for_contact_without_email(self, mock_contact_repo):
        from app.services.email_service import send_email

        mock_contact_repo.get_contact.return_value = {**SAMPLE_CONTACT, "email": None}
        db = MagicMock()

        with pytest.raises(ValueError, match="no email"):
            send_email(db, "user-1", "contact-1", "Subject", "Body")

    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.email_repo")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_logs_email_with_outcome_context(
        self, mock_get_token, mock_contact_repo, mock_email_repo, mock_post,
    ):
        from app.services.email_service import send_email

        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_email_repo.create_email_log.return_value = {"id": "log-2"}
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "g-2"},
            raise_for_status=lambda: None,
        )
        db = MagicMock()

        send_email(db, "user-1", "contact-1", "Subj", "Body", outcome_context="didnt_pick_up")

        log_data = mock_email_repo.create_email_log.call_args[0][1]
        assert log_data["outcome_context"] == "didnt_pick_up"
        assert log_data["recipient_email"] == "alex@acme.com"
        assert log_data["gmail_address"] == "sender@example.com"

    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_raises_on_gmail_api_error(
        self, mock_get_token, mock_contact_repo, mock_post,
    ):
        from app.services.email_service import send_email

        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "forbidden", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = resp
        db = MagicMock()

        with pytest.raises(httpx.HTTPStatusError):
            send_email(db, "user-1", "contact-1", "Subj", "Body")
