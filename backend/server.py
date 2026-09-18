"""PixelLand backend - FastAPI + MongoDB.

Implements:
 - Emergent Google Auth (session_token bearer flow)
 - Admin email/password login (single admin: admin@pixelland.com)
 - Pixel grid: 20x20 = 400 pixels with varied prices in Pixel Coins
 - Buy pixel flow + pixel detail update
 - Admin endpoints for users + pixels
"""

from __future__ import annotations

import os
import logging
import random
import shutil
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

import bcrypt
import cloudinary
import cloudinary.uploader
import httpx
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.openai.image_generation import OpenAIImageGeneration
from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends, UploadFile, File
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.cors import CORSMiddleware


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger("pixelland")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

# ---------------- Configuration ----------------

GRID_SIZE = 20
TOTAL_PIXELS = GRID_SIZE * GRID_SIZE
INITIAL_COINS = 1000
PIXEL_PRICES = [5, 10, 20, 30, 40, 50, 100]
DEFAULT_COVER = (
    "https://images.unsplash.com/photo-1713981272299-355d7038d708?"
    "crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMzV8MHwxfHNlYXJjaHw0fHxhYnN0cmFjdCUyMGRpZ2l0YWwlMjBwaXhlbCUyMGFydCUyMGRhcmt8ZW58MHx8fHwxNzgyNDMyMDE4fDA"
    "&ixlib=rb-4.1.0&q=85"
)

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"].lower().strip()
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

# --- Cloudinary media storage ---
CLOUDINARY_CLOUD_NAME = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_API_KEY = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_API_SECRET = os.environ["CLOUDINARY_API_SECRET"]

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-quicktime"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024        # 10 MB
MAX_VIDEO_BYTES = 200 * 1024 * 1024       # 200 MB
MAX_MEDIA_PER_PIXEL = 20

# --- Emergent LLM key (universal) for AI text + image generation ---
EMERGENT_LLM_KEY = os.environ["EMERGENT_LLM_KEY"]
AI_TEXT_MODEL = ("openai", "gpt-5.4")
AI_IMAGE_MODEL = "gpt-image-1"

# --- PayPal (sandbox by default) ---
PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "sandbox").lower()
PAYPAL_CLIENT_ID = os.environ["PAYPAL_CLIENT_ID"]
PAYPAL_SECRET = os.environ["PAYPAL_SECRET"]
PAYPAL_BASE = (
    "https://api-m.sandbox.paypal.com"
    if PAYPAL_MODE == "sandbox"
    else "https://api-m.paypal.com"
)

COIN_BUNDLES = {
    "bundle_1000": {"coins": 1000, "price_usd": "4.99", "label": "1.000 Pixel Coins"},
    "bundle_3000": {"coins": 3500, "price_usd": "9.99", "label": "3.500 Pixel Coins (+500 bônus)"},
    "bundle_8000": {"coins": 10000, "price_usd": "19.99", "label": "10.000 Pixel Coins (+2000 bônus)"},
}

EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

mongo_url = os.environ["MONGO_URL"]
db_name = os.environ.get("DB_NAME", "pixelland")
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# ---------------- Models ----------------


class GoogleSessionIn(BaseModel):
    session_token: str  # Returned from Emergent session-data API


class AdminLoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    coins: int
    pixels_owned: int
    is_admin: bool
    joined_at: Optional[str] = None


class SessionOut(BaseModel):
    session_token: str
    user: UserOut


class PixelOut(BaseModel):
    pixel_id: str
    x: int
    y: int
    number: int
    price: int
    name: str
    description: Optional[str] = ""
    cover_image: Optional[str] = None
    cover_media_id: Optional[str] = None
    cover_type: str = "image"  # "image" | "video"
    cover_video: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    purchased_at: Optional[str] = None
    gallery: List[str] = Field(default_factory=list)
    external_link: Optional[str] = ""
    theme_color: Optional[str] = "#00E5FF"
    listed_price: Optional[int] = None


def _validate_http_url(v: Optional[str]) -> Optional[str]:
    """Allow empty string (clears link) or http/https URL only."""
    if v is None:
        return v
    s = v.strip()
    if s == "":
        return s
    low = s.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")
    if len(s) > 2048:
        raise ValueError("URL too long")
    return s


class PixelUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    cover_media_id: Optional[str] = None
    gallery: Optional[List[str]] = None
    external_link: Optional[str] = None
    theme_color: Optional[str] = None

    @field_validator("cover_image", "external_link")
    @classmethod
    def _v_url(cls, v):
        return _validate_http_url(v)

    @field_validator("gallery")
    @classmethod
    def _v_gallery(cls, v):
        if v is None:
            return v
        if len(v) > 30:
            raise ValueError("Gallery limited to 30 images")
        out = []
        for item in v:
            validated = _validate_http_url(item)
            if not validated:
                raise ValueError("Gallery URL must be http(s)")
            out.append(validated)
        return out

    @field_validator("theme_color")
    @classmethod
    def _v_theme(cls, v):
        if v is None:
            return v
        s = v.strip()
        if s == "":
            return s
        # Simple hex color check
        import re
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", s):
            raise ValueError("theme_color must be a #RRGGBB hex value")
        return s


class AdminPixelUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    price: Optional[int] = None
    owner_id: Optional[str] = None  # set to "" to clear ownership


class ListPixelIn(BaseModel):
    price: int


class TransactionOut(BaseModel):
    tx_id: str
    pixel_id: str
    kind: str  # "primary" | "resale"
    seller_id: Optional[str] = None
    seller_name: Optional[str] = None
    buyer_id: str
    buyer_name: str
    price: int
    fee: int
    seller_proceeds: int
    timestamp: str


class LeaderboardEntry(BaseModel):
    user_id: str
    name: str
    picture: Optional[str] = None
    pixels_owned: int
    total_spent: int
    is_admin: bool


class MediaOut(BaseModel):
    media_id: str
    pixel_id: str
    kind: str  # "image" | "video"
    url: str
    thumbnail_url: str
    bytes: int
    mime_type: str
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: str


class AiDescriptionIn(BaseModel):
    name: Optional[str] = ""
    hint: Optional[str] = ""


class AiDescriptionOut(BaseModel):
    description: str


class AiCoverIn(BaseModel):
    prompt: str

    @field_validator("prompt")
    @classmethod
    def _v_prompt(cls, v):
        s = (v or "").strip()
        if len(s) < 3:
            raise ValueError("Prompt is too short")
        if len(s) > 500:
            raise ValueError("Prompt too long (max 500 chars)")
        return s


class CoinBundleOut(BaseModel):
    bundle_id: str
    coins: int
    price_usd: str
    label: str


class CreateOrderIn(BaseModel):
    bundle_id: str


class CreateOrderOut(BaseModel):
    order_id: str
    approve_url: str
    bundle_id: str
    coins: int
    price_usd: str


class CaptureOrderOut(BaseModel):
    order_id: str
    status: str
    credited: bool
    coins_added: int
    new_balance: int


class AdminUserUpdateIn(BaseModel):
    name: Optional[str] = None
    coins: Optional[int] = None
    is_admin: Optional[bool] = None


# ---------------- Helpers ----------------


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _user_to_out(u: dict) -> UserOut:
    joined = u.get("created_at")
    if isinstance(joined, datetime):
        joined = _to_aware(joined).isoformat()
    return UserOut(
        user_id=u["user_id"],
        email=u["email"],
        name=u.get("name") or "",
        picture=u.get("picture"),
        coins=int(u.get("coins", 0)),
        pixels_owned=int(u.get("pixels_owned", 0)),
        is_admin=bool(u.get("is_admin", False)),
        joined_at=joined,
    )


def _pixel_to_out(p: dict) -> PixelOut:
    purchased_at = p.get("purchased_at")
    if isinstance(purchased_at, datetime):
        purchased_at = _to_aware(purchased_at).isoformat()
    x = int(p["x"])
    y = int(p["y"])
    return PixelOut(
        pixel_id=p["pixel_id"],
        x=x,
        y=y,
        number=y * GRID_SIZE + x + 1,
        price=int(p["price"]),
        name=p.get("name") or "",
        description=p.get("description") or "",
        cover_image=p.get("cover_image") or DEFAULT_COVER,
        cover_media_id=p.get("cover_media_id"),
        cover_type=p.get("cover_type") or "image",
        cover_video=p.get("cover_video"),
        owner_id=p.get("owner_id"),
        owner_name=p.get("owner_name"),
        purchased_at=purchased_at,
        gallery=list(p.get("gallery") or []),
        external_link=p.get("external_link") or "",
        theme_color=p.get("theme_color") or "#00E5FF",
        listed_price=p.get("listed_price"),
    )


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = _to_aware(session["expires_at"])
    if expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ---------------- Seeding ----------------


async def seed_pixels():
    count = await db.pixels.count_documents({})
    if count >= TOTAL_PIXELS:
        return
    docs = []
    rnd = random.Random(42)
    for y in range(GRID_SIZE):
        for x in range(GRID_SIZE):
            pid = f"{x}_{y}"
            docs.append({
                "pixel_id": pid,
                "x": x,
                "y": y,
                "price": rnd.choice(PIXEL_PRICES),
                "name": f"Pixel ({x},{y})",
                "description": "An unclaimed digital territory awaiting a universe.",
                "cover_image": DEFAULT_COVER,
                "owner_id": None,
                "owner_name": None,
                "purchased_at": None,
                "created_at": now_utc(),
            })
    # only insert missing
    existing = {d["pixel_id"] async for d in db.pixels.find({}, {"pixel_id": 1, "_id": 0})}
    new_docs = [d for d in docs if d["pixel_id"] not in existing]
    if new_docs:
        await db.pixels.insert_many(new_docs)
        logger.info("Seeded %d pixels", len(new_docs))


async def seed_admin():
    """Seed admin ONCE if missing. Never overwrite existing hash so the
    password can be rotated in the secret store without the app restoring it.
    """
    existing = await db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})
    if existing:
        # Ensure admin flag stays true, but never touch the password hash.
        if not existing.get("is_admin"):
            await db.users.update_one(
                {"email": ADMIN_EMAIL},
                {"$set": {"is_admin": True}},
            )
        return
    hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await db.users.insert_one({
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": ADMIN_EMAIL,
        "name": "Admin",
        "picture": None,
        "coins": 99999,
        "pixels_owned": 0,
        "is_admin": True,
        "password_hash": hashed,
        "created_at": now_utc(),
    })
    logger.info("Seeded admin user %s", ADMIN_EMAIL)


