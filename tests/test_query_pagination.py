"""
Unit and integration tests for query pagination bounds and unbounded query prevention (DB-02, DB-03, MED-03).
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from backend.app.main import app
from backend.app.dependencies import require_admin, get_current_user, get_db
from backend.app.models.user import User, RoleEnum


@pytest.fixture
def mock_admin_user():
    user = MagicMock(spec=User)
    user.id = "00000000-0000-0000-0000-000000000001"
    user.name = "Admin Tester"
    user.email = "admin@test.com"
    user.role = RoleEnum.admin
    user.is_active = True
    return user


@pytest.fixture
def client_with_admin(mock_admin_user):
    mock_db = MagicMock()
    app.dependency_overrides[require_admin] = lambda: mock_admin_user
    app.dependency_overrides[get_current_user] = lambda: mock_admin_user
    app.dependency_overrides[get_db] = lambda: mock_db
    client = TestClient(app)
    yield client, mock_db
    app.dependency_overrides.clear()


def test_all_sessions_bounded_query(client_with_admin):
    """Verify /api/v1/sessions/all rejects limits exceeding max 500 to prevent denial-of-service."""
    client, mock_db = client_with_admin
    
    # 1. Invalid limit > 500 should return 422
    resp = client.get("/api/v1/sessions/all?limit=501")
    assert resp.status_code == 422

    # 2. Invalid limit < 1 should return 422
    resp = client.get("/api/v1/sessions/all?limit=0")
    assert resp.status_code == 422

    # 3. Valid default limit returns 200
    mock_query = mock_db.query.return_value
    mock_query.options.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value.all.return_value = []
    
    resp = client.get("/api/v1/sessions/all")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_expenses_pagination_bounds(client_with_admin):
    """Verify /api/v1/finance/expenses enforces page_size <= 100."""
    client, _ = client_with_admin

    # Page size > 100 must be rejected with 422
    resp = client.get("/api/v1/finance/expenses?page_size=101")
    assert resp.status_code == 422

    # Negative page must be rejected with 422
    resp = client.get("/api/v1/finance/expenses?page=0")
    assert resp.status_code == 422


def test_login_history_pagination_bounds(client_with_admin):
    """Verify /api/v1/login-history enforces page_size <= 100."""
    client, _ = client_with_admin

    # Page size > 100 must be rejected with 422
    resp = client.get("/api/v1/login-history?page_size=101")
    assert resp.status_code == 422

    # Page < 1 must be rejected with 422
    resp = client.get("/api/v1/login-history?page=-1")
    assert resp.status_code == 422
