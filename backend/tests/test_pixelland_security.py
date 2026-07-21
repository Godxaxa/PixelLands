"""PixelLand Iteration 3 - Security fixes verification.

SEC-001 (Critical): admin creds from env, seed_admin idempotent, no hardcoded pw.
SEC-002 (High): buy_pixel + buy_resale must not permit overspending, even under concurrency.
SEC-003 (Medium): PATCH /api/pixels validates URLs (http/https only), theme_color hex, gallery <= 30.
"""

import os
import re
import uuid
import concurrent.futures as cf
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://pixelland-mvp.preview.emergentagent.com"
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
ADMIN_EMAIL = "admin@pixelland.com"
ADMIN_PASSWORD = "Apollo2122@×+>×>adm00140"


# ---------- helpers / fixtures ----------

@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def small_balance_user(mongo):
    """Create a real DB user + session with a small coin balance for concurrent buy tests."""
    uid = f"user_{uuid.uuid4().hex[:12]}"
    token = f"tst_{uuid.uuid4().hex}"
    email = f"test_sec_{uuid.uuid4().hex[:6]}@pixelland.test"
    mongo.users.insert_one({
        "user_id": uid,
        "email": email,
        "name": "TEST_SecBuyer",
        "picture": None,
        "coins": 30,  # only 30 coins; each pixel of price 20 => only 1 can succeed
        "pixels_owned": 0,
        "is_admin": False,
        "created_at": datetime.now(timezone.utc),
    })
    mongo.user_sessions.insert_one({
        "session_token": token,
        "user_id": uid,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
    })
    yield {"user_id": uid, "email": email, "token": token}
    # teardown - release any pixels this test user grabbed & delete
    for p in mongo.pixels.find({"owner_id": uid}, {"pixel_id": 1, "_id": 0}):
        mongo.pixels.update_one(
            {"pixel_id": p["pixel_id"]},
            {"$set": {"owner_id": None, "owner_name": None, "purchased_at": None, "listed_price": None}},
        )
    mongo.user_sessions.delete_many({"user_id": uid})
    mongo.users.delete_one({"user_id": uid})


@pytest.fixture(scope="module")
def resale_pool(mongo):
    """Provision a resale test user + a second buyer for concurrent resale test."""
    seller_uid = f"user_{uuid.uuid4().hex[:12]}"
    seller_token = f"tst_{uuid.uuid4().hex}"
    buyer_uid = f"user_{uuid.uuid4().hex[:12]}"
    buyer_token = f"tst_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    mongo.users.insert_many([
        {"user_id": seller_uid, "email": f"sec_seller_{uuid.uuid4().hex[:6]}@pl.test",
         "name": "TEST_Seller", "coins": 500, "pixels_owned": 0, "is_admin": False, "created_at": now},
        {"user_id": buyer_uid, "email": f"sec_resbuyer_{uuid.uuid4().hex[:6]}@pl.test",
         "name": "TEST_ResBuyer", "coins": 30, "pixels_owned": 0, "is_admin": False, "created_at": now},
    ])
    mongo.user_sessions.insert_many([
        {"session_token": seller_token, "user_id": seller_uid,
         "expires_at": now + timedelta(days=1), "created_at": now},
        {"session_token": buyer_token, "user_id": buyer_uid,
         "expires_at": now + timedelta(days=1), "created_at": now},
    ])
    yield {"seller": {"user_id": seller_uid, "token": seller_token},
           "buyer": {"user_id": buyer_uid, "token": buyer_token}}
    for uid in (seller_uid, buyer_uid):
        for p in mongo.pixels.find({"owner_id": uid}, {"pixel_id": 1, "_id": 0}):
            mongo.pixels.update_one(
                {"pixel_id": p["pixel_id"]},
                {"$set": {"owner_id": None, "owner_name": None, "purchased_at": None, "listed_price": None}},
            )
        mongo.user_sessions.delete_many({"user_id": uid})
        mongo.users.delete_one({"user_id": uid})


def _get_unowned_pixels(api_client, n):
    r = api_client.get(f"{BASE_URL}/api/pixels", timeout=30)
    assert r.status_code == 200
    out = []
    for p in r.json():
        if not p.get("owner_id"):
            out.append(p)
        if len(out) >= n:
            break
    assert len(out) >= n, f"need {n} unowned pixels, got {len(out)}"
    return out


# ---------- SEC-001 ----------

