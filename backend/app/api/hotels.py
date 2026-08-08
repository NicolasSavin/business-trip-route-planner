from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.hotels import HotelInput, LoginInput, admin_user, authenticate, current_user, get_repository, set_session_cookie

router = APIRouter(prefix="/api/hotels", tags=["hotels"])

@router.post("/auth/login")
def login(value: LoginInput, response: Response):
    user = authenticate(value.surname, value.password)
    if not user: raise HTTPException(status_code=401, detail="Неверная фамилия или пароль")
    set_session_cookie(response, user)
    return user

@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("hotels_session", path="/")

@router.get("/auth/me")
def me(user=Depends(current_user)):
    return {"surname": user["surname"], "is_admin": user["is_admin"]}

@router.get("")
def list_hotels(_=Depends(current_user)):
    return get_repository().list()

@router.post("", status_code=status.HTTP_201_CREATED)
def create_hotel(value: HotelInput, _=Depends(admin_user)):
    return get_repository().create(value)

@router.put("/{hotel_id}")
def update_hotel(hotel_id: int, value: HotelInput, _=Depends(admin_user)):
    hotel = get_repository().update(hotel_id, value)
    if not hotel: raise HTTPException(status_code=404, detail="Гостиница не найдена")
    return hotel

@router.delete("/{hotel_id}", status_code=204)
def delete_hotel(hotel_id: int, _=Depends(admin_user)):
    if not get_repository().delete(hotel_id): raise HTTPException(status_code=404, detail="Гостиница не найдена")
