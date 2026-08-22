from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.providers.rzd_availability.client import RZDClient
from app.providers.rzd_availability.exceptions import RZDAvailabilityError

router = APIRouter(prefix="/api/v1/seats", tags=["seats"])


def _evaluate(train, passengers: int) -> dict:
    by_coupe: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"lower": 0, "upper": 0, "any": 0})
    for seat in train.seats:
        if not seat.is_available:
            continue
        key = (seat.carriage_number or "?", seat.compartment_number or "?")
        if seat.compartment_number:
            by_coupe[key]["any"] += 1
            if seat.berth_position == "lower":
                by_coupe[key]["lower"] += 1
            elif seat.berth_position == "upper":
                by_coupe[key]["upper"] += 1
    confirmed_coupe = any(v["any"] >= passengers for v in by_coupe.values())
    confirmed_coupe_lower = any(v["lower"] >= passengers for v in by_coupe.values())
    lower = train.lower_seats
    return {
        "number": train.train_number,
        "available": train.available_seats,
        "lower": lower,
        "upper": train.upper_seats,
        "min_price": train.min_price,
        "same_coupe": True if confirmed_coupe else (None if not train.seats else False),
        "same_coupe_lower": True if confirmed_coupe_lower else (None if not train.seats else False),
        "lower_enough": None if lower is None else lower >= passengers,
        "ok_for_request": bool(
            confirmed_coupe_lower or (lower is not None and lower >= passengers and passengers == 1)
        ),
    }


@router.get("/rzd")
async def rzd_seats(
    origin: str = Query(..., min_length=1),
    destination: str = Query(..., min_length=1),
    departure_date: date = Query(..., alias="date"),
    passengers: int = Query(1, ge=1, le=9),
):
    try:
        result = await RZDClient().search(origin, destination, departure_date, passengers)
    except RZDAvailabilityError as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "trains": [],
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "error": str(exc), "error_type": type(exc).__name__, "trains": []},
        )
    trains = [_evaluate(train, passengers) for train in result.trains]
    return {
        "ok": True,
        "from": result.origin.name,
        "to": result.destination.name,
        "from_code": result.origin.code,
        "to_code": result.destination.code,
        "passengers": passengers,
        "trains": trains,
    }
