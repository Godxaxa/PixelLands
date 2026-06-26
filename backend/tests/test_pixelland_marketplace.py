"""PixelLand Iteration 2 - Marketplace, Transactions, Leaderboard, Personalization.

Covers ONLY new endpoints / behavior added in iteration 2:
  - POST /api/pixels/{id}/list  (validation, ownership)
  - DELETE /api/pixels/{id}/list
  - POST /api/pixels/{id}/buy-resale  (happy path + 409 paths)
  - GET /api/pixels/{id}/transactions  (primary + resale rows)
  - GET /api/listings
  - GET /api/leaderboard
  - PATCH /api/pixels/{id} with gallery/external_link/theme_color
  - PixelOut surfaces gallery/external_link/theme_color/listed_price

A second non-admin user is provisioned by direct mongo insert (+ session token row)
so we can exercise the resale flow with a different buyer.
"""

import os
import uuid
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://pixelland-mvp.preview.emergentagent.com"
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# state shared across tests in this module
STATE: dict = {}


# ---------- second user fixture ----------

@pytest.fixture(scope="module")
def second_user():
    """Insert a non-admin test buyer + its session token directly into mongo."""
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    uid = f"user_{uuid.uuid4().hex[:12]}"
    token = f"tst_{uuid.uuid4().hex}"
    email = f"test_buyer_{uuid.uuid4().hex[:6]}@pixelland.test"
    db.users.insert_one({
        "user_id": uid,
        "email": email,
        "name": "TEST_Buyer",
        "picture": None,
        "coins": 5000,
        "pixels_owned": 0,
        "is_admin": False,
        "created_at": datetime.now(timezone.utc),
    })
    db.user_sessions.insert_one({
        "session_token": token,
        "user_id": uid,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        "created_at": datetime.now(timezone.utc),
    })
    yield {"user_id": uid, "email": email, "token": token}
    # teardown
    try:
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})
    finally:
        client.close()


@pytest.fixture
def buyer_headers(second_user):
    return {"Authorization": f"Bearer {second_user['token']}", "Content-Type": "application/json"}


# ---------- helpers ----------

def _find_unowned_pixel(api_client):
    r = api_client.get(f"{BASE_URL}/api/pixels", timeout=30)
    assert r.status_code == 200
    for p in r.json():
        if not p.get("owner_id"):
            return p
    raise AssertionError("No unowned pixels available")


def _ensure_admin_has_coins(api_client, auth_headers, admin_user, minimum=2000):
    me = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
    if me["coins"] < minimum:
        api_client.patch(
            f"{BASE_URL}/api/admin/users/{admin_user['user_id']}",
            headers=auth_headers,
            json={"coins": 99999},
            timeout=15,
        )


# ---------- 1. List/Unlist validation & ownership ----------

