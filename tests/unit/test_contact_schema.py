"""Tests for ContactOut schema resilience against real-world DB data.

The contacts table can have NULL values for boolean/integer columns and
extra columns not declared in the model (e.g. hidden, import_batch_id).
These tests ensure ContactOut never crashes on such data.
"""
from __future__ import annotations

import pytest

from app.schemas.contact import ContactOut


MINIMAL_CONTACT = {
    "id": "c-1",
    "company_name": "ACME Corp",
}

FULL_CONTACT = {
    "id": "c-1",
    "first_name": "Jane",
    "last_name": "Doe",
    "title": "CEO",
    "company_name": "ACME Corp",
    "person_linkedin_url": None,
    "website": "https://acme.com",
    "company_linkedin_url": None,
    "employees": "50",
    "city": "Berlin",
    "state": None,
    "country": "DE",
    "timezone": "Europe/Berlin",
    "email": "jane@acme.com",
    "mobile_phone": "+491234567890",
    "work_direct_phone": None,
    "corporate_phone": None,
    "score": 85,
    "company_type": "distributor",
    "rationale": "Good fit",
    "rejection_reason": None,
    "company_description": "Industrial supplies distributor.",
    "industry_tag": "Electrical Supplies",
    "exa_scrape_success": True,
    "scoring_failed": False,
    "call_occasion_count": 2,
    "times_called": 3,
    "call_outcome": "didnt_pick_up",
    "messaging_status": None,
    "sms_sent": False,
    "sms_sent_after_calls": None,
    "sms_scheduled_at": None,
    "enrichment_status": None,
    "apollo_person_id": None,
    "assigned_to": None,
    "assigned_at": None,
    "retry_at": None,
    "created_at": "2025-01-01T00:00:00",
}


class TestContactOutExtraFields:
    """Extra DB columns must not crash the model."""

    def test_extra_hidden_field_ignored(self):
        c = ContactOut(**{**FULL_CONTACT, "hidden": True})
        assert c.id == "c-1"

    def test_extra_import_batch_id_ignored(self):
        c = ContactOut(**{**FULL_CONTACT, "import_batch_id": "batch-123"})
        assert c.id == "c-1"

    def test_extra_updated_at_ignored(self):
        c = ContactOut(**{**FULL_CONTACT, "updated_at": "2025-06-01T00:00:00"})
        assert c.id == "c-1"

    def test_multiple_extra_fields_ignored(self):
        c = ContactOut(**{
            **FULL_CONTACT,
            "hidden": False,
            "import_batch_id": "b-1",
            "updated_at": "2025-06-01T00:00:00",
            "some_future_column": "whatever",
        })
        assert c.id == "c-1"


class TestContactOutNullBooleans:
    """Boolean columns may be NULL in the DB; they must coerce to False."""

    @pytest.mark.parametrize("field", ["exa_scrape_success", "scoring_failed", "sms_sent"])
    def test_null_bool_becomes_false(self, field: str):
        data = {**FULL_CONTACT, field: None}
        c = ContactOut(**data)
        assert getattr(c, field) is False

    @pytest.mark.parametrize("field", ["exa_scrape_success", "scoring_failed", "sms_sent"])
    def test_true_bool_stays_true(self, field: str):
        data = {**FULL_CONTACT, field: True}
        c = ContactOut(**data)
        assert getattr(c, field) is True


class TestContactOutNullIntegers:
    """Integer columns may be NULL in the DB; they must coerce to 0."""

    @pytest.mark.parametrize("field", ["call_occasion_count", "times_called"])
    def test_null_int_becomes_zero(self, field: str):
        data = {**FULL_CONTACT, field: None}
        c = ContactOut(**data)
        assert getattr(c, field) == 0

    @pytest.mark.parametrize("field", ["call_occasion_count", "times_called"])
    def test_positive_int_preserved(self, field: str):
        data = {**FULL_CONTACT, field: 5}
        c = ContactOut(**data)
        assert getattr(c, field) == 5


class TestContactOutMinimalData:
    """Contacts with only required fields and everything else NULL."""

    def test_minimal_contact_succeeds(self):
        c = ContactOut(**MINIMAL_CONTACT)
        assert c.id == "c-1"
        assert c.company_name == "ACME Corp"
        assert c.scoring_failed is False
        assert c.times_called == 0
        assert c.exa_scrape_success is False

    def test_all_nullable_fields_as_none(self):
        data = {
            "id": "c-2",
            "company_name": "Test",
            "first_name": None,
            "last_name": None,
            "score": None,
            "exa_scrape_success": None,
            "scoring_failed": None,
            "sms_sent": None,
            "call_occasion_count": None,
            "times_called": None,
            "call_outcome": None,
            "retry_at": None,
            "created_at": None,
        }
        c = ContactOut(**data)
        assert c.id == "c-2"
        assert c.exa_scrape_success is False
        assert c.scoring_failed is False
        assert c.sms_sent is False
        assert c.call_occasion_count == 0
        assert c.times_called == 0


class TestContactOutWithRealWorldDBRow:
    """Simulate a full row as it comes from SELECT * on the contacts table,
    including extra columns not in the schema."""

    def test_full_db_row_with_extras(self):
        db_row = {
            **FULL_CONTACT,
            "hidden": False,
            "import_batch_id": "12897d23-9aff-4e3a-be52-e10738a6d547",
            "updated_at": "2026-04-24T19:49:39.732383+00:00",
        }
        c = ContactOut(**db_row)
        assert c.id == "c-1"
        assert c.company_name == "ACME Corp"
        assert not hasattr(c, "hidden")
        assert not hasattr(c, "import_batch_id")

    def test_db_row_with_all_nulls_and_extras(self):
        db_row = {
            "id": "c-99",
            "company_name": "Bare Inc",
            "first_name": None,
            "last_name": None,
            "title": None,
            "person_linkedin_url": None,
            "website": None,
            "company_linkedin_url": None,
            "employees": None,
            "city": None,
            "state": None,
            "country": None,
            "timezone": None,
            "email": None,
            "mobile_phone": None,
            "work_direct_phone": None,
            "corporate_phone": None,
            "score": None,
            "company_type": None,
            "rationale": None,
            "rejection_reason": None,
            "company_description": None,
            "industry_tag": None,
            "exa_scrape_success": None,
            "scoring_failed": None,
            "call_occasion_count": None,
            "times_called": None,
            "call_outcome": None,
            "messaging_status": None,
            "sms_sent": None,
            "sms_sent_after_calls": None,
            "sms_scheduled_at": None,
            "enrichment_status": None,
            "apollo_person_id": None,
            "assigned_to": None,
            "assigned_at": None,
            "retry_at": None,
            "created_at": None,
            "hidden": None,
            "import_batch_id": None,
            "updated_at": None,
        }
        c = ContactOut(**db_row)
        assert c.id == "c-99"
        assert c.scoring_failed is False
        assert c.exa_scrape_success is False
        assert c.sms_sent is False
        assert c.times_called == 0
        assert c.call_occasion_count == 0
