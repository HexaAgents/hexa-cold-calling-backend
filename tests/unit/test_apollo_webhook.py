"""Unit tests for the Apollo phone-number webhook classifier.

The classifier previously only recognized type_cd containing "mobile" or
"work", so Apollo's "corporate", "hq", "home", "other" values fell through to
a first-empty-slot fallback and could land in the wrong column (e.g. a
corporate number ending up in mobile_phone). These tests pin down the fixed
behaviour.
"""

from app.routers.apollo_webhooks import _classify_phones


class TestClassifyPhones:
    def test_mobile_and_corporate_go_to_correct_columns(self):
        phones, _ = _classify_phones(
            [
                {"sanitized_number": "+14149491154", "type_cd": "mobile"},
                {"sanitized_number": "+12625440254", "type_cd": "corporate"},
            ]
        )
        assert phones == {
            "mobile_phone": "+14149491154",
            "corporate_phone": "+12625440254",
        }

    def test_work_direct_maps_to_work_direct_phone(self):
        phones, _ = _classify_phones(
            [{"sanitized_number": "+15551234567", "type_cd": "work_direct"}]
        )
        assert phones == {"work_direct_phone": "+15551234567"}

    def test_hq_is_treated_as_corporate(self):
        phones, _ = _classify_phones(
            [{"sanitized_number": "+15550000000", "type_cd": "hq"}]
        )
        assert phones == {"corporate_phone": "+15550000000"}

    def test_home_is_treated_as_mobile(self):
        phones, _ = _classify_phones(
            [{"sanitized_number": "+15559998888", "type_cd": "home"}]
        )
        assert phones == {"mobile_phone": "+15559998888"}

    def test_other_and_unknown_fall_through_to_first_free_slot(self):
        # 'other' has no explicit mapping; should land in first free slot
        # (mobile_phone), not conflict with an existing classified mobile.
        phones, _ = _classify_phones(
            [
                {"sanitized_number": "+15550000001", "type_cd": "other"},
                {"sanitized_number": "+15550000002", "type_cd": "mobile"},
            ]
        )
        assert phones == {
            "mobile_phone": "+15550000002",
            "work_direct_phone": "+15550000001",
        }

    def test_duplicate_type_does_not_overwrite(self):
        phones, _ = _classify_phones(
            [
                {"sanitized_number": "+15551111111", "type_cd": "mobile"},
                {"sanitized_number": "+15552222222", "type_cd": "mobile"},
            ]
        )
        # First mobile wins the mobile slot; second falls through to work.
        assert phones == {
            "mobile_phone": "+15551111111",
            "work_direct_phone": "+15552222222",
        }

    def test_empty_sanitized_number_is_skipped(self):
        phones, _ = _classify_phones(
            [
                {"sanitized_number": "", "type_cd": "mobile"},
                {"sanitized_number": "+15553334444", "type_cd": "mobile"},
            ]
        )
        assert phones == {"mobile_phone": "+15553334444"}

    def test_raw_number_used_when_sanitized_missing(self):
        phones, _ = _classify_phones(
            [{"raw_number": "(555) 444-3333", "type_cd": "mobile"}]
        )
        assert phones == {"mobile_phone": "(555) 444-3333"}

    def test_three_phones_fill_all_slots_in_priority(self):
        phones, _ = _classify_phones(
            [
                {"sanitized_number": "+15550001111", "type_cd": "mobile"},
                {"sanitized_number": "+15550002222", "type_cd": "work_direct"},
                {"sanitized_number": "+15550003333", "type_cd": "corporate"},
            ]
        )
        assert phones == {
            "mobile_phone": "+15550001111",
            "work_direct_phone": "+15550002222",
            "corporate_phone": "+15550003333",
        }

    def test_case_insensitive_type_cd(self):
        phones, _ = _classify_phones(
            [{"sanitized_number": "+15557776666", "type_cd": "MOBILE"}]
        )
        assert phones == {"mobile_phone": "+15557776666"}

    def test_empty_input_returns_empty(self):
        phones, type_cds = _classify_phones([])
        assert phones == {}
        assert type_cds == []
