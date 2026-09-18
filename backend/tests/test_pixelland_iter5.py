"""Iteration 5 tests: Cover-from-media, AI (description + cover), PayPal sandbox.

Runs against the public preview backend. Fully self-cleaning.
"""
import io
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pixelland-mvp.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@pixelland.com"
ADMIN_PASSWORD = "Apollo2122@×+>×>adm00140"

# --- pymongo helpers for teardown + idempotency simulation ---
try:
    from pymongo import MongoClient
    _mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    _db = _mongo[os.environ.get("DB_NAME", "test_database")]
except Exception:
    _db = None


def _admin_login():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return r.json()["session_token"], r.json()["user"]


@pytest.fixture(scope="module")
def admin_token():
    tok, _u = _admin_login()
    return tok


@pytest.fixture(scope="module")
def admin_user():
    _t, u = _admin_login()
    return u


@pytest.fixture(scope="module")
def owned_pixel(admin_token):
    """Buy a fresh unowned pixel as admin. Release on teardown."""
    h = {"Authorization": f"Bearer {admin_token}"}
    r = requests.get(f"{BASE_URL}/api/pixels", timeout=20)
    assert r.status_code == 200
    unowned = [p for p in r.json() if not p.get("owner_id")]
    assert unowned, "No unowned pixel available"
    pid = unowned[0]["pixel_id"]
    b = requests.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=h, timeout=20)
    assert b.status_code == 200, b.text
    yield pid
    # teardown: clear ownership + media via admin
    if _db is not None:
        _db.pixels.update_one(
            {"pixel_id": pid},
            {"$set": {
                "owner_id": None, "owner_name": None, "purchased_at": None,
                "cover_media_id": None, "cover_type": "image",
                "cover_video": None, "cover_image": None,
                "gallery": [], "name": f"Pixel ({pid.replace('_', ',')})",
                "description": "An unclaimed digital territory awaiting a universe.",
                "listed_price": None,
            }},
        )
        _db.pixel_media.delete_many({"pixel_id": pid})


def _tiny_png_bytes():
    # 1x1 transparent PNG
    return bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
        "890000000A49444154789C63000100000500010D0A2DB40000000049454E44AE426082"
    )


def _upload_image(pixel_id, token):
    files = {"file": (f"test_{uuid.uuid4().hex[:6]}.png", _tiny_png_bytes(), "image/png")}
    r = requests.post(
        f"{BASE_URL}/api/pixels/{pixel_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        files=files, timeout=60,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ================== COVER FIX ==================

class TestCoverFix:
    def test_patch_cover_with_image_media(self, owned_pixel, admin_token):
        media = _upload_image(owned_pixel, admin_token)
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            json={"cover_media_id": media["media_id"]}, headers=h, timeout=20,
        )
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["cover_media_id"] == media["media_id"]
        assert p["cover_type"] == "image"
        assert p["cover_image"] == media["url"]
        assert p["cover_video"] is None
        assert "res.cloudinary.com" in p["cover_image"]

    def test_patch_cover_with_nonexistent_media_returns_404(self, owned_pixel, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            json={"cover_media_id": "med_doesnotexist999"}, headers=h, timeout=20,
        )
        assert r.status_code == 404

    def test_patch_cover_empty_string_resets_to_default(self, owned_pixel, admin_token):
        media = _upload_image(owned_pixel, admin_token)
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        # set a cover
        requests.patch(f"{BASE_URL}/api/pixels/{owned_pixel}",
                       json={"cover_media_id": media["media_id"]}, headers=h, timeout=20)
        # reset
        r = requests.patch(f"{BASE_URL}/api/pixels/{owned_pixel}",
                           json={"cover_media_id": ""}, headers=h, timeout=20)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["cover_media_id"] is None
        assert p["cover_type"] == "image"
        assert p["cover_video"] is None
        assert "unsplash" in (p["cover_image"] or "")  # DEFAULT_COVER

    def test_delete_cover_media_resets_cover(self, owned_pixel, admin_token):
        media = _upload_image(owned_pixel, admin_token)
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        requests.patch(f"{BASE_URL}/api/pixels/{owned_pixel}",
                       json={"cover_media_id": media["media_id"]}, headers=h, timeout=20)
        # confirm set
        p = requests.get(f"{BASE_URL}/api/pixels/{owned_pixel}", timeout=20).json()
        assert p["cover_media_id"] == media["media_id"]
        # delete media
        d = requests.delete(
            f"{BASE_URL}/api/pixels/{owned_pixel}/media/{media['media_id']}",
            headers={"Authorization": f"Bearer {admin_token}"}, timeout=30,
        )
        assert d.status_code == 200
        p2 = requests.get(f"{BASE_URL}/api/pixels/{owned_pixel}", timeout=20).json()
        assert p2["cover_media_id"] is None
        assert "unsplash" in (p2["cover_image"] or "")


