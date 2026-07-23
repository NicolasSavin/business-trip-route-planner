from app.models.routes import RouteOption
from .models import DecisionPolicy, DecisionReason, DecisionReasonKind, DecisionSummary, ComparisonCriterion, CompareResponse

class DecisionEngine:
    def __init__(self, policy: DecisionPolicy | None = None):
        self.policy = policy or DecisionPolicy()

    def analyze(self, routes: list[RouteOption], passengers: int = 1) -> list[DecisionSummary]:
        if not routes:
            return []
        policy = self.policy.model_copy(update={"group_size": passengers})
        fastest = min(r.total_duration_minutes for r in routes)
        max_seats = max(self._min_seats(r) for r in routes)
        raw = [self._analyze_one(r, fastest, max_seats, policy) for r in routes]
        return sorted(raw, key=lambda s: (-s.rating, s.total_duration_minutes, s.transfers_count, -s.minimum_available_seats))

    def compare(self, left: RouteOption, right: RouteOption, passengers: int = 1) -> CompareResponse:
        left_summary, right_summary = self.analyze([left, right], passengers=passengers)
        by_id = {left_summary.route_id: left_summary, right_summary.route_id: right_summary}
        left_summary, right_summary = by_id[left.id], by_id[right.id]
        winner = None
        if left_summary.rating != right_summary.rating:
            winner = left.id if left_summary.rating > right_summary.rating else right.id
        criteria = [
            self._criterion("Общий рейтинг", left.id, right.id, left_summary.rating, right_summary.rating, "баллов"),
            self._criterion("Время поездки", left.id, right.id, left.total_duration_minutes, right.total_duration_minutes, "мин", lower_wins=True),
            self._criterion("Ожидание пересадок", left.id, right.id, left_summary.transfer_wait_minutes, right_summary.transfer_wait_minutes, "мин", lower_wins=True),
            self._criterion("Количество пересадок", left.id, right.id, left.transfers_count, right.transfers_count, "", lower_wins=True),
            self._criterion("Минимальный запас мест", left.id, right.id, left_summary.minimum_available_seats, right_summary.minimum_available_seats, "мест"),
        ]
        rec = [DecisionReason(code="choose_winner" if winner else "routes_equal", kind=DecisionReasonKind.RECOMMENDATION, message=("Рекомендуется маршрут-победитель: выше детерминированный рейтинг." if winner else "Маршруты равноценны по детерминированному рейтингу."))]
        diffs = [c.difference for c in criteria if c.difference != "без различий"]
        return CompareResponse(winner_route_id=winner, criteria=criteria, differences=diffs, recommendations=rec, left_summary=left_summary, right_summary=right_summary)

    def _analyze_one(self, route, fastest, max_seats, policy):
        adv=[]; dis=[]; warn=[]; rec=[]; score=50.0
        min_seats=self._min_seats(route); wait=self._wait(route)
        availability_status = getattr(getattr(route, "availability", None), "status", None) or ("confirmed" if route.is_available_for_group is True else "unavailable" if route.is_available_for_group is False else "unknown")
        status_text = str(availability_status).lower()
        proven_unavailable = "unavailable" in status_text or any(s.available_seats is not None and s.available_seats < policy.group_size for s in route.segments)
        if route.is_available_for_group and min_seats >= policy.group_size and str(availability_status) in {"confirmed", "AvailabilityStatus.CONFIRMED"}:
            score += policy.availability_bonus; adv.append(self._r("available", "Подходит для группы из %d человек." % policy.group_size, "advantage", policy.availability_bonus))
        elif proven_unavailable:
            penalty = policy.unavailable_penalty
            score -= penalty; warn.append(self._r("unavailable", "Недостаточно мест.", "warning", -penalty))
        else:
            penalty = policy.unavailable_penalty * 0.25
            score -= penalty; warn.append(self._r("unknown_availability", "Наличие мест не подтверждено.", "warning", -penalty))
        if route.total_duration_minutes == fastest:
            score += policy.fastest_bonus; adv.append(self._r("fastest", "Самый быстрый маршрут.", "advantage", policy.fastest_bonus))
        if ("partially_confirmed" in status_text or "unknown" in status_text or "unconfirmed" in status_text) and not proven_unavailable:
            score -= 8; warn.append(self._r("unknown_availability", "Наличие мест требует проверки, но это не равно отсутствию мест.", "warning", -8))
        if route.transfers_count == 0:
            score += policy.direct_bonus; adv.append(self._r("direct", "Маршрут без пересадок.", "advantage", policy.direct_bonus))
        else:
            score -= route.transfers_count * policy.transfer_penalty; dis.append(self._r("transfers", f"Есть пересадки: {route.transfers_count}.", "disadvantage", -policy.transfer_penalty))
        if min_seats == max_seats or min_seats >= policy.good_seat_reserve:
            score += policy.seat_reserve_bonus; adv.append(self._r("seat_reserve", "Максимальный запас свободных мест.", "advantage", policy.seat_reserve_bonus))
        if route.transfer_duration_minutes is not None and route.transfer_duration_minutes < policy.short_transfer_minutes:
            score -= policy.short_transfer_penalty; warn.append(self._r("short_transfer", "Очень короткая пересадка.", "warning", -policy.short_transfer_penalty)); rec.append(self._r("miss_risk", "Большой риск пропустить следующий поезд.", "recommendation"))
        if wait >= policy.long_wait_minutes:
            score -= policy.long_wait_penalty; dis.append(self._r("long_wait", "Длительное ожидание между сегментами.", "disadvantage", -policy.long_wait_penalty))
        if route.total_duration_minutes <= fastest * 1.15 and route.transfers_count <= 1 and route.is_available_for_group:
            score += policy.balanced_bonus; adv.append(self._r("balanced", "Лучший баланс времени и количества пересадок.", "advantage", policy.balanced_bonus))
        providers = {segment.provider for segment in route.segments if getattr(segment, "provider", None)}
        if "rzd" in providers or route.provider == "rzd":
            adv.append(self._r("source_rzd", "Источник: РЖД", "advantage"))
        for w in route.warnings:
            warn.append(self._r("route_warning", w, "warning"))
        rating=max(0,min(100,round(score)))
        explanation = self._explanation(adv, warn, dis)
        return DecisionSummary(route_id=route.id,total_duration_minutes=route.total_duration_minutes,transfer_wait_minutes=wait,transfers_count=route.transfers_count,has_available_seats=route.is_available_for_group is True,minimum_available_seats=min_seats,score=round(score,2),rating=rating,explanation=explanation,advantages=adv,disadvantages=dis,warnings=warn,recommendations=rec)

    def _wait(self, route): return route.transfer_duration_minutes or 0
    def _min_seats(self, route): return min([s.available_seats for s in route.segments if s.available_seats is not None], default=0)
    def _r(self, code, message, kind, weight=0): return DecisionReason(code=code,message=message,kind=DecisionReasonKind(kind),weight=weight)
    def _explanation(self, adv, warn, dis):
        if adv: return adv[0].message
        if warn: return warn[0].message
        if dis: return dis[0].message
        return "Маршрут оценён по прозрачным правилам."
    def _criterion(self, name, left_id, right_id, left, right, unit, lower_wins=False):
        winner = None if left == right else (left_id if (left < right if lower_wins else left > right) else right_id)
        suffix = f" {unit}" if unit else ""
        return ComparisonCriterion(name=name,left=f"{left}{suffix}",right=f"{right}{suffix}",winner=winner,difference=("без различий" if left == right else f"разница {abs(left-right)}{suffix}"))