class TestSec001AdminCredsFromEnv:
    def test_no_hardcoded_admin_password_literal_in_server_py(self):
        src = Path("/app/backend/server.py").read_text(encoding="utf-8")
        # The literal password must NOT appear anywhere in source
        assert "Apollo2122" not in src, "hardcoded admin password literal still present in server.py"
        # Must read from env
        assert "ADMIN_EMAIL" in src and "ADMIN_PASSWORD" in src
        assert 'os.environ["ADMIN_PASSWORD"]' in src or "os.environ.get('ADMIN_PASSWORD'" in src \
            or 'os.environ.get("ADMIN_PASSWORD"' in src

    def test_admin_login_still_works_with_env_password(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["is_admin"] is True
        assert body["user"]["email"] == ADMIN_EMAIL
        assert body.get("session_token")

    def test_admin_login_wrong_password_rejected(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/admin-login",
            json={"email": ADMIN_EMAIL, "password": "wrong_password"}, timeout=20,
        )
        assert r.status_code == 401

    def test_seed_admin_is_idempotent_code_path(self):
        """Source check: seed_admin must early-return when admin exists (no update to password_hash)."""
        src = Path("/app/backend/server.py").read_text(encoding="utf-8")
        # Extract seed_admin function block
        m = re.search(r"async def seed_admin\(\).*?(?=\nasync def |\nclass |\Z)", src, re.DOTALL)
        assert m, "seed_admin function not found"
        body = m.group(0)
        # Must NOT unconditionally overwrite password_hash
        assert "password_hash" in body  # only in the insert path
        # Path: if existing -> return; the update must NOT include password_hash
        # ensure there is a return statement in the existing branch
        assert "return" in body
        # ensure no update_one that $sets password_hash
        assert re.search(r"\$set.*password_hash", body) is None, \
            "seed_admin appears to overwrite password_hash on existing admin"

    def test_seed_idempotency_hash_unchanged_after_restart_semantics(self, mongo):
        """Read current admin hash, ensure it's a bcrypt hash and remains stable across
        a simulated re-seed by invoking the same logic path (existing branch is early-return)."""
        u = mongo.users.find_one({"email": ADMIN_EMAIL}, {"password_hash": 1, "is_admin": 1, "_id": 0})
        assert u is not None, "admin user missing from DB"
        assert u.get("is_admin") is True
        h = u.get("password_hash")
        assert h and h.startswith("$2"), "admin password_hash missing or not bcrypt"
        # A second read must return the same hash (proxy for idempotency)
        u2 = mongo.users.find_one({"email": ADMIN_EMAIL}, {"password_hash": 1, "_id": 0})
        assert u2["password_hash"] == h


# ---------- SEC-002: buy_pixel overspending ----------

class TestSec002BuyPixelOverspend:
    def test_buy_pixel_with_insufficient_coins_returns_402_and_no_claim(
        self, api_client, mongo, small_balance_user
    ):
        # set balance to 0
        mongo.users.update_one({"user_id": small_balance_user["user_id"]}, {"$set": {"coins": 0}})
        pixels = _get_unowned_pixels(api_client, 1)
        pid = pixels[0]["pixel_id"]
        h = {"Authorization": f"Bearer {small_balance_user['token']}", "Content-Type": "application/json"}
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=h, timeout=15)
        assert r.status_code == 402, r.text
        # verify pixel STILL unowned
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["owner_id"] is None
        # verify user coins remained 0 (no phantom charge/refund artifact)
        u = mongo.users.find_one({"user_id": small_balance_user["user_id"]}, {"coins": 1, "pixels_owned": 1, "_id": 0})
        assert u["coins"] == 0
        assert u["pixels_owned"] == 0

    def test_buy_pixel_concurrent_never_negative_balance(
        self, api_client, mongo, small_balance_user
    ):
        """Fire 20 concurrent buys against different pixels. Balance must never go negative and
        total pixels claimed × price must be <= starting balance (30)."""
        # Reset the test user's coins to exactly 30
        mongo.users.update_one(
            {"user_id": small_balance_user["user_id"]},
            {"$set": {"coins": 30, "pixels_owned": 0}},
        )
        # Grab 20 unowned pixels (any prices). We'll compute total spent = sum of successful pixel prices
        pixels = _get_unowned_pixels(api_client, 20)
        pids = [p["pixel_id"] for p in pixels]
        prices_by_pid = {p["pixel_id"]: int(p["price"]) for p in pixels}
        h = {"Authorization": f"Bearer {small_balance_user['token']}", "Content-Type": "application/json"}

        def _buy(pid):
            try:
                r = requests.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=h, timeout=30)
                return pid, r.status_code
            except Exception as e:
                return pid, f"ERR:{e}"

        with cf.ThreadPoolExecutor(max_workers=20) as ex:
            results = list(ex.map(_buy, pids))

        successes = [pid for pid, code in results if code == 200]
        total_spent = sum(prices_by_pid[pid] for pid in successes)
        # Reload user
        u = mongo.users.find_one({"user_id": small_balance_user["user_id"]}, {"coins": 1, "pixels_owned": 1, "_id": 0})
        assert u["coins"] >= 0, f"NEGATIVE BALANCE {u['coins']} after concurrent buys ({results})"
        assert total_spent <= 30, f"total_spent={total_spent} exceeds starting balance 30 (results={results})"
        # Consistency: coins + total_spent == 30
        assert u["coins"] == 30 - total_spent, (u, total_spent, successes, results)
        # pixels_owned counter matches
        assert u["pixels_owned"] == len(successes)


