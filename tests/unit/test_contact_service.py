from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_contact_repo():
    with patch("app.services.contact_service.contact_repo") as mock_repo:
        yield mock_repo


class TestListContacts:
    def test_list_contacts_delegates(self, _mock_contact_repo):
        from app.services.contact_service import list_contacts

        _mock_contact_repo.list_contacts.return_value = ([{"id": "c1"}], 1)
        db = MagicMock()

        result = list_contacts(
            db, sort_by="score", sort_order="desc",
            outcome_filter="answered", page=2, per_page=25,
        )

        _mock_contact_repo.list_contacts.assert_called_once_with(
            db,
            sort_by="score",
            sort_order="desc",
            outcome_filter="answered",
            page=2,
            per_page=25,
        )
        assert result == ([{"id": "c1"}], 1)


class TestGetContact:
    def test_get_contact_found(self, _mock_contact_repo):
        from app.services.contact_service import get_contact

        _mock_contact_repo.get_contact.return_value = {"id": "c1", "company_name": "ACME"}
        db = MagicMock()

        result = get_contact(db, "c1")

        assert result == {"id": "c1", "company_name": "ACME"}

    def test_get_contact_not_found(self, _mock_contact_repo):
        from app.services.contact_service import get_contact

        _mock_contact_repo.get_contact.return_value = None
        db = MagicMock()

        result = get_contact(db, "nonexistent")

        assert result is None


class TestDeleteContact:
    def test_delete_contact_success(self, _mock_contact_repo):
        from app.services.contact_service import delete_contact

        _mock_contact_repo.delete_contact.return_value = True
        db = MagicMock()

        assert delete_contact(db, "c1") is True

    def test_delete_contact_not_found(self, _mock_contact_repo):
        from app.services.contact_service import delete_contact

        _mock_contact_repo.delete_contact.return_value = False
        db = MagicMock()

        assert delete_contact(db, "nonexistent") is False
