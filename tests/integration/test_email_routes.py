from __future__ import annotations

from unittest.mock import MagicMock, patch


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
    "email_subject_interested": "Great chatting",
    "email_template_interested": "Hi <first_name>, thanks for your time.",
}


# ---------------------------------------------------------------------------
# OAuth URL
# ---------------------------------------------------------------------------

class TestOAuthUrl:
    @patch("app.services.email_service.settings")
    def test_returns_oauth_url(self, mock_settings, client, mock_supabase):
        mock_settings.google_client_id = "test-client-id"
        mock_settings.backend_public_url = "https://api.example.com"

        resp = client.get("/email/oauth/url")

        assert resp.status_code == 200
        url = resp.json()["url"]
        assert "accounts.google.com" in url
        assert "test-client-id" in url


# ---------------------------------------------------------------------------
# OAuth Callback
# ---------------------------------------------------------------------------

class TestOAuthCallback:
    @patch("app.services.email_service.get_gmail_address")
    @patch("app.services.email_service.exchange_code")
    @patch("app.routers.email.settings")
    def test_callback_success_redirects(
        self, mock_router_settings, mock_exchange, mock_gmail_addr,
        client, mock_supabase,
    ):
        mock_router_settings.backend_public_url = "https://api.example.com"
        mock_router_settings.frontend_url = "https://frontend.example.com"
        mock_exchange.return_value = {
            "access_token": "ya29.new",
            "refresh_token": "1//rt",
            "expires_in": 3600,
        }
        mock_gmail_addr.return_value = "user@gmail.com"

        mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(
            data=[{"user_id": "user-1"}]
        )

        resp = client.get(
            "/email/oauth/callback",
            params={"code": "auth-code", "state": "user-1"},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert "settings?gmail=connected" in resp.headers["location"]

    @patch("app.services.email_service.exchange_code")
    @patch("app.routers.email.settings")
    def test_callback_error_redirects_with_error(
        self, mock_router_settings, mock_exchange, client, mock_supabase,
    ):
        mock_router_settings.backend_public_url = "https://api.example.com"
        mock_router_settings.frontend_url = "https://frontend.example.com"
        mock_exchange.side_effect = Exception("token exchange failed")

        resp = client.get(
            "/email/oauth/callback",
            params={"code": "bad-code", "state": "user-1"},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert "gmail=error" in resp.headers["location"]


# ---------------------------------------------------------------------------
# OAuth Status
# ---------------------------------------------------------------------------

class TestOAuthStatus:
    def test_connected(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(
                data={"gmail_address": "user@gmail.com", "access_token": "tok"}
            )

        resp = client.get("/email/oauth/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["gmail_address"] == "user@gmail.com"

    def test_not_connected(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data=None)

        resp = client.get("/email/oauth/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["gmail_address"] is None


# ---------------------------------------------------------------------------
# OAuth Disconnect
# ---------------------------------------------------------------------------

class TestOAuthDisconnect:
    def test_disconnect(self, client, mock_supabase):
        mock_supabase.table.return_value.delete.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{"user_id": "test-user-id"}])

        resp = client.delete("/email/oauth/disconnect")

        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------

class TestDraft:
    @patch("app.services.email_service.settings_repo")
    @patch("app.services.email_service.contact_repo")
    def test_returns_draft(self, mock_contact_repo, mock_settings_repo, client, mock_supabase):
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_settings_repo.get_settings.return_value = SAMPLE_SETTINGS

        resp = client.post("/email/draft", json={
            "contact_id": "contact-1",
            "template_key": "didnt_pick_up",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["to"] == "alex@acme.com"
        assert "Alex" in body["subject"]
        assert body["contact_name"] == "Alex Smith"

    @patch("app.services.email_service.contact_repo")
    def test_draft_missing_contact(self, mock_contact_repo, client, mock_supabase):
        mock_contact_repo.get_contact.return_value = None

        resp = client.post("/email/draft", json={
            "contact_id": "bad-id",
            "template_key": "didnt_pick_up",
        })

        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

class TestSendEmail:
    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.email_repo")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_send_email_success(
        self, mock_get_token, mock_contact_repo, mock_email_repo, mock_post,
        client, mock_supabase,
    ):
        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_email_repo.create_email_log.return_value = {"id": "log-1", "subject": "Test"}
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "gmail-msg-1"},
            raise_for_status=lambda: None,
        )

        resp = client.post("/email/send", json={
            "contact_id": "contact-1",
            "subject": "Test Subject",
            "body": "Test body.",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["gmail_message_id"] == "gmail-msg-1"
        assert body["email_log"]["id"] == "log-1"

    @patch("app.services.email_service.contact_repo")
    def test_send_missing_contact_returns_400(self, mock_contact_repo, client, mock_supabase):
        mock_contact_repo.get_contact.return_value = None

        resp = client.post("/email/send", json={
            "contact_id": "bad-id",
            "subject": "Test",
            "body": "Body",
        })

        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    @patch("app.services.email_service.contact_repo")
    def test_send_no_email_returns_400(self, mock_contact_repo, client, mock_supabase):
        mock_contact_repo.get_contact.return_value = {**SAMPLE_CONTACT, "email": None}

        resp = client.post("/email/send", json={
            "contact_id": "contact-1",
            "subject": "Test",
            "body": "Body",
        })

        assert resp.status_code == 400
        assert "no email" in resp.json()["detail"]

    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_send_gmail_api_error_returns_500(
        self, mock_get_token, mock_contact_repo, mock_post,
        client, mock_supabase,
    ):
        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        resp_mock = MagicMock()
        resp_mock.raise_for_status.side_effect = Exception("Gmail API error")
        mock_post.return_value = resp_mock

        resp = client.post("/email/send", json={
            "contact_id": "contact-1",
            "subject": "Test",
            "body": "Body",
        })

        assert resp.status_code == 500
        assert "Email send failed" in resp.json()["detail"]

    @patch("app.services.email_service.httpx.post")
    @patch("app.services.email_service.email_repo")
    @patch("app.services.email_service.contact_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_send_with_outcome_context(
        self, mock_get_token, mock_contact_repo, mock_email_repo, mock_post,
        client, mock_supabase,
    ):
        mock_get_token.return_value = ("ya29.token", "sender@example.com")
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_email_repo.create_email_log.return_value = {"id": "log-1"}
        mock_post.return_value = MagicMock(
            json=lambda: {"id": "g-1"},
            raise_for_status=lambda: None,
        )

        resp = client.post("/email/send", json={
            "contact_id": "contact-1",
            "subject": "Follow up",
            "body": "Hi there",
            "outcome_context": "didnt_pick_up",
        })

        assert resp.status_code == 200
        log_data = mock_email_repo.create_email_log.call_args[0][1]
        assert log_data["outcome_context"] == "didnt_pick_up"


# ---------------------------------------------------------------------------
# Email Logs
# ---------------------------------------------------------------------------

class TestEmailLogs:
    def test_returns_logs(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(
                data=[
                    {"id": "log-1", "subject": "First"},
                    {"id": "log-2", "subject": "Second"},
                ]
            )

        resp = client.get("/email/logs/contact-1")

        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) == 2
        assert logs[0]["id"] == "log-1"

    def test_returns_empty_list(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/email/logs/nonexistent")

        assert resp.status_code == 200
        assert resp.json() == []