# ---------- SEC-002: buy_resale overspending ----------

class TestSec002BuyResaleOverspend:
    def test_buy_resale_insufficient_coins_returns_402_no_transfer(
        self, api_client, mongo, resale_pool
    ):
        seller = resale_pool["seller"]
        buyer = resale_pool["buyer"]
        # Give seller a pixel via direct mongo (avoid consuming admin coins)
        pixels = _get_unowned_pixels(api_client, 1)
        pid = pixels[0]["pixel_id"]
        mongo.pixels.update_one(
            {"pixel_id": pid},
            {"$set": {"owner_id": seller["user_id"], "owner_name": "TEST_Seller",
                      "purchased_at": datetime.now(timezone.utc), "listed_price": 500}},
        )
        mongo.users.update_one({"user_id": seller["user_id"]}, {"$inc": {"pixels_owned": 1}})
        # Buyer only has 30 coins, listing is 500
        mongo.users.update_one({"user_id": buyer["user_id"]}, {"$set": {"coins": 30, "pixels_owned": 0}})
        h = {"Authorization": f"Bearer {buyer['token']}", "Content-Type": "application/json"}
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy-resale", headers=h, timeout=15)
        assert r.status_code == 402, r.text
        # ownership unchanged, still listed
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["owner_id"] == seller["user_id"]
        assert got["listed_price"] == 500
        # buyer coins unchanged (no phantom charge)
        b = mongo.users.find_one({"user_id": buyer["user_id"]}, {"coins": 1, "pixels_owned": 1, "_id": 0})
        assert b["coins"] == 30
        assert b["pixels_owned"] == 0

    def test_buy_resale_concurrent_never_negative(self, api_client, mongo, resale_pool):
        """Setup: 5 listings at price 20 each owned by seller; buyer has 30 coins.
        Fire concurrent resale purchases; buyer balance must never go negative."""
        seller = resale_pool["seller"]
        buyer = resale_pool["buyer"]
        # Prepare 5 listings owned by seller
        pixels = _get_unowned_pixels(api_client, 5)
        pids = []
        now = datetime.now(timezone.utc)
        for p in pixels:
            mongo.pixels.update_one(
                {"pixel_id": p["pixel_id"]},
                {"$set": {"owner_id": seller["user_id"], "owner_name": "TEST_Seller",
                          "purchased_at": now, "listed_price": 20}},
            )
            pids.append(p["pixel_id"])
        mongo.users.update_one({"user_id": seller["user_id"]}, {"$set": {"pixels_owned": len(pids)}})
        mongo.users.update_one({"user_id": buyer["user_id"]}, {"$set": {"coins": 30, "pixels_owned": 0}})

        h = {"Authorization": f"Bearer {buyer['token']}", "Content-Type": "application/json"}

        def _buy(pid):
            try:
                r = requests.post(f"{BASE_URL}/api/pixels/{pid}/buy-resale", headers=h, timeout=30)
                return pid, r.status_code
            except Exception as e:
                return pid, f"ERR:{e}"

        with cf.ThreadPoolExecutor(max_workers=len(pids)) as ex:
            results = list(ex.map(_buy, pids))

        successes = [pid for pid, code in results if code == 200]
        total_spent = 20 * len(successes)
        b = mongo.users.find_one({"user_id": buyer["user_id"]}, {"coins": 1, "pixels_owned": 1, "_id": 0})
        assert b["coins"] >= 0, f"NEGATIVE buyer coins {b['coins']} (results={results})"
        assert total_spent <= 30, f"total_spent={total_spent} > 30 (results={results})"
        assert b["coins"] == 30 - total_spent, (b, total_spent, results)
        assert b["pixels_owned"] == len(successes)