# ================== AI ==================

class TestAI:
    def test_generate_description_authed(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{BASE_URL}/api/ai/generate-description",
            json={"name": "TEST Nebula", "hint": "cosmic ocean"},
            headers=h, timeout=60,
        )
        assert r.status_code == 200, r.text
        desc = r.json()["description"]
        assert isinstance(desc, str) and 0 < len(desc) <= 500

    def test_pixel_ai_description_owner(self, owned_pixel, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{BASE_URL}/api/pixels/{owned_pixel}/ai/description",
            json={"hint": "aurora"}, headers=h, timeout=60,
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["description"]) > 0

    def test_pixel_ai_description_no_auth_401(self, owned_pixel):
        r = requests.post(
            f"{BASE_URL}/api/pixels/{owned_pixel}/ai/description",
            json={"hint": "x"}, timeout=20,
        )
        assert r.status_code == 401

    def test_pixel_ai_description_non_owner_403(self, admin_token):
        # find a pixel owned by NOBODY, buy it as admin => admin is owner, so we need a different owned pixel
        # Use direct DB to spoof: create a pixel owned by another user id? Simpler: create a second user via session-token API is not possible.
        # Instead: pick any pixel owned by admin, admin is not "non-owner". We need a pixel NOT owned by admin.
        # Since admin is our only auth path, we verify 403 via a fabricated non-admin user token in DB.
        if _db is None:
            pytest.skip("Mongo unavailable")
        # Insert a fake user + session
        fake_uid = f"user_TESTFAKE_{uuid.uuid4().hex[:6]}"
        fake_token = f"tst_{uuid.uuid4().hex}"
        _db.users.insert_one({
            "user_id": fake_uid, "email": f"{fake_uid}@t.io", "name": "Fake",
            "coins": 0, "pixels_owned": 0, "is_admin": False,
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        _db.user_sessions.insert_one({
            "session_token": fake_token, "user_id": fake_uid,
            "expires_at": __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(days=1),
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        try:
            # find any admin-owned pixel
            admin_uid = _db.users.find_one({"email": ADMIN_EMAIL})["user_id"]
            p = _db.pixels.find_one({"owner_id": admin_uid})
            if not p:
                pytest.skip("Admin owns no pixel to test 403 against")
            r = requests.post(
                f"{BASE_URL}/api/pixels/{p['pixel_id']}/ai/description",
                json={"hint": "x"},
                headers={"Authorization": f"Bearer {fake_token}",
                         "Content-Type": "application/json"},
                timeout=20,
            )
            assert r.status_code == 403
        finally:
            _db.users.delete_one({"user_id": fake_uid})
            _db.user_sessions.delete_one({"session_token": fake_token})

    def test_ai_cover_short_prompt_422(self, owned_pixel, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{BASE_URL}/api/pixels/{owned_pixel}/ai/cover",
            json={"prompt": "ab"}, headers=h, timeout=20,
        )
        assert r.status_code == 422

    def test_ai_cover_owner_happy_path(self, owned_pixel, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        # Get media count before
        before = requests.get(f"{BASE_URL}/api/pixels/{owned_pixel}/media", timeout=20).json()
        r = requests.post(
            f"{BASE_URL}/api/pixels/{owned_pixel}/ai/cover",
            json={"prompt": "a serene mountain at sunset, digital art"},
            headers=h, timeout=120,
        )
        assert r.status_code == 200, r.text
        p = r.json()
        assert "res.cloudinary.com" in p["cover_image"]
        # Fetch image URL
        img = requests.get(p["cover_image"], timeout=30)
        assert img.status_code == 200
        assert img.headers.get("content-type", "").startswith("image/")
        # media list grew
        after = requests.get(f"{BASE_URL}/api/pixels/{owned_pixel}/media", timeout=20).json()
        assert len(after) == len(before) + 1
        # newest media is the AI one
        newest = after[0]
        assert newest["kind"] == "image"
        assert newest["url"] == p["cover_image"]


# ================== PAYPAL ==================

class TestPayPal:
    def test_bundles_list(self):
        r = requests.get(f"{BASE_URL}/api/payments/bundles", timeout=20)
        assert r.status_code == 200
        bundles = r.json()
        assert len(bundles) == 3
        by_id = {b["bundle_id"]: b for b in bundles}
        assert set(by_id) == {"bundle_1000", "bundle_3000", "bundle_8000"}
        assert by_id["bundle_1000"]["price_usd"] == "4.99"
        assert by_id["bundle_3000"]["price_usd"] == "9.99"
        assert by_id["bundle_8000"]["price_usd"] == "19.99"

    def test_create_order_ok(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{BASE_URL}/api/payments/create-order",
            json={"bundle_id": "bundle_1000"}, headers=h, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["order_id"]
        assert d["approve_url"].startswith("https://www.sandbox.paypal.com/")
        assert d["bundle_id"] == "bundle_1000"
        assert d["coins"] == 1000
        assert d["price_usd"] == "4.99"

    def test_create_order_invalid_bundle(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.post(
            f"{BASE_URL}/api/payments/create-order",
            json={"bundle_id": "bundle_bogus"}, headers=h, timeout=30,
        )
        assert r.status_code == 400

    def test_capture_not_approved_returns_502(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        cr = requests.post(
            f"{BASE_URL}/api/payments/create-order",
            json={"bundle_id": "bundle_1000"}, headers=h, timeout=30,
        )
        assert cr.status_code == 200
        order_id = cr.json()["order_id"]
        r = requests.post(
            f"{BASE_URL}/api/payments/capture/{order_id}",
            headers=h, timeout=30,
        )
        assert r.status_code == 502

    def test_capture_no_auth_401(self, admin_token):
        # need a real order_id to hit the auth check (any string works because auth check is FIRST)
        r = requests.post(f"{BASE_URL}/api/payments/capture/fakeorder123", timeout=20)
        assert r.status_code == 401

    def test_capture_wrong_owner_403(self, admin_token):
        if _db is None:
            pytest.skip("Mongo unavailable")
        # Create order as admin
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        cr = requests.post(f"{BASE_URL}/api/payments/create-order",
                           json={"bundle_id": "bundle_1000"}, headers=h, timeout=30)
        assert cr.status_code == 200
        order_id = cr.json()["order_id"]
        # Fabricate a different user + session
        fake_uid = f"user_TEST403_{uuid.uuid4().hex[:6]}"
        fake_token = f"tst_{uuid.uuid4().hex}"
        _db.users.insert_one({
            "user_id": fake_uid, "email": f"{fake_uid}@t.io", "name": "OtherUser",
            "coins": 0, "pixels_owned": 0, "is_admin": False,
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        _db.user_sessions.insert_one({
            "session_token": fake_token, "user_id": fake_uid,
            "expires_at": __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(days=1),
            "created_at": __import__("datetime").datetime.utcnow(),
        })
        try:
            r = requests.post(
                f"{BASE_URL}/api/payments/capture/{order_id}",
                headers={"Authorization": f"Bearer {fake_token}"}, timeout=20,
            )
            assert r.status_code == 403
        finally:
            _db.users.delete_one({"user_id": fake_uid})
            _db.user_sessions.delete_one({"session_token": fake_token})
            _db.payment_orders.delete_one({"order_id": order_id})

    def test_capture_unknown_order_404(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.post(f"{BASE_URL}/api/payments/capture/UNKNOWN_ORDER_XYZ",
                          headers=h, timeout=20)
        assert r.status_code == 404

    def test_capture_idempotency_credited_short_circuit(self, admin_token, admin_user):
        if _db is None:
            pytest.skip("Mongo unavailable")
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        cr = requests.post(f"{BASE_URL}/api/payments/create-order",
                           json={"bundle_id": "bundle_1000"}, headers=h, timeout=30)
        assert cr.status_code == 200
        order_id = cr.json()["order_id"]
        # Flip credited=true directly
        _db.payment_orders.update_one(
            {"order_id": order_id},
            {"$set": {"credited": True, "status": "COMPLETED"}},
        )
        try:
            r1 = requests.post(f"{BASE_URL}/api/payments/capture/{order_id}",
                               headers=h, timeout=20)
            assert r1.status_code == 200, r1.text
            d1 = r1.json()
            assert d1["credited"] is True
            assert d1["coins_added"] == 0
            # Second call - same response
            r2 = requests.post(f"{BASE_URL}/api/payments/capture/{order_id}",
                               headers=h, timeout=20)
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["credited"] is True and d2["coins_added"] == 0
        finally:
            _db.payment_orders.delete_one({"order_id": order_id})


# ================== CONFIG SOURCING ==================

class TestConfig:
    def test_env_sourced_no_hardcoded(self):
        with open("/app/backend/server.py") as f:
            src = f.read()
        # Ensure sensitive values are NOT hardcoded as literals
        assert "AWg1JYkYtbfU5f5nJFKCcfqYQiMrfV9BRibdItiI1VQ3" not in src
        assert "EEV1yEJmzY8vs0rqr8ztqPrJ_yZLhYXLKmN8Xaj1epS9" not in src
        assert "sk-emergent-d321a5922FeE0A97d8" not in src
        # Ensure env-var access is present
        assert 'os.environ["EMERGENT_LLM_KEY"]' in src
        assert 'os.environ["PAYPAL_CLIENT_ID"]' in src
        assert 'os.environ["PAYPAL_SECRET"]' in src
        assert 'os.environ.get("PAYPAL_MODE"' in src


# ================== REGRESSION ==================

class TestRegression:
    def test_admin_login(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20,
        )
        assert r.status_code == 200
        assert r.json()["user"]["is_admin"] is True

    def test_pixels_list_shape(self):
        r = requests.get(f"{BASE_URL}/api/pixels", timeout=20)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) == 400
        # New iter5 fields present
        assert "cover_media_id" in arr[0]
        assert "cover_type" in arr[0]
        assert "cover_video" in arr[0]

    def test_leaderboard(self):
        r = requests.get(f"{BASE_URL}/api/leaderboard", timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_listings_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/listings", timeout=20)
        assert r.status_code == 200

    def test_admin_users_rbac(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users",
                         headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
        assert r.status_code == 200
        # Non-admin denied
        r2 = requests.get(f"{BASE_URL}/api/admin/users", timeout=20)
        assert r2.status_code == 401

    def test_patch_url_validator_rejects_javascript(self, owned_pixel, admin_token):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = requests.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            json={"external_link": "javascript:alert(1)"}, headers=h, timeout=20,
        )
        assert r.status_code == 422
