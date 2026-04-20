from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_supabase():
    return MagicMock()


@pytest.fixture
def mock_current_user():
    return {
        "id": "test-user-id",
        "email": "test@hexaagents.com",
        "full_name": "Test User",
    }


@pytest.fixture
def client(mock_supabase, mock_current_user):
    from app.main import app
    from app.dependencies import get_supabase, get_current_user

    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    app.dependency_overrides[get_current_user] = lambda: mock_current_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
