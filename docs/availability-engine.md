# Availability Engine

Availability Engine is a separate backend subsystem in `backend/app/availability` that answers one question: can the requested employee group travel on an already found route with the available seats and service-class rules?

## TransportProvider vs AvailabilityProvider

- `TransportProvider` returns schedules and `TransportSegment` objects. It owns route-search input such as departure/arrival times, stations, carriers, transport type, and the coarse `available_seats` snapshot already present on a segment.
- `AvailabilityProvider` checks current availability for one concrete `TransportSegment` and an `AvailabilityPolicy`. It is intentionally not the same interface as `TransportProvider`, so future inventory integrations can change without affecting schedule providers.

## RouteEngine vs AvailabilityEngine

`RouteEngine` still builds candidate routes using the transport graph, transfer rules, scoring, and Search Intelligence. It then composes with `AvailabilityEngine` to attach availability details to each `RouteOption`.

`AvailabilityEngine` does not search routes, create transfers, score options, mutate `RouteOption`, or book tickets. It checks every segment through an `AvailabilityProvider`, aggregates per-segment results, computes the minimum seats across the route, and produces route-level reasons and warnings.

The API service preserves existing behavior by returning group-usable routes, while the route options now include an optional `availability` block for clients that want details.

## AvailabilityPolicy

`AvailabilityPolicy` contains:

- `passengers` — requested employee count;
- `preferred_classes` — acceptable `TransportClass` values;
- `require_same_class_for_all_segments` — when true, all checked segments must resolve to one class;
- `require_group_together` — when true, each segment must have seats for the whole group;
- `allow_split_group` — when true and the group is not required together, a segment can be acceptable with at least one seat;
- `minimum_seats_per_segment` — optional explicit threshold overriding the derived seat threshold.

## SegmentAvailability

`SegmentAvailability` describes one checked segment without duplicating `TransportSegment`:

- `segment_id`;
- `is_available`;
- `available_seats`;
- `requested_passengers`;
- `transport_class`;
- `checked_at`;
- `source`;
- `reason`;
- `warnings`;
- freshness metadata: `stale_after_seconds` and computed `is_stale`.

## RouteAvailability

`RouteAvailability` aggregates the route check:

- `is_available`;
- `requested_passengers`;
- `minimum_available_seats`;
- `checked_at`;
- `segment_results`;
- `reasons`;
- `warnings`;
- freshness metadata: `stale_after_seconds` and computed `is_stale`.

## Unknown and stale data

The engine does not create a cache or background refresh jobs. Providers return `checked_at` and may set `stale_after_seconds`; the engine marks the route stale when at least one segment result is stale. A mock override of `None` means availability data is unavailable and produces a clear unavailable reason.

## Future RzdAvailabilityProvider

A real RZD integration should implement only `AvailabilityProvider.check_segment(segment, policy)`. The provider would map `TransportSegment` metadata to external train/station identifiers, call the inventory endpoint, and return `SegmentAvailability` with RZD as `source`. Route-level aggregation remains in `AvailabilityEngine`, so the Route Engine and API contract do not need to change.

## No booking responsibility

Availability Engine verifies feasibility, but it does not reserve seats, store passenger documents, process payments, authenticate users, or run notifications. Booking requires separate transactional guarantees and provider-specific workflows that are outside this project stage.