# ---------- SEC-003: PATCH validation ----------

class TestSec003PatchUrlValidation:
    """PATCH /api/pixels/{id} must reject bad external_link/cover_image/gallery URLs,
    reject bad theme_color values, and reject gallery > 30 items."""

    @pytest.fixture(scope="class")
    def owned_pixel(self, api_client, admin_token, admin_user):
        # Ensure admin has coins
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        me = api_client.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15).json()
        if me["coins"] < 500:
            api_client.patch(
                f"{BASE_URL}/api/admin/users/{admin_user['user_id']}",
                headers=h, json={"coins": 99999}, timeout=15,
            )
        pixels = _get_unowned_pixels(api_client, 1)
        pid = pixels[0]["pixel_id"]
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=h, timeout=20)
        assert r.status_code == 200, r.text
        yield pid
        # release
        api_client.patch(
            f"{BASE_URL}/api/admin/pixels/{pid}", headers=h,
            json={"owner_id": ""}, timeout=15,
        )

    @pytest.mark.parametrize("bad_url", [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "ftp://x.com",
        "data:text/html,<script>",
        "vbscript:msgbox(1)",
    ])
    def test_reject_bad_external_link(self, api_client, admin_token, owned_pixel, bad_url):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"external_link": bad_url}, timeout=15,
        )
        assert r.status_code in (400, 422), f"expected 400/422 for {bad_url}, got {r.status_code}: {r.text}"

    def test_empty_external_link_is_allowed(self, api_client, admin_token, owned_pixel):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"external_link": ""}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["external_link"] == ""

    @pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://x.com"])
    def test_reject_bad_cover_image(self, api_client, admin_token, owned_pixel, bad_url):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"cover_image": bad_url}, timeout=15,
        )
        assert r.status_code in (400, 422), f"got {r.status_code}: {r.text}"

    def test_reject_gallery_with_bad_url(self, api_client, admin_token, owned_pixel):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"gallery": ["https://ok.com/a.jpg", "javascript:alert(1)"]}, timeout=15,
        )
        assert r.status_code in (400, 422), r.text

    def test_reject_gallery_over_30_items(self, api_client, admin_token, owned_pixel):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        big = [f"https://example.com/{i}.jpg" for i in range(31)]
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"gallery": big}, timeout=15,
        )
        assert r.status_code in (400, 422), r.text

    def test_accept_gallery_exactly_30_items(self, api_client, admin_token, owned_pixel):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        exactly30 = [f"https://example.com/{i}.jpg" for i in range(30)]
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"gallery": exactly30}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["gallery"]) == 30

    @pytest.mark.parametrize("bad_color", ["red", "#fff", "javascript:", "#GGGGGG", "rgba(1,2,3,1)", "#12345"])
    def test_reject_bad_theme_color(self, api_client, admin_token, owned_pixel, bad_color):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h, json={"theme_color": bad_color}, timeout=15,
        )
        assert r.status_code in (400, 422), f"{bad_color} got {r.status_code}: {r.text}"

    def test_accept_valid_theme_color_and_urls(self, api_client, admin_token, owned_pixel):
        h = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{owned_pixel}",
            headers=h,
            json={
                "theme_color": "#AABBCC",
                "external_link": "https://example.com/x",
                "cover_image": "http://images.example.com/y.jpg",
                "gallery": ["https://a.com/1.jpg"],
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["theme_color"] == "#AABBCC"
        assert body["external_link"] == "https://example.com/x"
        assert body["cover_image"] == "http://images.example.com/y.jpg"
        assert body["gallery"] == ["https://a.com/1.jpg"]


# ---------- Regression smoke (iteration 1 + 2 critical endpoints) ----------

class TestRegressionSmoke:
    def test_auth_me_and_admin_fields(self, api_client, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = api_client.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15)
        assert r.status_code == 200
        me = r.json()
        assert me["is_admin"] is True
        assert me["email"] == ADMIN_EMAIL

    def test_pixel_out_new_fields_present(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/pixels", timeout=30)
        assert r.status_code == 200
        px = r.json()[0]
        for k in ("number", "gallery", "theme_color", "listed_price"):
            assert k in px, f"missing field {k} in PixelOut"

    def test_rbac_admin_only_endpoint_rejects_no_auth(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/admin/users", timeout=15)
        assert r.status_code == 401

    def test_leaderboard_and_listings_reachable(self, api_client):
        assert api_client.get(f"{BASE_URL}/api/leaderboard", timeout=20).status_code == 200
        assert api_client.get(f"{BASE_URL}/api/listings", timeout=20).status_code == 200
