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
from pydantic import BaseModel, Field
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

ADMIN_EMAIL = "admin@pixelland.com"
ADMIN_PASSWORD = "Apollo2122@×+>×>adm00140"

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


class SessionOut(BaseModel):
    session_token: str
    user: UserOut


class PixelOut(BaseModel):
    pixel_id: str
    x: int
    y: int
    price: int
    name: str
    description: Optional[str] = ""
    cover_image: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    purchased_at: Optional[str] = None


class PixelUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None


class AdminPixelUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    price: Optional[int] = None
    owner_id: Optional[str] = None  # set to "" to clear ownership


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
    return UserOut(
        user_id=u["user_id"],
        email=u["email"],
        name=u.get("name") or "",
        picture=u.get("picture"),
        coins=int(u.get("coins", 0)),
        pixels_owned=int(u.get("pixels_owned", 0)),
        is_admin=bool(u.get("is_admin", False)),
    )


def _pixel_to_out(p: dict) -> PixelOut:
    purchased_at = p.get("purchased_at")
    if isinstance(purchased_at, datetime):
        purchased_at = _to_aware(purchased_at).isoformat()
    return PixelOut(
        pixel_id=p["pixel_id"],
        x=int(p["x"]),
        y=int(p["y"]),
        price=int(p["price"]),
        name=p.get("name") or "",
        description=p.get("description") or "",
        cover_image=p.get("cover_image") or DEFAULT_COVER,
        owner_id=p.get("owner_id"),
        owner_name=p.get("owner_name"),
        purchased_at=purchased_at,
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
    existing = await db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})
    hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    if existing:
        # always re-sync the admin password (idempotent and aligns with current ADMIN_PASSWORD)
        await db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"password_hash": hashed, "is_admin": True, "name": existing.get("name") or "Admin"}},
        )
        return
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
    if user.get("coins", 0) < price:
        raise HTTPException(status_code=402, detail="Not enough Pixel Coins")
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
        # Lost the race - someone else just bought it
        raise HTTPException(status_code=409, detail="Pixel already owned")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$inc": {"coins": -price, "pixels_owned": 1}},
    )
    updated = await db.pixels.find_one({"pixel_id": pixel_id}, {"_id": 0})
    return _pixel_to_out(updated)


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


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
