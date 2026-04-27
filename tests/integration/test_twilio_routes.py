from __future__ import annotations

from unittest.mock import patch


class TestVoiceWebhook:
    def test_voice_webhook_returns_twiml(self, client):
        resp = client.post("/twilio/voice", data={"To": "+14155551234"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/xml"
        body = resp.text
        assert "<Dial" in body
        assert "+14155551234" in body

    def test_voice_webhook_empty_to(self, client):
        resp = client.post("/twilio/voice", data={"To": ""})
        assert resp.status_code == 200
        assert "application/xml" in resp.headers["content-type"]

    def test_voice_webhook_no_form_data(self, client):
        resp = client.post("/twilio/voice")
        assert resp.status_code == 200
        assert "<Dial" in resp.text

    def test_voice_webhook_defaults_to_us(self, client):
        resp = client.post("/twilio/voice", data={"To": "+14155551234"})
        assert resp.status_code == 200

    @patch("app.routers.twilio_webhooks.settings")
    def test_voice_webhook_selects_uk_number(self, mock_settings, client):
        mock_settings.twilio_phone_numbers = {"US": "+12184236138", "GB": "+441234567890"}
        mock_settings.twilio_phone_number = "+12184236138"

        resp = client.post("/twilio/voice", data={"To": "+441234567890", "Country": "GB"})

        assert resp.status_code == 200
        assert "+441234567890" in resp.text
        assert 'callerId="+441234567890"' in resp.text

    @patch("app.routers.twilio_webhooks.settings")
    def test_voice_webhook_falls_back_to_default(self, mock_settings, client):
        mock_settings.twilio_phone_numbers = {"US": "+12184236138"}
        mock_settings.twilio_phone_number = "+12184236138"

        resp = client.post("/twilio/voice", data={"To": "+61412345678", "Country": "AU"})

        assert resp.status_code == 200
        assert 'callerId="+12184236138"' in resp.text

    @patch("app.routers.twilio_webhooks.settings")
    def test_voice_webhook_country_param_defaults_to_us(self, mock_settings, client):
        mock_settings.twilio_phone_numbers = {"US": "+12184236138"}
        mock_settings.twilio_phone_number = "+12184236138"

        resp = client.post("/twilio/voice", data={"To": "+14155551234"})

        assert resp.status_code == 200
        assert 'callerId="+12184236138"' in resp.text


class TestStatusCallback:
    def test_status_callback(self, client):
        resp = client.post("/twilio/status", data={
            "CallSid": "CA1234567890",
            "CallStatus": "completed",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["call_sid"] == "CA1234567890"
        assert body["status"] == "completed"

    def test_status_callback_empty(self, client):
        resp = client.post("/twilio/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["call_sid"] == ""
        assert body["status"] == ""


class TestGetAvailableNumbers:
    @patch("app.routers.twilio_webhooks.settings")
    def test_returns_configured_countries(self, mock_settings, client):
        mock_settings.twilio_phone_numbers = {"US": "+12184236138", "GB": "+441234567890"}

        resp = client.get("/twilio/numbers")

        assert resp.status_code == 200
        body = resp.json()
        assert "US" in body["countries"]
        assert "GB" in body["countries"]
        assert body["default"] == "US"

    @patch("app.routers.twilio_webhooks.settings")
    def test_returns_only_us_by_default(self, mock_settings, client):
        mock_settings.twilio_phone_numbers = {"US": "+12184236138"}

        resp = client.get("/twilio/numbers")

        assert resp.status_code == 200
        body = resp.json()
        assert body["countries"] == ["US"]
