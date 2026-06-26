import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pixelland-mvp.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@pixelland.com"
ADMIN_PASSWORD = "Apollo2122@×+>×>adm00140"


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_session(api_client):
    """Login as admin once, reused across tests."""
    r = api_client.post(
        f"{BASE_URL}/api/auth/admin-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"admin-login failed: {r.status_code} {r.text}"
    data = r.json()
    return data  # has session_token + user


@pytest.fixture(scope="session")
def admin_token(admin_session):
    return admin_session["session_token"]


@pytest.fixture(scope="session")
def admin_user(admin_session):
    return admin_session["user"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
