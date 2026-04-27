from __future__ import annotations

import json

from app.scoring.openai_scorer import _parse_response


def _valid_json(**overrides):
    data = {
        "score": 75,
        "company_type": "distributor",
        "rationale": "Good fit for cold calling",
        "rejection_reason": None,
        "company_description": "Distributes industrial pumps and valves to the oil and gas industry. Serves mid-market clients across North America.",
    }
    data.update(overrides)
    return json.dumps(data)


class TestParseResponse:
    def test_parse_valid_json(self):
        result = _parse_response(_valid_json())

        assert result["score"] == 75
        assert result["company_type"] == "distributor"
        assert result["rationale"] == "Good fit for cold calling"
        assert result["rejection_reason"] is None

    def test_parse_invalid_json(self):
        result = _parse_response("this is not json at all")

        assert result["score"] == 0
        assert result["company_type"] == "rejected"
        assert result["rationale"] == "Scoring parse error"

    def test_parse_score_clamped_to_100(self):
        result = _parse_response(_valid_json(score=150))
        assert result["score"] == 100

    def test_parse_score_clamped_to_0(self):
        result = _parse_response(_valid_json(score=-10))
        assert result["score"] == 0

    def test_parse_score_as_string(self):
        result = _parse_response(_valid_json(score="85"))
        assert result["score"] == 85
        assert isinstance(result["score"], int)

    def test_parse_score_as_float(self):
        result = _parse_response(_valid_json(score=72.5))
        assert result["score"] == 72
        assert isinstance(result["score"], int)

    def test_parse_unknown_company_type(self):
        result = _parse_response(_valid_json(company_type="unknown"))
        assert result["company_type"] == "rejected"

    def test_parse_unknown_rejection_reason(self):
        result = _parse_response(_valid_json(rejection_reason="bad_value"))
        assert result["rejection_reason"] == "unclear"

    def test_parse_distributor_facing_vendor_reason(self):
        result = _parse_response(
            _valid_json(rejection_reason="distributor_facing_vendor", company_type="rejected", score=15)
        )
        assert result["rejection_reason"] == "distributor_facing_vendor"
        assert result["company_type"] == "rejected"

    def test_parse_rejection_reason_forces_rejected_even_if_model_said_distributor(self):
        result = _parse_response(
            _valid_json(company_type="distributor", rejection_reason="distributor_facing_vendor", score=90)
        )
        assert result["company_type"] == "rejected"
        assert result["rejection_reason"] == "distributor_facing_vendor"

    def test_parse_valid_rejection_none(self):
        result = _parse_response(_valid_json(rejection_reason=None))
        assert "rejection_reason" in result
        assert result["rejection_reason"] is None

    def test_parse_company_description(self):
        result = _parse_response(_valid_json())
        assert result["company_description"] == "Distributes industrial pumps and valves to the oil and gas industry. Serves mid-market clients across North America."

    def test_parse_missing_company_description(self):
        raw = json.dumps({
            "score": 75,
            "company_type": "distributor",
            "rationale": "Good fit",
            "rejection_reason": None,
        })
        result = _parse_response(raw)
        assert result["company_description"] is None

    def test_parse_empty_company_description(self):
        result = _parse_response(_valid_json(company_description=""))
        assert result["company_description"] is None
