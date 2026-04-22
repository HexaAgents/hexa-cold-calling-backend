from __future__ import annotations

from unittest.mock import MagicMock


SAMPLE_SETTINGS = {
    "id": "settings-1",
    "sms_call_threshold": 3,
    "sms_template": "Hi <first_name>, this is Hexa Agents.",
    "retry_days": 3,
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestGetSettings:
    def test_get_settings(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .limit.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_SETTINGS)

        resp = client.get("/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "settings-1"
        assert body["sms_call_threshold"] == 3
        assert "<first_name>" in body["sms_template"]


class TestUpdateSettings:
    def test_update_settings(self, client, mock_supabase):
        updated = {**SAMPLE_SETTINGS, "sms_call_threshold": 5}

        mock_supabase.table.return_value \
            .select.return_value \
            .limit.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_SETTINGS)

        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([updated])

        resp = client.put("/settings", json={"sms_call_threshold": 5})
        assert resp.status_code == 200
        assert resp.json()["sms_call_threshold"] == 5

    def test_update_retry_days(self, client, mock_supabase):
        updated = {**SAMPLE_SETTINGS, "retry_days": 7}

        mock_supabase.table.return_value \
            .select.return_value \
            .limit.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_SETTINGS)

        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _make_execute_result([updated])

        resp = client.put("/settings", json={"retry_days": 7})
        assert resp.status_code == 200
        assert resp.json()["retry_days"] == 7

    def test_update_settings_empty(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .limit.return_value \
            .single.return_value \
            .execute.return_value = _make_execute_result(SAMPLE_SETTINGS)

        resp = client.put("/settings", json={})
        assert resp.status_code == 200
        assert resp.json()["sms_call_threshold"] == 3