class TestListUnlist:
    def test_admin_buys_pixel_for_resale_tests(self, api_client, auth_headers, admin_user):
        _ensure_admin_has_coins(api_client, auth_headers, admin_user)
        pixel = _find_unowned_pixel(api_client)
        pid = pixel["pixel_id"]
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["owner_id"] == admin_user["user_id"]
        # New iteration-2 fields surface in response
        assert "gallery" in body and isinstance(body["gallery"], list)
        assert "external_link" in body
        assert "theme_color" in body
        assert "listed_price" in body
        assert body["listed_price"] is None
        STATE["pid"] = pid
        STATE["primary_price"] = body["price"]

    def test_list_with_zero_price_returns_400(self, api_client, auth_headers):
        pid = STATE["pid"]
        r = api_client.post(
            f"{BASE_URL}/api/pixels/{pid}/list",
            headers=auth_headers, json={"price": 0}, timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_list_with_negative_price_returns_400(self, api_client, auth_headers):
        pid = STATE["pid"]
        r = api_client.post(
            f"{BASE_URL}/api/pixels/{pid}/list",
            headers=auth_headers, json={"price": -50}, timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_list_as_non_owner_returns_403(self, api_client, buyer_headers):
        pid = STATE["pid"]
        r = api_client.post(
            f"{BASE_URL}/api/pixels/{pid}/list",
            headers=buyer_headers, json={"price": 100}, timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_list_as_owner_sets_listed_price(self, api_client, auth_headers):
        pid = STATE["pid"]
        r = api_client.post(
            f"{BASE_URL}/api/pixels/{pid}/list",
            headers=auth_headers, json={"price": 200}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["listed_price"] == 200
        # verify via GET
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["listed_price"] == 200

    def test_unlist_clears_listed_price(self, api_client, auth_headers):
        pid = STATE["pid"]
        r = api_client.delete(f"{BASE_URL}/api/pixels/{pid}/list", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["listed_price"] is None
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["listed_price"] is None

    def test_unlist_as_non_owner_returns_403(self, api_client, auth_headers, buyer_headers):
        # re-list first so the pixel is in a listed state
        pid = STATE["pid"]
        api_client.post(
            f"{BASE_URL}/api/pixels/{pid}/list",
            headers=auth_headers, json={"price": 150}, timeout=15,
        )
        r = api_client.delete(f"{BASE_URL}/api/pixels/{pid}/list", headers=buyer_headers, timeout=15)
        assert r.status_code == 403, r.text


# ---------- 2. GET /api/listings ----------

class TestListingsEndpoint:
    def test_listings_only_returns_pixels_with_listed_price(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/listings", timeout=15)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        for it in items:
            assert it.get("listed_price") is not None
            assert int(it["listed_price"]) > 0
        # the pixel we just listed should appear
        assert any(it["pixel_id"] == STATE["pid"] for it in items)


# ---------- 3. Resale flow ----------

class TestResaleFlow:
    def test_buy_resale_by_owner_returns_409(self, api_client, auth_headers):
        pid = STATE["pid"]  # admin is owner & it's listed
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy-resale", headers=auth_headers, timeout=15)
        assert r.status_code == 409, r.text

    def test_buy_resale_on_unlisted_pixel_returns_409(self, api_client, auth_headers, buyer_headers, admin_user):
        # Buy a fresh pixel as admin but DON'T list it
        _ensure_admin_has_coins(api_client, auth_headers, admin_user)
        pixel = _find_unowned_pixel(api_client)
        pid = pixel["pixel_id"]
        rb = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy", headers=auth_headers, timeout=20)
        assert rb.status_code == 200
        STATE["unlisted_pid"] = pid
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy-resale", headers=buyer_headers, timeout=15)
        assert r.status_code == 409, r.text

    def test_buy_resale_happy_path_transfers_ownership_and_coins(
        self, api_client, auth_headers, buyer_headers, second_user, admin_user
    ):
        pid = STATE["pid"]
        # ensure pixel is listed at 150 (set in TestListUnlist last test)
        listed = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert listed["listed_price"] == 150
        list_price = 150
        expected_fee = (list_price * 10) // 100  # 15
        expected_proceeds = list_price - expected_fee  # 135

        # snapshots
        admin_me = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
        admin_coins_before = admin_me["coins"]
        admin_owned_before = admin_me["pixels_owned"]
        buyer_me = api_client.get(f"{BASE_URL}/api/auth/me", headers=buyer_headers, timeout=15).json()
        buyer_coins_before = buyer_me["coins"]
        buyer_owned_before = buyer_me["pixels_owned"]

        # buyer purchases
        r = api_client.post(f"{BASE_URL}/api/pixels/{pid}/buy-resale", headers=buyer_headers, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["owner_id"] == second_user["user_id"]
        assert body["listed_price"] is None  # cleared
        assert body["purchased_at"]

        # GET to verify persistence
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["owner_id"] == second_user["user_id"]
        assert got["listed_price"] is None

        # balances
        admin_me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15).json()
        buyer_me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=buyer_headers, timeout=15).json()
        assert admin_me2["coins"] == admin_coins_before + expected_proceeds, (
            admin_me2["coins"], admin_coins_before, expected_proceeds,
        )
        assert admin_me2["pixels_owned"] == admin_owned_before - 1
        assert buyer_me2["coins"] == buyer_coins_before - list_price
        assert buyer_me2["pixels_owned"] == buyer_owned_before + 1

        STATE["list_price"] = list_price
        STATE["fee"] = expected_fee
        STATE["proceeds"] = expected_proceeds


# ---------- 4. Transactions history ----------

class TestTransactionsHistory:
    def test_transactions_contain_primary_and_resale(self, api_client):
        pid = STATE["pid"]
        r = api_client.get(f"{BASE_URL}/api/pixels/{pid}/transactions", timeout=15)
        assert r.status_code == 200, r.text
        txs = r.json()
        assert isinstance(txs, list)
        kinds = [t["kind"] for t in txs]
        assert "primary" in kinds, kinds
        assert "resale" in kinds, kinds

        resale = next(t for t in txs if t["kind"] == "resale")
        assert resale["price"] == STATE["list_price"]
        assert resale["fee"] == STATE["fee"]
        assert resale["seller_proceeds"] == STATE["proceeds"]
        assert resale["seller_id"]  # must be set for resale
        assert resale["buyer_id"]
        assert resale["pixel_id"] == pid

        primary = next(t for t in txs if t["kind"] == "primary")
        assert primary["fee"] == 0
        assert primary["seller_id"] in (None, "")  # no seller on primary
        assert primary["price"] == STATE.get("primary_price", primary["price"])


# ---------- 5. Leaderboard ----------

class TestLeaderboard:
    def test_leaderboard_sorted_and_aggregates_spend(self, api_client, second_user):
        r = api_client.get(f"{BASE_URL}/api/leaderboard", timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and rows, "leaderboard should not be empty"
        # sorted by pixels_owned desc
        owned_seq = [row["pixels_owned"] for row in rows]
        assert owned_seq == sorted(owned_seq, reverse=True), owned_seq
        # find our buyer - should have total_spent >= list_price (just bought a resale)
        buyer_row = next((row for row in rows if row["user_id"] == second_user["user_id"]), None)
        assert buyer_row is not None, "buyer not in leaderboard"
        assert buyer_row["pixels_owned"] >= 1
        assert buyer_row["total_spent"] >= STATE["list_price"]
        # password_hash must never leak
        for row in rows:
            assert "password_hash" not in row


# ---------- 6. Pixel personalization (gallery/external_link/theme_color) ----------

class TestPixelPersonalization:
    def test_patch_personalization_as_owner(self, api_client, buyer_headers, second_user):
        pid = STATE["pid"]  # buyer now owns it
        payload = {
            "gallery": [
                "https://example.com/a.jpg",
                "https://example.com/b.jpg",
            ],
            "external_link": "https://example.com/portfolio",
            "theme_color": "#FF00AA",
        }
        r = api_client.patch(
            f"{BASE_URL}/api/pixels/{pid}", headers=buyer_headers, json=payload, timeout=15
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["gallery"] == payload["gallery"]
        assert body["external_link"] == payload["external_link"]
        assert body["theme_color"] == payload["theme_color"]
        # GET persistence
        got = api_client.get(f"{BASE_URL}/api/pixels/{pid}", timeout=15).json()
        assert got["gallery"] == payload["gallery"]
        assert got["external_link"] == payload["external_link"]
        assert got["theme_color"] == payload["theme_color"]


# ---------- 7. Cleanup teardown ----------

@pytest.fixture(scope="module", autouse=True)
def _cleanup_pixels(api_client_factory):
    """After this module finishes, release the test pixels back to unowned."""
    yield
    # session-level admin token to do cleanup
    r = api_client_factory.post(
        f"{BASE_URL}/api/auth/admin-login",
        json={"email": "admin@pixelland.com", "password": "Apollo2122@×+>×>adm00140"},
        timeout=15,
    )
    if r.status_code != 200:
        return
    tok = r.json()["session_token"]
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    for key in ("pid", "unlisted_pid"):
        pid = STATE.get(key)
        if pid:
            api_client_factory.patch(
                f"{BASE_URL}/api/admin/pixels/{pid}",
                headers=h,
                json={"owner_id": "", "name": f"Pixel {pid.replace('_', ', ')}", "description": "An unclaimed digital territory awaiting a universe."},
                timeout=15,
            )


@pytest.fixture(scope="module")
def api_client_factory():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
