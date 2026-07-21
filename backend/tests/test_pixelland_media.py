"""
PixelLand — Media Gallery (Cloudinary) test suite.

Covers /api/pixels/{id}/media POST/GET/DELETE:
  * happy path image (owner)
  * happy path video (owner)
  * 401 no token, 403 non-owner, 415 pdf, 413 >10MB, 404 pixel-not-found
  * public GET
  * DELETE owner + verify CDN 404, DELETE non-owner=403
  * enforcement of 20-media-per-pixel limit (21st → 409)
  * admin can upload to a pixel they don't own
  * config sanity — Cloudinary creds from env
  * regression on prior endpoints (auth, buy, listings, leaderboard, admin, PixelOut.gallery/number)
"""
import io
import os
import time
import uuid
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests
from PIL import Image
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import imageio_ffmpeg

BASE_URL = "https://pixelland-mvp.preview.emergentagent.com".rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@pixelland.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Apollo2122@×+>×>adm00140")


# ---------- helpers ----------

def _png_bytes(w=32, h=32, color=(120, 30, 200)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _large_png_bytes(target_mb=11) -> bytes:
    """Create a PNG >10MB by using a big canvas with random noise (poor compression)."""
    import random
    side = 4200  # ~17M pixels ⇒ >10MB PNG with noise
    img = Image.new("RGB", (side, side))
    px = img.load()
    r = random.Random(7)
    for y in range(side):
        row = [(r.randint(0, 255), r.randint(0, 255), r.randint(0, 255)) for _ in range(side)]
        for x in range(side):
            px[x, y] = row[x]
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    data = buf.getvalue()
    # If still under, pad the buffer by appending an extra IDAT-safe tail (Cloudinary parses PNGs; we just need >10MB total)
    if len(data) < target_mb * 1024 * 1024:
        # Append junk after IEND — the server counts uploaded bytes BEFORE Cloudinary, so extra bytes still count.
        data = data + b"\x00" * (target_mb * 1024 * 1024 - len(data) + 1024)
    return data


def _make_mp4(path: str, seconds=1):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.check_call(
        [ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c=blue:s=320x240:d={seconds}",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-loglevel", "error", path],
        timeout=60,
    )


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- fixtures ----------


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin-login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"admin-login failed: {r.status_code} {r.text}"
    return r.json()  # {session_token, user}


@pytest.fixture(scope="module")
def admin_token(admin):
    return admin["session_token"]


@pytest.fixture(scope="module")
def admin_user(admin):
    return admin["user"]


@pytest.fixture(scope="module")
def mongo():
    """Async mongo handle for direct-DB seeding of non-admin users and pixel ownership."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cli = AsyncIOMotorClient(MONGO_URL)
    return {"db": cli[DB_NAME], "loop": loop, "cli": cli}


def _run(coro, mongo):
    return mongo["loop"].run_until_complete(coro)


@pytest.fixture(scope="module")
def owner_user(mongo):
    """Create a NON-admin user with a session, and give them ownership of a fresh pixel."""
    db = mongo["db"]
    user_id = f"usr_TEST_{uuid.uuid4().hex[:10]}"
    token = f"tst_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    user_doc = {
        "user_id": user_id,
        "email": f"TEST_owner_{user_id}@example.com",
        "name": "TEST Media Owner",
        "picture": None,
        "coins": 10000,
        "pixels_owned": 0,
        "is_admin": False,
        "joined_at": now,
    }
    sess_doc = {
        "session_token": token,
        "user_id": user_id,
        "expires_at": now + timedelta(days=1),
        "created_at": now,
    }
    _run(db.users.insert_one(user_doc), mongo)
    _run(db.user_sessions.insert_one(sess_doc), mongo)

    # Grab a fresh unowned pixel for this user (avoid 0_0 which is used by other tests)
    pixel = _run(db.pixels.find_one({"owner_id": None, "listed_price": None}, {"_id": 0}), mongo)
    assert pixel, "no unowned pixel found"
    pid = pixel["pixel_id"]
    _run(db.pixels.update_one({"pixel_id": pid},
                              {"$set": {"owner_id": user_id, "owned_at": now, "gallery": []}}),
         mongo)

    yield {"user_id": user_id, "token": token, "pixel_id": pid}

    # Teardown: release pixel, remove media docs+users
    _run(db.pixel_media.delete_many({"pixel_id": pid}), mongo)
    _run(db.pixels.update_one(
        {"pixel_id": pid},
        {"$set": {"owner_id": None, "owned_at": None, "listed_price": None,
                  "gallery": [], "external_link": None, "theme_color": None,
                  "cover_image": None, "title": None, "description": None}},
    ), mongo)
    _run(db.users.delete_one({"user_id": user_id}), mongo)
    _run(db.user_sessions.delete_one({"session_token": token}), mongo)


@pytest.fixture(scope="module")
def other_user(mongo):
    """Second non-admin user (used to test 403 non-owner)."""
    db = mongo["db"]
    user_id = f"usr_TEST_{uuid.uuid4().hex[:10]}"
    token = f"tst_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    _run(db.users.insert_one({
        "user_id": user_id, "email": f"TEST_other_{user_id}@example.com",
        "name": "TEST Non Owner", "picture": None, "coins": 500,
        "pixels_owned": 0, "is_admin": False, "joined_at": now,
    }), mongo)
    _run(db.user_sessions.insert_one({
        "session_token": token, "user_id": user_id,
        "expires_at": now + timedelta(days=1), "created_at": now,
    }), mongo)
    yield {"user_id": user_id, "token": token}
    _run(db.users.delete_one({"user_id": user_id}), mongo)
    _run(db.user_sessions.delete_one({"session_token": token}), mongo)


# ---------- Config sanity ----------


class TestConfig:
    def test_cloudinary_env_present_and_matches(self):
        assert os.environ.get("CLOUDINARY_CLOUD_NAME") == "cynpx6ck"
        assert os.environ.get("CLOUDINARY_API_KEY")
        assert os.environ.get("CLOUDINARY_API_SECRET")

    def test_no_hardcoded_cloudinary_secret_in_source(self):
        with open("/app/backend/server.py") as f:
            src = f.read()
        # secret must NOT appear literally
        assert os.environ["CLOUDINARY_API_SECRET"] not in src
        # cloud name is fine to appear in tests/strings — but server should read via os.environ
        assert 'os.environ["CLOUDINARY_CLOUD_NAME"]' in src


# ---------- Media upload — happy path (image, owner) ----------


class TestImageUploadOwner:
    def test_owner_uploads_png_returns_200(self, owner_user):
        files = {"file": ("test.png", _png_bytes(), "image/png")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "image"
        assert body["pixel_id"] == owner_user["pixel_id"]
        assert body["url"].startswith("https://res.cloudinary.com/cynpx6ck/")
        assert body["thumbnail_url"].startswith("https://res.cloudinary.com/cynpx6ck/")
        assert body["media_id"].startswith("med_")
        assert body["bytes"] > 0
        # stash for follow-up tests
        pytest.image_media = body

    def test_uploaded_url_is_reachable_200(self):
        m = getattr(pytest, "image_media", None)
        assert m, "prior upload missing"
        r = requests.get(m["url"], timeout=20)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")

    def test_public_list_contains_the_upload(self, owner_user):
        r = requests.get(f"{API}/pixels/{owner_user['pixel_id']}/media", timeout=20)
        assert r.status_code == 200
        ids = [i["media_id"] for i in r.json()]
        assert pytest.image_media["media_id"] in ids

    def test_pixelout_gallery_and_number_reflect_upload(self, owner_user):
        r = requests.get(f"{API}/pixels/{owner_user['pixel_id']}", timeout=20)
        assert r.status_code == 200
        p = r.json()
        assert "number" in p and isinstance(p["number"], int)
        assert "gallery" in p and isinstance(p["gallery"], list)
        assert pytest.image_media["url"] in p["gallery"]


# ---------- Media upload — auth/validation errors ----------


class TestUploadValidation:
    def test_no_token_returns_401(self, owner_user):
        files = {"file": ("t.png", _png_bytes(), "image/png")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          files=files, timeout=20)
        assert r.status_code == 401

    def test_non_owner_returns_403(self, owner_user, other_user):
        files = {"file": ("t.png", _png_bytes(), "image/png")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(other_user["token"]), files=files, timeout=20)
        assert r.status_code == 403

    def test_pdf_content_type_returns_415(self, owner_user):
        files = {"file": ("x.pdf", b"%PDF-1.4\n%fake", "application/pdf")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=20)
        assert r.status_code == 415

    def test_pixel_not_found_returns_404(self, owner_user):
        files = {"file": ("t.png", _png_bytes(), "image/png")}
        r = requests.post(f"{API}/pixels/nope_9999/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=20)
        assert r.status_code == 404

    def test_image_over_10mb_returns_413(self, owner_user):
        big = _large_png_bytes(target_mb=11)
        assert len(big) > 10 * 1024 * 1024, f"generated only {len(big)} bytes"
        files = {"file": ("big.png", big, "image/png")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=120)
        assert r.status_code == 413, f"expected 413, got {r.status_code}: {r.text[:200]}"


# ---------- Video upload (owner) ----------


class TestVideoUploadOwner:
    def test_owner_uploads_mp4_returns_video_kind(self, owner_user, tmp_path_factory):
        path = str(tmp_path_factory.mktemp("v") / "clip.mp4")
        _make_mp4(path, seconds=1)
        with open(path, "rb") as f:
            files = {"file": ("clip.mp4", f.read(), "video/mp4")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "video"
        assert body["url"].startswith("https://res.cloudinary.com/cynpx6ck/")
        assert body["thumbnail_url"].startswith("https://res.cloudinary.com/cynpx6ck/")
        assert "/video/upload/so_0/" in body["thumbnail_url"], body["thumbnail_url"]
        assert body["thumbnail_url"].endswith(".jpg")
        pytest.video_media = body

    def test_video_poster_thumbnail_reachable(self):
        m = getattr(pytest, "video_media", None)
        assert m
        # Cloudinary needs a moment to render on-the-fly thumb
        for _ in range(5):
            r = requests.get(m["thumbnail_url"], timeout=20)
            if r.status_code == 200:
                break
            time.sleep(1)
        assert r.status_code == 200, r.status_code
        assert r.headers.get("content-type", "").startswith("image/")


# ---------- Delete media ----------


class TestDeleteMedia:
    def test_non_owner_delete_returns_403(self, owner_user, other_user):
        m = pytest.image_media
        r = requests.delete(f"{API}/pixels/{owner_user['pixel_id']}/media/{m['media_id']}",
                            headers=_auth(other_user["token"]), timeout=20)
        assert r.status_code == 403

    def test_owner_delete_removes_from_db_and_cdn(self, owner_user):
        m = pytest.image_media
        r = requests.delete(f"{API}/pixels/{owner_user['pixel_id']}/media/{m['media_id']}",
                            headers=_auth(owner_user["token"]), timeout=20)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # DB: gone from list
        r2 = requests.get(f"{API}/pixels/{owner_user['pixel_id']}/media", timeout=20)
        assert m["media_id"] not in [x["media_id"] for x in r2.json()]

        # gallery URL pulled from Pixel doc
        r3 = requests.get(f"{API}/pixels/{owner_user['pixel_id']}", timeout=20)
        assert m["url"] not in r3.json().get("gallery", [])

        # CDN: eventually 404 (Cloudinary invalidate is async — retry a bit)
        final = None
        for _ in range(6):
            resp = requests.get(m["url"], timeout=20)
            final = resp.status_code
            if final == 404:
                break
            time.sleep(2)
        # We accept either the invalidated 404 OR the resource-not-found 404 wrapper.
        assert final == 404, f"CDN did not 404 after delete+invalidate; last={final}"


# ---------- Admin can upload to any pixel ----------


class TestAdminCanUploadAny:
    def test_admin_uploads_on_owner_pixel(self, owner_user, admin_token):
        files = {"file": ("admin.png", _png_bytes(color=(0, 200, 100)), "image/png")}
        r = requests.post(f"{API}/pixels/{owner_user['pixel_id']}/media",
                          headers=_auth(admin_token), files=files, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "image"
        pytest.admin_upload = body

    def test_admin_delete_own_upload(self, owner_user, admin_token):
        m = pytest.admin_upload
        r = requests.delete(f"{API}/pixels/{owner_user['pixel_id']}/media/{m['media_id']}",
                            headers=_auth(admin_token), timeout=20)
        assert r.status_code == 200


# ---------- 20-per-pixel enforcement ----------


class TestQuotaEnforcement:
    def test_21st_upload_returns_409(self, owner_user, mongo):
        db = mongo["db"]
        pid = owner_user["pixel_id"]

        # Clean any prior media on this pixel from previous tests to start from zero.
        _run(db.pixel_media.delete_many({"pixel_id": pid}), mongo)
        _run(db.pixels.update_one({"pixel_id": pid}, {"$set": {"gallery": []}}), mongo)

        # Insert 20 fake media rows directly into Mongo (avoid 20 real Cloudinary uploads).
        # The endpoint counts via db.pixel_media.count_documents — this hits the same code path.
        fake_docs = []
        for i in range(20):
            fake_docs.append({
                "media_id": f"med_TESTQUOTA_{uuid.uuid4().hex[:10]}",
                "pixel_id": pid,
                "kind": "image",
                "url": f"https://res.cloudinary.com/cynpx6ck/image/upload/quota_{i}.png",
                "thumbnail_url": f"https://res.cloudinary.com/cynpx6ck/image/upload/quota_{i}.png",
                "public_id": f"pixelland/pixel_{pid}/quota_{i}",
                "resource_type": "image",
                "bytes": 100,
                "mime_type": "image/png",
                "uploaded_by": owner_user["user_id"],
                "created_at": datetime.now(timezone.utc),
            })
        _run(db.pixel_media.insert_many(fake_docs), mongo)

        # 21st: should be rejected 409 with correct message
        files = {"file": ("t.png", _png_bytes(), "image/png")}
        r = requests.post(f"{API}/pixels/{pid}/media",
                          headers=_auth(owner_user["token"]), files=files, timeout=30)
        assert r.status_code == 409, r.text
        assert "Limite atingido" in r.text and "20" in r.text

        # cleanup fake rows so downstream tests / users still see clean state
        _run(db.pixel_media.delete_many({"media_id": {"$regex": "^med_TESTQUOTA_"}}), mongo)


# ---------- Regression suite (auth, buy, listings, leaderboard, admin, PixelOut shape) ----------


class TestRegression:
    def test_auth_me_admin(self, admin_token, admin_user):
        r = requests.get(f"{API}/auth/me", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["email"].lower() == admin_user["email"].lower()

    def test_pixels_list_shape(self):
        r = requests.get(f"{API}/pixels", timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) == 400
        sample = arr[0]
        for k in ("pixel_id", "x", "y", "price", "number", "gallery"):
            assert k in sample, f"missing key {k} in PixelOut"

    def test_leaderboard_ok(self):
        r = requests.get(f"{API}/leaderboard", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_listings_endpoint_ok(self):
        r = requests.get(f"{API}/listings", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_pixel_transactions_public(self):
        # per-pixel transactions endpoint
        r = requests.get(f"{API}/pixels/0_0/transactions", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_users_list(self, admin_token):
        r = requests.get(f"{API}/admin/users", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_buy_then_list_then_unlist_flow(self, mongo):
        """Full marketplace regression: fresh user buys an unowned pixel, lists it, unlists."""
        db = mongo["db"]
        uid = f"usr_TEST_{uuid.uuid4().hex[:10]}"
        tok = f"tst_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        _run(db.users.insert_one({
            "user_id": uid, "email": f"TEST_buy_{uid}@e.com", "name": "TEST buyer",
            "picture": None, "coins": 1000, "pixels_owned": 0,
            "is_admin": False, "joined_at": now,
        }), mongo)
        _run(db.user_sessions.insert_one({
            "session_token": tok, "user_id": uid,
            "expires_at": now + timedelta(days=1), "created_at": now,
        }), mongo)

        pix = _run(db.pixels.find_one({"owner_id": None, "listed_price": None}, {"_id": 0}), mongo)
        assert pix, "no free pixel"
        pid = pix["pixel_id"]

        try:
            # buy
            r = requests.post(f"{API}/pixels/{pid}/buy", headers=_auth(tok), timeout=20)
            assert r.status_code == 200, r.text
            assert r.json()["owner_id"] == uid

            # list
            r = requests.post(f"{API}/pixels/{pid}/list",
                              headers={**_auth(tok), "Content-Type": "application/json"},
                              json={"price": 42}, timeout=20)
            assert r.status_code == 200, r.text
            assert r.json()["listed_price"] == 42

            # unlist (DELETE /pixels/{id}/list)
            r = requests.delete(f"{API}/pixels/{pid}/list", headers=_auth(tok), timeout=20)
            assert r.status_code == 200
            assert r.json().get("listed_price") is None
        finally:
            _run(db.pixels.update_one({"pixel_id": pid},
                                      {"$set": {"owner_id": None, "owned_at": None,
                                                "listed_price": None, "gallery": [],
                                                "external_link": None, "theme_color": None,
                                                "cover_image": None, "title": None,
                                                "description": None}}), mongo)
            _run(db.users.delete_one({"user_id": uid}), mongo)
            _run(db.user_sessions.delete_one({"session_token": tok}), mongo)