async def ensure_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.user_sessions.create_index("user_id")
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
    await db.pixels.create_index("pixel_id", unique=True)
    await db.transactions.create_index("pixel_id")
    await db.transactions.create_index("buyer_id")
    await db.transactions.create_index("timestamp")
    await db.pixel_media.create_index("pixel_id")
    await db.pixel_media.create_index("media_id", unique=True)
    await db.payment_orders.create_index("order_id", unique=True)
    await db.payment_orders.create_index("user_id")


# ---------------- App / Router ----------------

app = FastAPI(title="PixelLand")
api = APIRouter(prefix="/api")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await seed_admin()
    await seed_pixels()


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


@api.get("/")
async def root():
    return {"app": "PixelLand", "status": "ok"}


# -------- Auth --------


@api.post("/auth/session", response_model=SessionOut)
async def auth_session(payload: GoogleSessionIn):
    """Exchange a session_token from Emergent for our app session."""
    token = payload.session_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="session_token required")
    # Verify with Emergent
    async with httpx.AsyncClient(timeout=15) as hc:
        resp = await hc.get(
            EMERGENT_SESSION_DATA_URL,
            headers={"X-Session-ID": token},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google session")
    data = resp.json()
    email = (data.get("email") or "").lower().strip()
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data.get("session_token") or token
    if not email:
        raise HTTPException(status_code=400, detail="Email missing from Google")

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": email,
            "name": name,
            "picture": picture,
            "coins": INITIAL_COINS,
            "pixels_owned": 0,
            "is_admin": False,
            "created_at": now_utc(),
        }
        await db.users.insert_one(user)
        user.pop("_id", None)
    else:
        # update picture/name on each login
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"name": name, "picture": picture}},
        )
        user["name"] = name
        user["picture"] = picture

    await _store_session(session_token, user["user_id"])
    return SessionOut(session_token=session_token, user=_user_to_out(user))


@api.post("/auth/admin-login", response_model=SessionOut)
async def admin_login(payload: AdminLoginIn):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(payload.password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session_token = f"adm_{uuid.uuid4().hex}"
    await _store_session(session_token, user["user_id"])
    return SessionOut(session_token=session_token, user=_user_to_out(user))


async def _store_session(session_token: str, user_id: str):
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {
            "$set": {
                "session_token": session_token,
                "user_id": user_id,
                "expires_at": now_utc() + timedelta(days=7),
                "created_at": now_utc(),
            }
        },
        upsert=True,
    )


@api.get("/auth/me", response_model=UserOut)
async def auth_me(user: dict = Depends(get_current_user)):
    return _user_to_out(user)


@api.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        await db.user_sessions.delete_one({"session_token": token})
    return {"ok": True}


# -------- Pixels --------


@api.get("/pixels", response_model=List[PixelOut])
async def list_pixels():
    pixels = await db.pixels.find({}, {"_id": 0}).sort([("y", 1), ("x", 1)]).to_list(length=TOTAL_PIXELS + 10)
    return [_pixel_to_out(p) for p in pixels]


@api.get("/pixels/{pixel_id}", response_model=PixelOut)
async def get_pixel(pixel_id: str):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    return _pixel_to_out(p)


@api.post("/pixels/{pixel_id}/buy", response_model=PixelOut)
async def buy_pixel(pixel_id: str, user: dict = Depends(get_current_user)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id"):
        raise HTTPException(status_code=409, detail="Pixel already owned")
    price = int(p["price"])
    # STEP 1: atomically deduct coins ONLY if balance is sufficient.
    coin_res = await db.users.update_one(
        {"user_id": user["user_id"], "coins": {"$gte": price}},
        {"$inc": {"coins": -price, "pixels_owned": 1}},
    )
    if coin_res.matched_count == 0:
        raise HTTPException(status_code=402, detail="Not enough Pixel Coins")
    # STEP 2: atomically claim the pixel. If it was taken between step 1 and 2, refund.
    now = now_utc()
    result = await db.pixels.update_one(
        {"pixel_id": pixel_id, "owner_id": None},
        {
            "$set": {
                "owner_id": user["user_id"],
                "owner_name": user.get("name") or user["email"],
                "purchased_at": now,
            }
        },
    )
    if result.matched_count == 0:
        # Refund - someone else claimed it first
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$inc": {"coins": price, "pixels_owned": -1}},
        )
        raise HTTPException(status_code=409, detail="Pixel already owned")
    await _record_transaction(
        pixel_id=pixel_id,
        kind="primary",
        seller_id=None,
        seller_name=None,
        buyer_id=user["user_id"],
        buyer_name=user.get("name") or user["email"],
        price=price,
        fee=0,
        seller_proceeds=0,
        ts=now,
    )
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


# -------- Marketplace (secondary) --------

MARKET_FEE_PCT = 10  # 10% goes to the house


