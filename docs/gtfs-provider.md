# GTFS provider

`GTFSProvider` adds a provider-agnostic transport data source that reads a local General Transit Feed Specification directory and exposes the same `TransportProvider.get_segments()` contract as the mock provider.

## New classes

- `GTFSProvider` (`backend/app/providers/gtfs/provider.py`) implements `TransportProvider` and returns `TransportSegment` objects for a requested date and transport filter.
- `GTFSLoader` (`backend/app/providers/gtfs/loader.py`) validates and reads GTFS text files from a directory.
- `GTFSParser` (`backend/app/providers/gtfs/parser.py`) parses GTFS CSV files into internal feed models and creates route segments for active services.
- `GTFSTransportSegmentMapper` (`backend/app/providers/gtfs/mapper.py`) converts a pair of consecutive GTFS stop times into one `TransportSegment`.
- Internal GTFS dataclasses in `backend/app/providers/gtfs/models.py` represent stops, routes, trips, stop times, calendars, calendar date exceptions, and the parsed feed.

## Supported GTFS files

Required files:

- `stops.txt`
- `routes.txt`
- `trips.txt`
- `stop_times.txt`
- `calendar.txt`

Optional files:

- `calendar_dates.txt`

The parser supports GTFS times above `24:00:00`; these arrivals/departures are mapped to the next service day as GTFS expects.

## GTFS to TransportSegment mapping

For each active `trip_id` on the requested date, `GTFSParser` sorts `stop_times.txt` rows by `stop_sequence`. Every consecutive stop pair becomes a separate `TransportSegment`:

1. `trips.txt.route_id` selects a route from `routes.txt`.
2. `stop_times.txt.stop_id` selects origin and destination stops from `stops.txt`.
3. `calendar.txt` and `calendar_dates.txt` decide whether the trip's `service_id` runs on the requested date.
4. `route_type` maps to domain transport type:
   - rail route types (`2` and common extended train route types) become `TransportType.TRAIN`;
   - other supported examples, including GTFS bus type `3`, become `TransportType.BUS`.
5. `arrival_time` and `departure_time` become absolute datetimes on the requested service date.
6. The generated segment uses provider `gtfs`, route short/long name as `vehicle_number`, stop IDs as station IDs, and GTFS IDs in metadata.

`city_name` or `stop_city` in `stops.txt` is used as the domain city name when present. If neither column is present, `stop_name` is used as a safe fallback.

## Connecting the provider

Instantiate the provider with a path to a GTFS directory and pass it to `RouteEngine` or any service expecting `TransportProvider`:

```python
from app.engine import RouteEngine
from app.providers.gtfs import GTFSProvider

provider = GTFSProvider("examples/gtfs")
engine = RouteEngine(provider)
```

`RouteEngine` still calls only `provider.get_segments(departure_date, allowed_transport)`, so it works the same way with `MockTransportProvider` and `GTFSProvider`.

## Example dataset

A small training feed is included in `examples/gtfs`. It contains one rail route from Moscow to Ekaterinburg through Kazan and one bus route from Moscow to Nizhny Novgorod through Vladimir. The dataset is intentionally small and synthetic to avoid size and licensing constraints.

## Tests

Unit tests in `backend/tests/test_gtfs_provider.py` cover:

- GTFS file loading and missing required files;
- parsing internal GTFS models;
- mapping consecutive stop times into `TransportSegment` objects;
- transport type filtering;
- `calendar_dates.txt` service removal and addition;
- `RouteEngine` compatibility with `GTFSProvider`.
