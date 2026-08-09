import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field


HOTEL_NAMES = [
    "У Моста", "Амакс", "Аврора", "Азимут", "Алтай", "Ангара", "Астория", "Атриум",
    "Байкал", "Балтика", "Белые ночи", "Берёзка", "Бристоль", "Вега", "Виктория", "Волга",
    "Восток", "Гагарин", "Гранд", "Двина", "Европа", "Енисей", "Жемчужина", "Заря",
    "Звезда", "Золотое кольцо", "Империал", "Калининград", "Космос", "Кристалл", "Ладога", "Лотте",
    "Маринс Парк", "Маяк", "Меридиан", "Метрополь", "Москва", "Надежда", "Невский", "Октябрьская",
    "Олимп", "Онегин", "Орбита", "Паллада", "Парк Инн", "Плаза", "Полярная звезда", "Президент-Отель",
    "Премьер", "Рэдиссон", "Россия", "Русь", "Садко", "Салют", "Северная", "Сибирь",
    "Славянская", "Сокол", "Спутник", "Тайга", "Театральная", "Турист", "Урал", "Фрегат",
    "Центральная", "Чайка", "Шаляпин Палас", "Экватор", "Эрмитаж", "Юбилейная", "Яр", "Александровский сад",
    "Грин Парк", "Домино", "Купеческий двор", "Лесная", "Малахит", "Николаевский", "Панорама", "Ривьера",
    "Северное сияние", "Тихая гавань", "Форум", "Царский двор",
]
REPORT_AMOUNTS = [3000, 3500, 3600, 3900, 4000, 4100, 4500, 4700, 5500]


class Hotel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    report_amount: int
    actual_price: int | None = None
    city: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    photo_url: str = ""
    notes: str = ""


class HotelUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    report_amount: int = Field(gt=0)
    actual_price: int | None = Field(default=None, ge=0)
    city: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=100)
    website: str = Field(default="", max_length=500)
    photo_url: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=5000)


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionUser(BaseModel):
    username: str
    is_admin: bool


def database_path() -> Path:
    return Path(os.getenv("HOTELS_DATABASE", "data/hotels.sqlite3"))


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS hotels (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, report_amount INTEGER NOT NULL,
        actual_price INTEGER, city TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', photo_url TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT ''
    )""")
    if connection.execute("SELECT COUNT(*) FROM hotels").fetchone()[0] == 0:
        connection.executemany(
            "INSERT INTO hotels VALUES (?, ?, ?, NULL, '', '', '', '', '', '')",
            [(index, name, REPORT_AMOUNTS[(index - 1) % len(REPORT_AMOUNTS)]) for index, name in enumerate(HOTEL_NAMES, 1)],
        )
        connection.commit()
    return connection


def _secret() -> bytes:
    value = os.getenv("AUTH_SESSION_SECRET")
    if not value:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    return value.encode()


def _session(username: str, is_admin: bool) -> str:
    payload = json.dumps({"u": username, "a": is_admin, "exp": int(time.time()) + 86400}, separators=(",", ":"))
    encoded = payload.encode().hex()
    signature = hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def current_user(hotel_session: Annotated[str | None, Cookie()] = None) -> SessionUser:
    if not hotel_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        encoded, signature = hotel_session.split(".", 1)
        expected = hmac.new(_secret(), encoded.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(bytes.fromhex(encoded))
        if payload["exp"] < time.time():
            raise ValueError
        return SessionUser(username=payload["u"], is_admin=payload["a"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")


def administrator(user: Annotated[SessionUser, Depends(current_user)]) -> SessionUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


router = APIRouter(prefix="/api/v1", tags=["hotels"])


@router.post("/auth/login", response_model=SessionUser)
def login(credentials: LoginRequest, response: Response) -> SessionUser:
    admin = (os.getenv("HOTELS_ADMIN_USERNAME"), os.getenv("HOTELS_ADMIN_PASSWORD"))
    regular = (os.getenv("HOTELS_USER_USERNAME"), os.getenv("HOTELS_USER_PASSWORD"))
    if not all(admin + regular):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is not configured")
    is_admin = hmac.compare_digest(credentials.username, admin[0] or "") and hmac.compare_digest(credentials.password, admin[1] or "")
    is_regular = hmac.compare_digest(credentials.username, regular[0] or "") and hmac.compare_digest(credentials.password, regular[1] or "")
    if not (is_admin or is_regular):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    user = SessionUser(username=credentials.username, is_admin=is_admin)
    response.set_cookie("hotel_session", _session(user.username, user.is_admin), httponly=True, secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", samesite=os.getenv("COOKIE_SAMESITE", "lax"), max_age=86400, path="/")
    return user


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie("hotel_session", path="/")


@router.get("/auth/me", response_model=SessionUser)
def me(user: Annotated[SessionUser, Depends(current_user)]) -> SessionUser:
    return user


@router.get("/hotels", response_model=list[Hotel])
def list_hotels(user: Annotated[SessionUser, Depends(current_user)], search: str = "") -> list[sqlite3.Row]:
    del user
    with connect() as database:
        return [dict(row) for row in database.execute("SELECT * FROM hotels WHERE name LIKE ? ORDER BY name COLLATE NOCASE", (f"%{search}%",)).fetchall()]


@router.post("/hotels", response_model=Hotel, status_code=201)
def create_hotel(update: HotelUpdate, user: Annotated[SessionUser, Depends(administrator)]) -> sqlite3.Row:
    del user
    values = update.model_dump()
    with connect() as database:
        cursor = database.execute(
            "INSERT INTO hotels (name, report_amount, actual_price, city, address, phone, website, photo_url, notes) VALUES (:name, :report_amount, :actual_price, :city, :address, :phone, :website, :photo_url, :notes)", values,
        )
        database.commit()
        return dict(database.execute("SELECT * FROM hotels WHERE id = ?", (cursor.lastrowid,)).fetchone())


@router.put("/hotels/{hotel_id}", response_model=Hotel)
def update_hotel(hotel_id: int, update: HotelUpdate, user: Annotated[SessionUser, Depends(administrator)]) -> sqlite3.Row:
    del user
    values = update.model_dump()
    with connect() as database:
        cursor = database.execute(
            "UPDATE hotels SET name=:name, report_amount=:report_amount, actual_price=:actual_price, city=:city, address=:address, phone=:phone, website=:website, photo_url=:photo_url, notes=:notes WHERE id=:id",
            {**values, "id": hotel_id},
        )
        if cursor.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Hotel not found")
        database.commit()
        return dict(database.execute("SELECT * FROM hotels WHERE id = ?", (hotel_id,)).fetchone())


@router.delete("/hotels/{hotel_id}", status_code=204)
def delete_hotel(hotel_id: int, user: Annotated[SessionUser, Depends(administrator)]) -> None:
    del user
    with connect() as database:
        cursor = database.execute("DELETE FROM hotels WHERE id = ?", (hotel_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Hotel not found")
        database.commit()