async def _record_transaction(
    *,
    pixel_id: str,
    kind: str,
    seller_id: Optional[str],
    seller_name: Optional[str],
    buyer_id: str,
    buyer_name: str,
    price: int,
    fee: int,
    seller_proceeds: int,
    ts: datetime,
):
    await db.transactions.insert_one({
        "tx_id": f"tx_{uuid.uuid4().hex[:14]}",
        "pixel_id": pixel_id,
        "kind": kind,
        "seller_id": seller_id,
        "seller_name": seller_name,
        "buyer_id": buyer_id,
        "buyer_name": buyer_name,
        "price": price,
        "fee": fee,
        "seller_proceeds": seller_proceeds,
        "timestamp": ts,
    })


def _tx_to_out(t: dict) -> TransactionOut:
    ts = t.get("timestamp")
    if isinstance(ts, datetime):
        ts = _to_aware(ts).isoformat()
    return TransactionOut(
        tx_id=t["tx_id"],
        pixel_id=t["pixel_id"],
        kind=t["kind"],
        seller_id=t.get("seller_id"),
        seller_name=t.get("seller_name"),
        buyer_id=t["buyer_id"],
        buyer_name=t["buyer_name"],
        price=int(t["price"]),
        fee=int(t.get("fee") or 0),
        seller_proceeds=int(t.get("seller_proceeds") or 0),
        timestamp=ts or "",
    )


@api.post("/pixels/{pixel_id}/list", response_model=PixelOut)
async def list_for_sale(pixel_id: str, payload: ListPixelIn, user: dict = Depends(get_current_user)):
    if payload.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be > 0")
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your pixel")
    await db.pixels.update_one(
        {"pixel_id": pixel_id},
        {"$set": {"listed_price": int(payload.price)}},
    )
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


