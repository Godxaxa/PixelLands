"""PixelLand backend API tests.

Covers:
  - Auth: admin-login, /auth/me, /auth/logout, missing/invalid bearer
  - Pixels: list (400), get single, buy flow, already-owned 409, owner update
  - Profile: /profile/pixels
  - Admin: list/update users, update pixel (price/name/owner reassignment & clearing)
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pixelland-mvp.preview.emergentagent.com").rstrip("/")
PIXEL_PRICES = {5, 10, 20, 30, 40, 50, 100}


# ----- Auth -----

class TestAuth:
    def test_admin_login_success(self, admin_session):
        assert "session_token" in admin_session and admin_session["session_token"]
        u = admin_session["user"]
        assert u["email"] == "admin@pixelland.com"
        assert u["is_admin"] is True
        assert u["coins"] >= 99000  # seeded with 99999, may be slightly less after prior runs

    def test_admin_login_invalid_password(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": "admin@pixelland.com", "password": "wrong-password"},
            timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_admin_login_unknown_email(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": "nobody@pixelland.com", "password": "x"},
            timeout=15,
        )
        assert r.status_code == 401, r.text

    def test_auth_me_with_bearer(self, api_client, auth_headers):
        r = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == "admin@pixelland.com"
        assert body["is_admin"] is True
        for k in ("user_id", "name", "coins", "pixels_owned"):
            assert k in body

    def test_auth_me_without_bearer(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert r.status_code == 401

    def test_auth_me_invalid_bearer(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
            timeout=15,
        )
        assert r.status_code == 401

    def test_logout_invalidates_session(self, api_client):
        # create a new short-lived session so other tests aren't disturbed
        r = api_client.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": "admin@pixelland.com", "password": "Apollo2122@×+>×>adm00140"},
            timeout=15,
        )
        assert r.status_code == 200
        tok = r.json()["session_token"]
        h = {"Authorization": f"Bearer {tok}"}
        # confirm it works
        assert api_client.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15).status_code == 200
        # logout
        lo = api_client.post(f"{BASE_URL}/api/auth/logout", headers=h, timeout=15)
        assert lo.status_code == 200 and lo.json().get("ok") is True
        # now invalid
        assert api_client.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15).status_code == 401


# ----- Pixels (public reads) -----

class TestPixels:
    def test_list_pixels_count_and_shape(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/pixels", timeout=30)
        assert r.status_code == 200
        pixels = r.json()
        assert isinstance(pixels, list)
        assert len(pixels) == 400, f"expected 400 pixels, got {len(pixels)}"
        # all coords cover 0..19 in both axes
        xs = {p["x"] for p in pixels}
        ys = {p["y"] for p in pixels}
        assert xs == set(range(20))
        assert ys == set(range(20))
        # prices match allowed set
        assert {p["price"] for p in pixels}.issubset(PIXEL_PRICES)
        # required fields present
        for p in pixels[:3]:
            for k in ("pixel_id", "x", "y", "price", "name", "cover_image"):
                assert k in p

    def test_get_single_pixel(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/pixels/0_0", timeout=15)
        assert r.status_code == 200
        p = r.json()
        assert p["pixel_id"] == "0_0"
        assert p["x"] == 0 and p["y"] == 0
        assert p["price"] in PIXEL_PRICES

    def test_get_unknown_pixel_404(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/pixels/999_999", timeout=15)
        assert r.status_code == 404


# ----- Buy / update flow as admin -----

def _find_unowned_pixel(api_client):
    r = api_client.get(f"{BASE_URL}/api/pixels", timeout=30)
    assert r.status_code == 200
    for p in r.json():
        if not p.get("owner_id"):
            return p
    raise AssertionError("No unowned pixels left to buy in test")


class TestBuyAndUpdate:
    def test_buy_flow_and_balance(self, api_client, auth_headers, admin_user):
        # snapshot admin coins/pixels_owned
        me1 = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
        coins_before = me1["coins"]
        owned_before = me1["pixels_owned"]

        pixel = _find_unowned_pixel(api_client)
        pid = pixel["pixel_id"]
        price = pixel["price"]

        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        bought = r.json()
        assert bought["pixel_id"] == pid
        assert bought["owner_id"] == admin_user["user_id"]
        assert bought["purchased_at"]

        # GET to verify persistence
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["owner_id"] == admin_user["user_id"]

        # /auth/me reflects updated balance & count
        me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
        assert me2["coins"] == coins_before - price, (me2, coins_before, price)
        assert me2["pixels_owned"] == owned_before + 1

        # stash for next tests
        pytest._bought_pid = pid  # type: ignore[attr-defined]

    def test_buy_already_owned_returns_409(self, api_client, auth_headers):
        pid = getattr(pytest, "_bought_pid", None)
        if not pid:
            pytest.skip("no previously-bought pixel id available")
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=auth_headers, timeout=15)
        assert r.status_code == 409, r.text

    def test_owner_patch_pixel(self, api_client, auth_headers):
        pid = getattr(pytest, "_bought_pid", None)
        if not pid:
            pytest.skip("no previously-bought pixel id available")
        payload = {
            "name": "TEST_OwnedPixel",
            "description": "TEST owner-edited description",
            "cover_image": "https://example.com/cover.png",
        }
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{pid}", headers=auth_headers, json=payload, timeout=15
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == payload["name"]
        assert body["description"] == payload["description"]
        assert body["cover_image"] == payload["cover_image"]
        # GET reverify
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["name"] == payload["name"]

    def test_profile_pixels_lists_admin_owned(self, api_client, auth_headers, admin_user):
        r = api_client.get(f"{BASE_URL}/api/profile/pixels", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        pixels = r.json()
        assert isinstance(pixels, list)
        assert len(pixels) >= 1
        for p in pixels:
            assert p["owner_id"] == admin_user["user_id"]


# ----- Admin endpoints -----

class TestAdmin:
    def test_admin_users_requires_admin(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/admin/users", timeout=15)
        assert r.status_code == 401

    def test_admin_users_list(self, api_client, auth_headers):
        r = api_client.get(f"{BASE_URL}/api/admin/users", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        users = r.json()
        emails = {u["email"] for u in users}
        assert "admin@pixelland.com" in emails
        # password_hash must not leak
        for u in users:
            assert "password_hash" not in u

    def test_admin_update_user_coins_and_name(self, api_client, auth_headers, admin_user):
        new_name = "Admin_TEST"
        new_coins = 12345
        r = api_client.patch(
            f"{BASE_URL}/api/admin/users/{admin_user['user_id']}",
            headers=auth_headers,
            json={"name": new_name, "coins": new_coins},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == new_name
        assert body["coins"] == new_coins
        # verify via /auth/me
        me = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
        assert me["coins"] == new_coins
        # restore reasonable coins to keep admin able to buy in subsequent runs
        api_client.patch(
            f"{BASE_URL}/api/admin/users/{admin_user['user_id']}",
            headers=auth_headers,
            json={"name": "Admin", "coins": 99999},
            timeout=15,
        )

    def test_admin_patch_pixel_price_and_clear_owner(self, api_client, auth_headers, admin_user):
        # use the pixel admin bought earlier; clear its owner
        pid = getattr(pytest, "_bought_pid", None)
        if not pid:
            pytest.skip("no bought pixel available")

        # change price
        r = api_client.patch(
            f"{BASE_URL}/api/admin/pixels/{pid}",
            headers=auth_headers,
            json={"price": 77, "name": "TEST_AdminEdited", "description": "TEST admin edit"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["price"] == 77
        assert b["name"] == "TEST_AdminEdited"

        # owned count before clearing
        owned_before = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15
        ).json()["pixels_owned"]

        # clear owner via empty string
        r2 = api_client.patch(
            f"{BASE_URL}/api/admin/pixels/{pid}",
            headers=auth_headers,
            json={"owner_id": ""},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        cleared = r2.json()
        assert cleared["owner_id"] in (None, "")
        assert cleared["owner_name"] in (None, "")

        # admin's pixels_owned decremented
        owned_after = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15
        ).json()["pixels_owned"]
        assert owned_after == owned_before - 1

    def test_admin_assign_owner_then_clear(self, api_client, auth_headers, admin_user):
        # pick a fresh unowned pixel and assign to admin via admin endpoint
        pixel = _find_unowned_pixel(api_client)
        pid = pixel["pixel_id"]
        r = api_client.patch(
            f"{BASE_URL}/api/admin/pixels/{pid}",
            headers=auth_headers,
            json={"owner_id": admin_user["user_id"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["owner_id"] == admin_user["user_id"]
        assert body["purchased_at"]

        # cleanup: release ownership
        api_client.patch(
            f"{BASE_URL}/api/admin/pixels/{pid}",
            headers=auth_headers,
            json={"owner_id": ""},
            timeout=15,
        )

    def test_admin_pixel_404_for_unknown(self, api_client, auth_headers):
        r = api_client.patch(
            f"{BASE_URL}/api/admin/pixels/999_999",
            headers=auth_headers,
            json={"price": 5},
            timeout=15,
        )
        assert r.status_code == 404

    def test_admin_user_404_for_unknown(self, api_client, auth_headers):
        r = api_client.patch(
            f"{BASE_URL}/api/admin/users/no_such_user",
            headers=auth_headers,
            json={"coins": 1},
            timeout=15,
        )
        assert r.status_code == 404
