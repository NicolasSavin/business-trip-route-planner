# Availability Engine

`backend/app/availability` is an isolated subsystem for checking whether an already built `RouteOption` can be booked. It does not search routes and does not know how graph traversal works.

## Structure

- `AvailabilityProvider` defines `check_segment()` and `check_route()` for external inventory sources.
- `MockAvailabilityProvider` uses existing `TransportSegment.available_seats` values and optional overrides for demo and tests.
- `AvailabilityPolicy` describes booking constraints: whole group together, split group, coupe-only, or any class.
- `AvailabilityValidator` verifies segment coverage, transfer consistency, and total seats for the requested group.
- `AvailabilityEngine` coordinates provider checks, validation, and returns an `AvailabilityResult`.

## Scenarios covered by mocks

- enough seats on every segment;
- not enough seats on one segment;
- no seats on one segment;
- seats appeared through provider overrides.

## Route Engine integration

The Route Engine builds candidate routes and delegates all inventory decisions to `AvailabilityEngine`. It does not inspect how seats are checked. API route options include an `availability` object with per-segment availability, class, check time, source, and warnings.

## Connecting a real RZD API later

Add a provider implementing `AvailabilityProvider`:

```python
class RzdAvailabilityProvider:
    source = "rzd"

    def check_segment(self, segment, policy):
        # map TransportSegment metadata to RZD train/station IDs
        # call RZD inventory endpoint
        # convert response into SegmentAvailability
        ...

    def check_route(self, route, policy):
        # check every segment and aggregate into AvailabilityResult
        ...
```

Then inject it without changing route search:

```python
engine = RouteEngine(provider, availability_engine=AvailabilityEngine(RzdAvailabilityProvider()))
```
