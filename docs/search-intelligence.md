# Search Intelligence Layer

Search Intelligence Layer adds route quality understanding on top of provider-agnostic segment search. It is implemented in `backend/app/intelligence` and is intentionally split into independent services that can later be wired to real station, geo, transfer, and availability data.

## StationResolver

`StationResolver` expands a user query from a city or station name to the canonical city used by the route graph. For example, Moscow includes Kazansky, Leningradsky, Yaroslavsky, Vostochny, Kursky railway terminals and Salaryevo bus terminal. The route engine searches all stations in the resolved city instead of only one literal station.

## NearbyCityResolver

`NearbyCityResolver` provides ordered fallback cities for destinations with no route. Mock data currently includes Gelendzhik alternatives through Novorossiysk, Krasnodar, and Anapa. The route engine first searches the requested destination and only then tries nearby cities.

## TransferEngine

`TransferEngine` enriches transfers with a type (`walk`, `metro`, `bus`, `unknown`), estimated transfer duration, and validation warnings. It checks short transfers, long transfers, night transfers, station changes, city changes, and whether the wait is shorter than the estimated transfer time.

## ExplanationService

`ExplanationService` produces user-facing route explanations, warnings, and advantages. Examples include insufficient seats, transfers under the safe threshold, unavailable onward transport after arrival, station changes, city changes, direct-route advantages, maximum-seat advantages, fastest-route advantages, and routes that lost to another option by score.

## RouteComparator

`RouteComparator` ranks routes by delegating scoring to `ScoringService`, sorting the result, assigning ranks, and attaching explanations. The score considers total duration, transfer count, transfer wait, transfer type, station changes, city changes, time buffer, night transfers, and available seats.

## Real data readiness

All services are replaceable behind narrow interfaces: station resolution can be backed by a station registry, nearby cities by GIS data, transfer estimates by maps/GTFS, explanations by localized copy, and scoring by business rules or learning-to-rank without changing providers or API endpoints.
