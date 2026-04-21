from __future__ import annotations


class TestGetMe:
    def test_get_me(self, client, mock_current_user):
        resp = client.get("/auth/me")
        assert resp.status_code == 200

        body = resp.json()
        assert body["id"] == "test-user-id"
        assert body["email"] == "test@hexaagents.com"
        assert body["full_name"] == "Test User"


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
