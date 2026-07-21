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
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

import bcrypt
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
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
    update = {k: v for k, v in payload.dict().items() if v is not None}
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
