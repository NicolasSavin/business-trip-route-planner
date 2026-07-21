# Trip Decision Engine

Trip Decision Engine is a deterministic rules layer that analyzes `RouteOption` objects already returned by Route Engine. It does not search routes, mutate Route Engine behavior, call AI, or generate free-form LLM text.

## Architecture

- `DecisionEngine` evaluates route metrics and rules.
- `DecisionPolicy` stores thresholds and weights.
- `DecisionReason` is a typed, explainable rule result.
- `DecisionSummary` is the per-route user-facing analysis.
- `DecisionService` wraps the engine for API handlers.
- `/api/v1/decision/analyze` accepts existing route options and returns summaries.
- `/api/v1/decision/compare` accepts two route options and returns a deterministic comparison.

## Metrics

For every route the engine calculates:

- total trip time from `RouteOption.total_duration_minutes`;
- transfer waiting time from `transfer_duration_minutes`;
- number of transfers from `transfers_count`;
- seat availability from `is_available_for_group`;
- minimum seat reserve across segments;
- a bounded rating from 0 to 100;
- advantages, disadvantages, warnings, and recommendations.

## Rule set

Positive rules add weight: group availability, fastest route, direct route, large seat reserve, and balanced time/transfer count. Negative rules subtract weight: unavailable seats, transfers, short transfer windows, and long waiting times.

Messages are fixed templates, for example:

- `Самый быстрый маршрут.`
- `Лучший баланс времени и количества пересадок.`
- `Подходит для группы из N человек.`
- `Очень короткая пересадка.`
- `Большой риск пропустить следующий поезд.`
- `Длительное ожидание между сегментами.`

## Scoring algorithm

1. Start from a neutral score of 50.
2. Calculate fastest duration and maximum minimum-seat reserve within the analyzed set.
3. Apply policy weights for each route.
4. Clamp the final rating to the 0..100 range.
5. Sort summaries by rating descending, then duration ascending, transfers ascending, and seat reserve descending.

## Comparison algorithm

The compare endpoint analyzes the two routes with the same policy and returns:

- winner route id, or `null` for a tie;
- criterion rows for rating, duration, transfer waiting, transfer count, and minimum seats;
- textual differences generated from deterministic templates;
- recommendation to choose the winner or treat routes as equivalent.

## Future ML replacement

A future ML model can replace only the weight calculation behind `DecisionEngine`, while preserving the public API contracts and `DecisionReason` audit trail. The safe migration path is to keep deterministic fallback rules, log feature vectors and outcomes, train a model offline, then expose model factors as reason codes so explanations remain auditable.