@api.delete("/pixels/{pixel_id}/list", response_model=PixelOut)
async def unlist(pixel_id: str, user: dict = Depends(get_current_user)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your pixel")
    await db.pixels.update_one(
        {"pixel_id": pixel_id},
        {"$set": {"listed_price": None}},
    )
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


@api.post("/pixels/{pixel_id}/buy-resale", response_model=PixelOut)
async def buy_resale(pixel_id: str, user: dict = Depends(get_current_user)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    listed_price = p.get("listed_price")
    if not listed_price or listed_price <= 0:
        raise HTTPException(status_code=409, detail="Pixel not listed")
    seller_id = p.get("owner_id")
    if not seller_id:
        raise HTTPException(status_code=409, detail="Pixel has no owner")
    if seller_id == user["user_id"]:
        raise HTTPException(status_code=409, detail="Cannot buy your own pixel")
    price = int(listed_price)
    fee = (price * MARKET_FEE_PCT) // 100
    seller_proceeds = price - fee
    now = now_utc()
    # STEP 1: atomically deduct buyer coins ONLY if they have enough.
    buyer_res = await db.users.update_one(
        {"user_id": user["user_id"], "coins": {"$gte": price}},
        {"$inc": {"coins": -price, "pixels_owned": 1}},
    )
    if buyer_res.matched_count == 0:
        raise HTTPException(status_code=402, detail="Not enough Pixel Coins")
    # STEP 2: atomic conditional swap on the listing
    result = await db.pixels.update_one(
        {"pixel_id": pixel_id, "owner_id": seller_id, "listed_price": listed_price},
        {
            "$set": {
                "owner_id": user["user_id"],
                "owner_name": user.get("name") or user["email"],
                "purchased_at": now,
                "listed_price": None,
            }
        },
    )
    if result.matched_count == 0:
        # Refund the buyer - the listing changed
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$inc": {"coins": price, "pixels_owned": -1}},
        )
        raise HTTPException(status_code=409, detail="Listing changed, please retry")
    # Credit the seller
    await db.users.update_one(
        {"user_id": seller_id},
        {"$inc": {"coins": seller_proceeds, "pixels_owned": -1}},
    )
    seller = await db.users.find_one({"user_id": seller_id}, {"_id": 0, "name": 1, "email": 1})
    await _record_transaction(
        pixel_id=pixel_id,
        kind="resale",
        seller_id=seller_id,
        seller_name=(seller or {}).get("name") or (seller or {}).get("email"),
        buyer_id=user["user_id"],
        buyer_name=user.get("name") or user["email"],
        price=price,
        fee=fee,
        seller_proceeds=seller_proceeds,
        ts=now,
    )
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


@api.get("/pixels/{pixel_id}/transactions", response_model=List[TransactionOut])
async def pixel_transactions(pixel_id: str):
    txs = await db.transactions.find({"pixel_id": pixel_id}, {"_id": 0}).sort([("timestamp", -1)]).to_list(length=200)
    return [_tx_to_out(t) for t in txs]


@api.get("/listings", response_model=List[PixelOut])
async def listings():
    items = await db.pixels.find(
        {"listed_price": {"$ne": None, "$gt": 0}},
        {"_id": 0},
    ).sort([("listed_price", 1)]).to_list(length=TOTAL_PIXELS)
    return [_pixel_to_out(p) for p in items]


# -------- Media Gallery (Cloudinary) --------


def _media_to_out(m: dict) -> MediaOut:
    ts = m.get("created_at")
    if isinstance(ts, datetime):
        ts = _to_aware(ts).isoformat()
    return MediaOut(
        media_id=m["media_id"],
        pixel_id=m["pixel_id"],
        kind=m["kind"],
        url=m["url"],
        thumbnail_url=m.get("thumbnail_url") or m["url"],
        bytes=int(m.get("bytes") or 0),
        mime_type=m.get("mime_type") or "",
        duration=m.get("duration"),
        width=m.get("width"),
        height=m.get("height"),
        created_at=ts or "",
    )


@api.get("/pixels/{pixel_id}/media", response_model=List[MediaOut])
async def list_media(pixel_id: str):
    items = await db.pixel_media.find({"pixel_id": pixel_id}, {"_id": 0}).sort([("created_at", -1)]).to_list(length=MAX_MEDIA_PER_PIXEL + 5)
    return [_media_to_out(m) for m in items]


@api.post("/pixels/{pixel_id}/media", response_model=MediaOut)
async def upload_media(
    pixel_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only the owner can add media")

    # Enforce max 20 per pixel
    count = await db.pixel_media.count_documents({"pixel_id": pixel_id})
    if count >= MAX_MEDIA_PER_PIXEL:
        raise HTTPException(status_code=409, detail=f"Limite atingido ({MAX_MEDIA_PER_PIXEL} arquivos)")

    mime = (file.content_type or "").lower()
    is_image = mime in ALLOWED_IMAGE_MIMES
    is_video = mime in ALLOWED_VIDEO_MIMES
    if not is_image and not is_video:
        raise HTTPException(status_code=415, detail=f"Formato não suportado: {mime}")

    # Copy to a tmp file so cloudinary SDK can stream it.
    suffix = Path(file.filename or "upload").suffix or (".jpg" if is_image else ".mp4")
    tmp_path: Optional[str] = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if is_image and total > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Imagem maior que 10 MB")
                if is_video and total > MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=413, detail="Vídeo maior que 200 MB")
                tmp.write(chunk)
            tmp_path = tmp.name

        folder = f"pixelland/pixel_{pixel_id}"
        try:
            if is_video:
                result = cloudinary.uploader.upload_large(
                    tmp_path,
                    resource_type="video",
                    folder=folder,
                    chunk_size=6_000_000,
                )
                thumbnail_url = (
                    f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}"
                    f"/video/upload/so_0/{result['public_id']}.jpg"
                )
                kind = "video"
            else:
                result = cloudinary.uploader.upload(
                    tmp_path,
                    resource_type="image",
                    folder=folder,
                )
                thumbnail_url = result["secure_url"]
                kind = "image"
        except Exception as e:
            logger.exception("Cloudinary upload failed")
            raise HTTPException(status_code=502, detail=f"Falha no upload: {e}")

        now = now_utc()
        doc = {
            "media_id": f"med_{uuid.uuid4().hex[:14]}",
            "pixel_id": pixel_id,
            "kind": kind,
            "url": result["secure_url"],
            "thumbnail_url": thumbnail_url,
            "public_id": result["public_id"],
            "resource_type": result.get("resource_type") or kind,
            "bytes": int(result.get("bytes") or total),
            "mime_type": mime,
            "duration": result.get("duration"),
            "width": result.get("width"),
            "height": result.get("height"),
            "uploaded_by": user["user_id"],
            "created_at": now,
        }
        await db.pixel_media.insert_one(doc)
        # Update pixel.gallery (kept for backward compatibility) with URL
        await db.pixels.update_one(
            {"pixel_id": pixel_id},
            {"$push": {"gallery": result["secure_url"]}},
        )
        doc.pop("_id", None)
        return _media_to_out(doc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@api.delete("/pixels/{pixel_id}/media/{media_id}")
async def delete_media(pixel_id: str, media_id: str, user: dict = Depends(get_current_user)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only the owner can delete media")
    m = await db.pixel_media.find_one({"media_id": media_id, "pixel_id": pixel_id}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Media not found")
    # Delete from Cloudinary
    try:
        cloudinary.uploader.destroy(
            m["public_id"],
            resource_type=m.get("resource_type") or m["kind"],
            invalidate=True,
        )
    except Exception:
        logger.exception("Cloudinary destroy failed (soft-continue)")
    await db.pixel_media.delete_one({"media_id": media_id})
    await db.pixels.update_one({"pixel_id": pixel_id}, {"$pull": {"gallery": m["url"]}})
    # If this media was used as the cover, reset the cover to default
    await db.pixels.update_one(
        {"pixel_id": pixel_id, "cover_media_id": media_id},
        {"$set": {
            "cover_media_id": None,
            "cover_type": "image",
            "cover_video": None,
            "cover_image": DEFAULT_COVER,
        }},
    )
    return {"ok": True}


# -------- Leaderboard --------


# --- AI helpers ---


async def _generate_description(name: str, x: int, y: int, hint: str = "") -> str:
    """One-shot creative description generation via Emergent LLM key (OpenAI)."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"desc_{uuid.uuid4().hex}",
        system_message=(
            "Você é um narrador cósmico do jogo PixelLand, um multiverso de terrenos digitais chamados 'universos'. "
            "Escreva descrições curtas (3–4 frases, máximo 350 caracteres), em PT-BR, evocativas e poéticas, "
            "com pitadas de ficção científica. Sempre trate o local como um 'universo' único. "
            "Nunca inclua emojis, listas, títulos ou aspas — retorne apenas o texto corrido."
        ),
    ).with_model(*AI_TEXT_MODEL)
    user_prompt = f"Universo chamado '{name or 'Sem nome'}' nas coordenadas X {x}, Y {y}."
    if hint:
        user_prompt += f" Estilo/tema desejado: {hint}."
    resp = await chat.send_message(UserMessage(text=user_prompt))
    return (resp or "").strip()


async def _generate_image_bytes(prompt: str) -> bytes:
    gen = OpenAIImageGeneration(api_key=EMERGENT_LLM_KEY)
    images = await gen.generate_images(
        prompt=prompt,
        model=AI_IMAGE_MODEL,
        number_of_images=1,
    )
    if not images:
        raise HTTPException(status_code=502, detail="Image generation returned no result")
    return images[0]


# --- AI endpoints ---


@api.post("/ai/generate-description", response_model=AiDescriptionOut)
async def ai_generate_description(
    payload: AiDescriptionIn, user: dict = Depends(get_current_user)
):
    """Free-form description generation — no pixel required, used by wizard + edit panel."""
    x = 0
    y = 0
    try:
        text = await _generate_description(payload.name or "", x, y, payload.hint or "")
    except Exception as e:
        logger.exception("LLM description failed")
        raise HTTPException(status_code=502, detail=f"AI text failed: {e}")
    return AiDescriptionOut(description=text[:500])


@api.post("/pixels/{pixel_id}/ai/description", response_model=AiDescriptionOut)
async def ai_pixel_description(
    pixel_id: str, payload: AiDescriptionIn, user: dict = Depends(get_current_user)
):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Not your pixel")
    try:
        text = await _generate_description(
            payload.name or p.get("name") or "",
            int(p["x"]),
            int(p["y"]),
            payload.hint or "",
        )
    except Exception as e:
        logger.exception("LLM description failed")
        raise HTTPException(status_code=502, detail=f"AI text failed: {e}")
    return AiDescriptionOut(description=text[:500])


@api.post("/pixels/{pixel_id}/ai/cover", response_model=PixelOut)
async def ai_pixel_cover(
    pixel_id: str, payload: AiCoverIn, user: dict = Depends(get_current_user)
):
    """Generate a cover image with OpenAI, upload to Cloudinary, save as a new
    media item in the pixel's gallery and set it as the pixel's cover."""
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Not your pixel")
    count = await db.pixel_media.count_documents({"pixel_id": pixel_id})
    if count >= MAX_MEDIA_PER_PIXEL:
        raise HTTPException(status_code=409, detail=f"Limite atingido ({MAX_MEDIA_PER_PIXEL} arquivos)")

    prompt = payload.prompt.strip()
    try:
        img_bytes = await _generate_image_bytes(prompt)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Image generation failed")
        raise HTTPException(status_code=502, detail=f"AI image failed: {e}")

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name
        folder = f"pixelland/pixel_{pixel_id}"
        try:
            result = cloudinary.uploader.upload(
                tmp_path,
                resource_type="image",
                folder=folder,
            )
        except Exception as e:
            logger.exception("Cloudinary upload failed for AI cover")
            raise HTTPException(status_code=502, detail=f"Cloudinary falhou: {e}")

        now = now_utc()
        media_id = f"med_{uuid.uuid4().hex[:14]}"
        media_doc = {
            "media_id": media_id,
            "pixel_id": pixel_id,
            "kind": "image",
            "url": result["secure_url"],
            "thumbnail_url": result["secure_url"],
            "public_id": result["public_id"],
            "resource_type": "image",
            "bytes": int(result.get("bytes") or len(img_bytes)),
            "mime_type": "image/png",
            "duration": None,
            "width": result.get("width"),
            "height": result.get("height"),
            "uploaded_by": user["user_id"],
            "ai_generated": True,
            "ai_prompt": prompt,
            "created_at": now,
        }
        await db.pixel_media.insert_one(media_doc)
        # Set as cover + backfill gallery for backward compatibility
        await db.pixels.update_one(
            {"pixel_id": pixel_id},
            {
                "$set": {
                    "cover_media_id": media_id,
                    "cover_type": "image",
                    "cover_video": None,
                    "cover_image": result["secure_url"],
                },
                "$push": {"gallery": result["secure_url"]},
            },
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


# -------- Leaderboard (real) --------


# --- PayPal helpers ---


async def _paypal_access_token() -> str:
    async with httpx.AsyncClient(timeout=15) as hc:
        r = await hc.post(
            f"{PAYPAL_BASE}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"PayPal auth failed: {r.text}")
    return r.json()["access_token"]


@api.get("/payments/bundles", response_model=List[CoinBundleOut])
async def list_bundles():
    return [
        CoinBundleOut(bundle_id=k, coins=v["coins"], price_usd=v["price_usd"], label=v["label"])
        for k, v in COIN_BUNDLES.items()
    ]


@api.post("/payments/create-order", response_model=CreateOrderOut)
async def create_order(payload: CreateOrderIn, user: dict = Depends(get_current_user)):
    bundle = COIN_BUNDLES.get(payload.bundle_id)
    if not bundle:
        raise HTTPException(status_code=400, detail="Invalid bundle_id")
    token = await _paypal_access_token()
    return_url = f"{PAYPAL_BASE.replace('api-m', 'www')}/checkoutnow"  # not actually used, we handle return via app deep link
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": payload.bundle_id,
            "description": bundle["label"],
            "amount": {"currency_code": "USD", "value": bundle["price_usd"]},
        }],
        "application_context": {
            "brand_name": "PixelLand",
            "user_action": "PAY_NOW",
            "return_url": "https://pixelland-mvp.preview.emergentagent.com/paypal-return",
            "cancel_url": "https://pixelland-mvp.preview.emergentagent.com/paypal-cancel",
        },
    }
    async with httpx.AsyncClient(timeout=20) as hc:
        r = await hc.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": f"pxl-{uuid.uuid4().hex}",
            },
            json=body,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"PayPal order failed: {r.text}")
    data = r.json()
    order_id = data["id"]
    approve = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
    if not approve:
        raise HTTPException(status_code=502, detail="PayPal did not return an approval link")
    # Persist an intent record (idempotency + audit)
    await db.payment_orders.insert_one({
        "order_id": order_id,
        "user_id": user["user_id"],
        "bundle_id": payload.bundle_id,
        "coins": bundle["coins"],
        "price_usd": bundle["price_usd"],
        "status": "CREATED",
        "credited": False,
        "created_at": now_utc(),
    })
    return CreateOrderOut(
        order_id=order_id,
        approve_url=approve,
        bundle_id=payload.bundle_id,
        coins=bundle["coins"],
        price_usd=bundle["price_usd"],
    )


@api.post("/payments/capture/{order_id}", response_model=CaptureOrderOut)
async def capture_order(order_id: str, user: dict = Depends(get_current_user)):
    record = await db.payment_orders.find_one({"order_id": order_id}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="Order not found")
    if record["user_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail="Order belongs to another user")
    # Idempotent short-circuit if already credited
    if record.get("credited"):
        me = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "coins": 1})
        return CaptureOrderOut(
            order_id=order_id,
            status=record.get("status") or "COMPLETED",
            credited=True,
            coins_added=0,
            new_balance=int((me or {}).get("coins", 0)),
        )
    token = await _paypal_access_token()
    async with httpx.AsyncClient(timeout=25) as hc:
        r = await hc.post(
            f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "PayPal-Request-Id": f"cap-{order_id}",  # idempotency key at PayPal too
            },
        )
    if r.status_code not in (200, 201):
        # If PayPal says already captured, we still want to reconcile
        await db.payment_orders.update_one({"order_id": order_id}, {"$set": {"last_error": r.text}})
        raise HTTPException(status_code=502, detail=f"PayPal capture failed: {r.text}")
    data = r.json()
    status = data.get("status") or ""
    if status != "COMPLETED":
        await db.payment_orders.update_one({"order_id": order_id}, {"$set": {"status": status}})
        return CaptureOrderOut(
            order_id=order_id,
            status=status,
            credited=False,
            coins_added=0,
            new_balance=int(user.get("coins", 0)),
        )
    # Verify PayPal actually captured the amount we asked for — defense against
    # a client tampering with the amount at PayPal's side.
    try:
        captured_amount = str(
            data["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"]
        )
    except (KeyError, IndexError, TypeError):
        captured_amount = ""
    if captured_amount and captured_amount != str(record["price_usd"]):
        await db.payment_orders.update_one(
            {"order_id": order_id},
            {"$set": {
                "status": "AMOUNT_MISMATCH",
                "captured_amount": captured_amount,
                "raw": data,
            }},
        )
        raise HTTPException(
            status_code=409,
            detail=f"Amount mismatch: got {captured_amount}, expected {record['price_usd']}",
        )
    # Credit coins atomically ONLY IF not credited yet
    coins = int(record["coins"])
    swap = await db.payment_orders.update_one(
        {"order_id": order_id, "credited": {"$ne": True}},
        {"$set": {"credited": True, "status": status, "captured_at": now_utc(), "raw": data}},
    )
    if swap.matched_count == 1:
        await db.users.update_one({"user_id": user["user_id"]}, {"$inc": {"coins": coins}})
    me = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0, "coins": 1})
    return CaptureOrderOut(
        order_id=order_id,
        status=status,
        credited=True,
        coins_added=coins if swap.matched_count == 1 else 0,
        new_balance=int((me or {}).get("coins", 0)),
    )


# -------- Leaderboard --------


@api.get("/leaderboard", response_model=List[LeaderboardEntry])
async def leaderboard():
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(length=1000)
    # Aggregate total spent from transactions (only as buyer)
    pipeline = [
        {"$group": {"_id": "$buyer_id", "spent": {"$sum": "$price"}}},
    ]
    agg = {}
    async for row in db.transactions.aggregate(pipeline):
        agg[row["_id"]] = int(row.get("spent") or 0)
    entries = []
    for u in users:
        entries.append(LeaderboardEntry(
            user_id=u["user_id"],
            name=u.get("name") or u.get("email") or "Pixel Owner",
            picture=u.get("picture"),
            pixels_owned=int(u.get("pixels_owned", 0)),
            total_spent=agg.get(u["user_id"], 0),
            is_admin=bool(u.get("is_admin", False)),
        ))
    entries.sort(key=lambda e: (e.pixels_owned, e.total_spent), reverse=True)
    return entries[:50]


@api.patch("/pixels/{pixel_id}", response_model=PixelOut)
async def update_pixel(pixel_id: str, payload: PixelUpdateIn, user: dict = Depends(get_current_user)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    if p.get("owner_id") != user["user_id"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Not your pixel")
    update = {k: v for k, v in payload.dict().items() if v is not None and k != "cover_media_id"}
    # Resolve cover from media library so the URL is always a stable Cloudinary
    # asset (never a hotlink-protected URL that renders as a black block).
    if payload.cover_media_id is not None:
        if payload.cover_media_id == "":
            update["cover_media_id"] = None
            update["cover_type"] = "image"
            update["cover_video"] = None
            update["cover_image"] = DEFAULT_COVER
        else:
            media = await db.pixel_media.find_one(
                {"media_id": payload.cover_media_id, "pixel_id": pixel_id},
                {"_id": 0},
            )
            if not media:
                raise HTTPException(status_code=404, detail="Cover media not found for this pixel")
            update["cover_media_id"] = payload.cover_media_id
            if media["kind"] == "video":
                update["cover_type"] = "video"
                update["cover_video"] = media["url"]
                update["cover_image"] = media.get("thumbnail_url") or media["url"]
            else:
                update["cover_type"] = "image"
                update["cover_video"] = None
                update["cover_image"] = media["url"]
    if update:
        await db.pixels.update_one({"pixel_id": pixel_id}, {"$set": update})
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


@api.get("/profile/pixels", response_model=List[PixelOut])
async def my_pixels(user: dict = Depends(get_current_user)):
    pixels = await db.pixels.find({"owner_id": user["user_id"]}, {"_id": 0}).to_list(length=TOTAL_PIXELS)
    return [_pixel_to_out(p) for p in pixels]


# -------- Admin --------


@api.get("/admin/users", response_model=List[UserOut])
async def admin_list_users(_: dict = Depends(get_current_admin)):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(length=1000)
    return [_user_to_out(u) for u in users]


@api.patch("/admin/users/{user_id}", response_model=UserOut)
async def admin_update_user(user_id: str, payload: AdminUserUpdateIn, _: dict = Depends(get_current_admin)):
    target = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if update:
        await db.users.update_one({"user_id": user_id}, {"$set": update})
    updated = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    return _user_to_out(updated)


@api.patch("/admin/pixels/{pixel_id}", response_model=PixelOut)
async def admin_update_pixel(pixel_id: str, payload: AdminPixelUpdateIn, _: dict = Depends(get_current_admin)):
    p = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pixel not found")
    update: dict = {}
    if payload.name is not None:
        update["name"] = payload.name
    if payload.description is not None:
        update["description"] = payload.description
    if payload.cover_image is not None:
        update["cover_image"] = payload.cover_image
    if payload.price is not None:
        update["price"] = int(payload.price)
    if payload.owner_id is not None:
        if payload.owner_id == "":
            # release ownership
            prev_owner = p.get("owner_id")
            if prev_owner:
                await db.users.update_one({"user_id": prev_owner}, {"$inc": {"pixels_owned": -1}})
            update["owner_id"] = None
            update["owner_name"] = None
            update["purchased_at"] = None
        else:
            new_owner = await db.users.find_one({"user_id": payload.owner_id}, {"_id": 0})
            if not new_owner:
                raise HTTPException(status_code=404, detail="Owner not found")
            prev_owner = p.get("owner_id")
            if prev_owner and prev_owner != payload.owner_id:
                await db.users.update_one({"user_id": prev_owner}, {"$inc": {"pixels_owned": -1}})
            if prev_owner != payload.owner_id:
                await db.users.update_one({"user_id": payload.owner_id}, {"$inc": {"pixels_owned": 1}})
            update["owner_id"] = payload.owner_id
            update["owner_name"] = new_owner.get("name") or new_owner.get("email")
            update["purchased_at"] = now_utc()
    if update:
        await db.pixels.update_one({"pixel_id": pixel_id}, {"$set": update})
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


@api.post("/admin/pixels/seed")
async def admin_reseed(_: dict = Depends(get_current_admin)):
    await seed_pixels()
    return {"ok": True, "total": await db.pixels.count_documents({})}


@api.post("/admin/reset-map")
async def admin_reset_map(_: dict = Depends(get_current_admin)):
    """Wipes all ownership, listings and customizations from the grid.
    Resets users.pixels_owned counter. Transactions are kept as historical log."""
    await db.pixels.update_many({}, {"$set": {
        "owner_id": None,
        "owner_name": None,
        "purchased_at": None,
        "listed_price": None,
        "gallery": [],
        "external_link": "",
        "theme_color": "#00E5FF",
    }})
    # Reset description+name back to defaults
    async for p in db.pixels.find({}, {"_id": 0, "x": 1, "y": 1, "pixel_id": 1}):
        await db.pixels.update_one(
            {"pixel_id": p["pixel_id"]},
            {"$set": {
                "name": f"Pixel ({p['x']},{p['y']})",
                "description": "An unclaimed digital territory awaiting a universe.",
                "cover_image": DEFAULT_COVER,
            }}
        )
    await db.users.update_many({}, {"$set": {"pixels_owned": 0}})
    return {"ok": True}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
