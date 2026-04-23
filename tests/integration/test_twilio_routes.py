from __future__ import annotations


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
