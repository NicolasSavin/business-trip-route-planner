"""Protected hotel directory, authentication, and durable JSON repository."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("uvicorn.error")
COOKIE_NAME = "hotels_session"
SESSION_SECONDS = 60 * 60 * 12
SEED_PATH = Path(__file__).with_name("data") / "hotels.json"


class HotelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    locality: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=500)
    photo_url: str = Field(default="", max_length=2000)
    report_amount: int = Field(ge=0, le=100_000_000)
    actual_price: int | None = Field(default=None, ge=0, le=100_000_000)
    notes: str = Field(default="", max_length=3000)

    @field_validator("photo_url")
    @classmethod
    def safe_photo_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("URL фотографии должен начинаться с http:// или https://")
        return value


class LoginInput(BaseModel):
    surname: str = Field(min_length=1, max_length=100)
    password: str = Field(pattern=r"^\d{4}$")


def _production() -> bool:
    return os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower() in {"production", "prod"}


def session_secret() -> str:
    value = os.getenv("HOTELS_SESSION_SECRET", "")
    if not value and _production():
        raise RuntimeError("HOTELS_SESSION_SECRET is required in production")
    return value or "development-only-hotels-secret"


def normalized(value: str) -> str:
    return value.strip().casefold()


def users() -> list[dict[str, str]]:
    try:
        raw = json.loads(os.getenv("HOTELS_USERS_JSON", "[]"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("HOTELS_USERS_JSON must be valid JSON") from exc
    if not isinstance(raw, list):
        raise RuntimeError("HOTELS_USERS_JSON must be a JSON array")
    return [item for item in raw if isinstance(item, dict)]


def authenticate(surname: str, password: str) -> dict[str, Any] | None:
    wanted = normalized(surname)
    # These two specifically excluded records are denied even if mistakenly supplied.
    if wanted == normalized("Мельников") and password == "2403":
        return None
    if wanted == normalized("Фурин"):
        return None
    for item in users():
        stored_surname = str(item.get("surname", "")).strip()
        stored_password = str(item.get("password", ""))
        if normalized(stored_surname) == wanted and secrets.compare_digest(stored_password, password):
            admin = normalized(os.getenv("HOTELS_ADMIN_SURNAME", "")) == wanted
            return {"surname": stored_surname, "is_admin": admin}
    return None


def sign_session(user: dict[str, Any], now: int | None = None) -> str:
    payload = {"surname": user["surname"], "is_admin": bool(user["is_admin"]), "exp": (now or int(time.time())) + SESSION_SECONDS}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode().hex()
    signature = hmac.new(session_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_session(token: str | None) -> dict[str, Any]:
    try:
        encoded, supplied = (token or "").split(".", 1)
        expected = hmac.new(session_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        payload = json.loads(bytes.fromhex(encoded))
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError
        # Re-check the allowlist on every request so access revocation is immediate.
        if not any(normalized(str(u.get("surname", ""))) == normalized(payload["surname"]) for u in users()):
            raise ValueError
        payload["is_admin"] = normalized(os.getenv("HOTELS_ADMIN_SURNAME", "")) == normalized(payload["surname"])
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Требуется авторизация")


def current_user(hotels_session: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    return read_session(hotels_session)


def admin_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user


class HotelRepository:
    """Thread-safe JSON repository with atomic same-filesystem replacement."""

    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("HOTELS_DATA_PATH")
        self.path = Path(configured or tempfile.gettempdir() + "/business-trip-hotels.json")
        self._lock = threading.RLock()
        if not configured or str(self.path).startswith("/tmp/"):
            logger.warning("HOTELS_DATA_PATH is ephemeral; hotel edits are not persistent")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write(json.loads(SEED_PATH.read_text(encoding="utf-8")))

    def _atomic_write(self, hotels: list[dict[str, Any]]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(hotels, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(self.path.read_text(encoding="utf-8"))

    def create(self, value: HotelInput) -> dict[str, Any]:
        with self._lock:
            hotels = self.list()
            hotel = {"id": max((h["id"] for h in hotels), default=0) + 1, **value.model_dump()}
            hotels.append(hotel); self._atomic_write(hotels)
            return hotel

    def update(self, hotel_id: int, value: HotelInput) -> dict[str, Any] | None:
        with self._lock:
            hotels = self.list()
            for index, hotel in enumerate(hotels):
                if hotel["id"] == hotel_id:
                    hotels[index] = {"id": hotel_id, **value.model_dump()}; self._atomic_write(hotels)
                    return hotels[index]
            return None

    def delete(self, hotel_id: int) -> bool:
        with self._lock:
            hotels = self.list(); remaining = [h for h in hotels if h["id"] != hotel_id]
            if len(remaining) == len(hotels): return False
            self._atomic_write(remaining); return True


repository: HotelRepository | None = None


def get_repository() -> HotelRepository:
    global repository
    expected = Path(os.getenv("HOTELS_DATA_PATH", tempfile.gettempdir() + "/business-trip-hotels.json"))
    if repository is None or repository.path != expected:
        repository = HotelRepository(expected)
    return repository


def set_session_cookie(response: Response, user: dict[str, Any]) -> None:
    response.set_cookie(COOKIE_NAME, sign_session(user), max_age=SESSION_SECONDS, httponly=True,
                        secure=_production(), samesite="lax", path="/")
