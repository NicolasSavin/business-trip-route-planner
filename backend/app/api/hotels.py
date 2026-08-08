import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.hotels.repository import default_repository

router = APIRouter(prefix="/api/hotels", tags=["hotels"])
logger = logging.getLogger(__name__)
repository = default_repository()
COOKIE = "hotels_session"
EPHEMERAL_SESSION_SECRET = secrets.token_bytes(32)


class Login(BaseModel):
    surname: str
    password: str


class HotelInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    locality: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=500)
    photo_url: str = Field(default="", max_length=2000)
    report_amount: int = Field(ge=0, le=10_000_000)
    actual_price: int | None = Field(default=None, ge=0, le=10_000_000)
    notes: str = Field(default="", max_length=2000)


def users():
    try:
        raw = json.loads(os.getenv("HOTELS_USERS_JSON", "[]"))
    except json.JSONDecodeError:
        logger.error("HOTELS_USERS_JSON is invalid")
        return []
    # This known excluded record is rejected even if mistakenly configured.
    return [u for u in raw if not (str(u.get("surname", "")).strip().casefold() == "мельников" and str(u.get("password", "")).strip() == "2403")]


def secret():
    configured = os.getenv("HOTELS_SESSION_SECRET")
    return configured.encode() if configured else EPHEMERAL_SESSION_SECRET


def token(surname: str):
    payload = base64.urlsafe_b64encode(json.dumps({"s": surname, "e": int(time.time()) + 43200}).encode()).decode()
    return payload + "." + hmac.new(secret(), payload.encode(), hashlib.sha256).hexdigest()


def current_user(hotels_session: Annotated[str | None, Cookie()] = None):
    if not hotels_session or "." not in hotels_session: raise HTTPException(401, "Требуется вход")
    payload, signature = hotels_session.rsplit(".", 1)
    expected = hmac.new(secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected): raise HTTPException(401, "Недействительная сессия")
    try: data = json.loads(base64.urlsafe_b64decode(payload)); surname, expiry = data["s"], data["e"]
    except Exception: raise HTTPException(401, "Недействительная сессия")
    if expiry < time.time() or not any(str(u.get("surname", "")).strip().casefold() == surname.casefold() for u in users()):
        raise HTTPException(401, "Сессия истекла")
    admin = surname.casefold() == os.getenv("HOTELS_ADMIN_SURNAME", "").strip().casefold() and bool(os.getenv("HOTELS_ADMIN_SURNAME", "").strip())
    return {"surname": surname, "is_admin": admin}


def admin(user=Depends(current_user)):
    if not user["is_admin"]: raise HTTPException(403, "Недостаточно прав")
    return user


@router.post("/auth/login")
def login(body: Login, response: Response):
    surname, password = body.surname.strip(), body.password.strip()
    match = next((u for u in users() if str(u.get("surname", "")).strip().casefold() == surname.casefold() and hmac.compare_digest(str(u.get("password", "")).strip(), password)), None)
    if not match: raise HTTPException(401, "Неверная фамилия или пароль")
    canonical = str(match["surname"]).strip()
    response.set_cookie(COOKIE, token(canonical), httponly=True, secure=os.getenv("HOTELS_COOKIE_SECURE", "true").lower() == "true", samesite="lax", max_age=43200, path="/")
    return {"surname": canonical, "is_admin": canonical.casefold() == os.getenv("HOTELS_ADMIN_SURNAME", "").strip().casefold()}


@router.post("/auth/logout", status_code=204)
def logout(response: Response): response.delete_cookie(COOKIE, path="/")

@router.get("/auth/me")
def me(user=Depends(current_user)): return user

@router.get("")
def list_hotels(user=Depends(current_user)): return repository.list()

@router.post("", status_code=201)
def create_hotel(body: HotelInput, user=Depends(admin)): return repository.create(body.model_dump())

@router.put("/{hotel_id}")
def update_hotel(hotel_id: int, body: HotelInput, user=Depends(admin)):
    result = repository.update(hotel_id, body.model_dump())
    if result is None: raise HTTPException(404, "Гостиница не найдена")
    return result

@router.delete("/{hotel_id}", status_code=204)
def delete_hotel(hotel_id: int, user=Depends(admin)):
    if not repository.delete(hotel_id): raise HTTPException(404, "Гостиница не найдена")
