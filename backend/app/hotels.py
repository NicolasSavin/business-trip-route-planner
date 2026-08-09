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


HOTEL_SEED_DATA = [
    (1, "У Моста", 3000, ""),
    (2, "Шайба", 3500, ""),
    (3, "Голландия", 3500, ""),
    (4, "Юмья", 4000, ""),
    (5, "900км, УЮТ - с Москвы правая сторона", 3900, ""),
    (6, "900 км на Москву правая сторона", 4000, ""),
    (7, "Милеш (Исаково)", 4000, ""),
    (8, "Причал (Мамадыш)", 3500, ""),
    (9, "Чибис (Мамадыш)", 3500, ""),
    (10, "Дубай", 4000, ""),
    (11, "Астория", 4000, ""),
    (12, "Кугеси Тракдом", 3500, ""),
    (13, "Соло (Пыра)", 4000, ""),
    (14, "Слобода", 3900, "+100 ₽ / 4000 ₽"),
    (15, "Воротынец", 4000, ""),
    (16, "Вертолет", 4000, ""),
    (17, "Глобус", 3500, ""),
    (18, "Львово", 3500, ""),
    (19, "ЯТь", 4000, ""),
    (20, "Уют (Ярослав)", 4000, ""),
    (21, "Вязники", 3500, ""),
    (22, "Вязники (Сытый Гость)", 3500, "+100 ₽"),
    (23, "Дубрава", 4000, ""),
    (24, "Ямская Слобода", 4000, "+100 ₽"),
    (25, "Коурково", 4000, ""),
    (26, "УЮТ (объездная Перми)", 4000, ""),
    (27, "59 регион (Очер)", 3500, ""),
    (28, "У Озера", 4000, ""),
    (29, "Барабинск (На Посту)", 4000, ""),
    (30, "Тюкалинск (Берлога)", 3500, ""),
    (31, "Караван (Омск)", 4500, ""),
    (32, "ИП Авагян 943 км (Омская обл)", 4500, ""),
    (33, "Ольга (Омская обл, 545 км.)", 4000, ""),
    (34, "Кунгур (Вираж)", 4000, ""),
    (35, "Дилижанс", 3500, ""),
    (36, "Аврора", 4000, ""),
    (37, "Синявино", 3500, ""),
    (38, "Заячья гора", 4000, ""),
    (39, "Заячья гора Любава", 3900, "+100 ₽ / 4000 ₽"),
    (40, "Курское", 4000, ""),
    (41, "Курское (солнечная горка)", 3600, ""),
    (42, "Изумрудный город", 4000, ""),
    (43, "Агрострой", 4000, ""),
    (44, "Эберс", 3500, ""),
    (45, "Итель", 3500, "+100 ₽ / 3600 ₽"),
    (46, "Орловский родник", 4000, ""),
    (47, "Терса", 4100, ""),
    (48, "Прага", 4100, ""),
    (49, "Тихий Дон", 4000, ""),
    (50, "Абацкая слобода", 4000, ""),
    (51, "Караван (Сызрань)", 4000, ""),
    (52, "Алекс", 4000, ""),
    (53, "Каспий", 4000, ""),
    (54, "Саквояж", 4000, ""),
    (55, "Юрья", 3500, ""),
    (56, "Йошкар-Ола", 4000, ""),
    (57, "Пермь", 4500, ""),
    (58, "Тейково", 4000, ""),
    (59, "Дивное место", 3500, ""),
    (60, "Коломна", 4500, ""),
    (61, "Муром", 4500, ""),
    (62, "Фемели", 4500, ""),
    (63, "320 км.", 3900, ""),
    (64, "Шахты (Дуэт)", 4500, ""),
    (65, "Бийск", 4500, ""),
    (66, "Новоалтайск", 4500, ""),
    (67, "Дзержинский (экодомик)", 4500, ""),
    (68, "Мурманск", 4500, ""),
    (69, "Дружинино", 4500, ""),
    (70, "Екатеринбург (отель Свердлова 27)", 5500, ""),
    (71, "Нижняя Тура", 4500, ""),
    (72, "Саратов", 4500, ""),
    (73, "Новосибирск", 4500, ""),
    (74, "Владимир", 4500, ""),
    (75, "Дивеево", 4500, ""),
    (76, "С-Посад (ИП Тимчук)", 4500, ""),
    (77, "С-Посад, УЮТ", 4700, ""),
    (78, "Волгоград", 4500, ""),
    (79, "Плесецк (ласточкино гнездо)", 4000, ""),
    (80, "Мирный", 4500, ""),
    (81, "Знаменск", 4500, ""),
    (82, "Северодвинск", 4500, ""),
    (83, "Москва", 5500, ""),
    (84, "С-Петербург", 5500, ""),
]


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
            "INSERT INTO hotels VALUES (?, ?, ?, NULL, '', '', '', '', '', ?)",
            HOTEL_SEED_DATA,
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
