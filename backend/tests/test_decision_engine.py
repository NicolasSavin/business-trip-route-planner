from datetime import datetime, timedelta
from app.decision import DecisionEngine, DecisionService
from app.decision.models import AnalyzeRequest, CompareRequest
from app.models.routes import RouteOption, RouteSegment
from app.domain import TransportType


def seg(id, origin, dest, depart, minutes, seats=8):
    return RouteSegment(id=id, origin=origin, destination=dest, transport_type=TransportType.TRAIN, number=id, departure_time=depart, arrival_time=depart + timedelta(minutes=minutes), available_seats=seats)


def route(id="r1", transfers=0, seats=8, transfer_wait=None, duration=300, available=True):
    start = datetime(2026, 8, 10, 9)
    if transfers:
        first = seg(id+"a", "Москва", "Казань", start, 120, seats)
        second_depart = first.arrival_time + timedelta(minutes=transfer_wait or 60)
        second = seg(id+"b", "Казань", "Екатеринбург", second_depart, duration - 120 - (transfer_wait or 60), seats)
        segments = [first, second]
    else:
        segments = [seg(id+"a", "Москва", "Екатеринбург", start, duration, seats)]
    return RouteOption(id=id, origin="Москва", destination="Екатеринбург", segments=segments, transfer_city="Казань" if transfers else None, transfer_duration_minutes=transfer_wait if transfers else None, total_duration_minutes=duration, transfers_count=transfers, is_available_for_group=available)


def test_decision_engine_analyzes_explanation_and_rating():
    summary = DecisionEngine().analyze([route(duration=300)], passengers=6)[0]
    assert summary.rating > 80
    assert summary.explanation in {reason.message for reason in summary.advantages}
    assert any(reason.code == "available" for reason in summary.advantages)


def test_rule_evaluation_flags_short_transfer_risk():
    summary = DecisionEngine().analyze([route("r2", transfers=1, transfer_wait=20, duration=330)], passengers=2)[0]
    assert any(reason.code == "short_transfer" for reason in summary.warnings)
    assert any(reason.code == "miss_risk" for reason in summary.recommendations)


def test_long_wait_is_disadvantage():
    summary = DecisionEngine().analyze([route("r3", transfers=1, transfer_wait=240, duration=600)], passengers=2)[0]
    assert any(reason.code == "long_wait" for reason in summary.disadvantages)


def test_decision_service_returns_best_route_id():
    response = DecisionService().analyze(AnalyzeRequest(routes=[route("slow", duration=500), route("fast", duration=250)], passengers=2))
    assert response.best_route_id == "fast"


def test_compare_returns_winner_criteria_and_recommendation():
    response = DecisionService().compare(CompareRequest(left=route("slow", duration=500), right=route("fast", duration=250), passengers=2))
    assert response.winner_route_id == "fast"
    assert response.criteria
    assert response.differences
    assert response.recommendations[0].code == "choose_winner"
