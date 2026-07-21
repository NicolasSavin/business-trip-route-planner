# RzdProvider

`RzdProvider` adds a ready-to-connect Russian Railways integration boundary without making requests to RZD websites, scraping HTML, bypassing protection, or using closed APIs. The current implementation is intentionally powered by `MockRzdClient`.

## Architecture

Package: `backend/app/providers/rzd`.

- `RzdProvider` implements the existing `TransportProvider` protocol and is consumed through `UnifiedTransportProvider`.
- `RzdClient` is a protocol that isolates data retrieval from provider logic.
- `MockRzdClient` returns deterministic, realistic train responses for development and tests.
- `RzdMapper` converts client DTOs into internal `TransportSegment` models used by the Route Engine.
- `RzdConfiguration` contains connection settings: `enabled`, `priority`, `timeout`, `base_url`, and `retry_count`.
- `RzdCapabilities` declares train support, availability support, and no realtime support for this stage.

## Client

`MockRzdClient` supports trains, train numbers, stations, dates, times, car types, seat counts, and prices. It does not perform network I/O.

A future real client must implement the same `RzdClient` protocol:

```python
class RealRzdClient:
    def search_trains(self, departure_date: date) -> list[RzdTrainOption]: ...
    def healthcheck(self) -> bool: ...
```

## Mapper

`RzdMapper` maps `RzdTrainOption` into `TransportSegment` with:

- provider `rzd`;
- carrier `РЖД`;
- train transport type;
- station codes and names;
- train number/name;
- total available seats and minimum price;
- metadata that marks the current source as `rzd_mock`.

## Registry and health

The default registry registers RZD as `enabled=false`. The provider appears in `/api/v1/providers` and `/api/v1/providers/health` with metadata `ready_to_connect=true` and status label `готов к подключению`.

## Limitations

This stage explicitly does not include:

- Selenium or Playwright;
- requests to RZD websites;
- HTML parsing or web scraping;
- protection bypass;
- closed/private APIs.

## Replacing the mock later

To connect a real source in the future:

1. Implement `RzdClient` in a new client class using an approved, documented data source.
2. Return `RzdTrainOption` DTOs from that client.
3. Inject the new client into `RzdProvider` without changing Route Engine, Monitoring Engine, search API, or mapper contracts.
4. Set `RZD_ENABLED=true` and configure `RZD_BASE_URL`, `RZD_TIMEOUT`, `RZD_RETRY_COUNT`, and `RZD_PRIORITY` as needed.
5. Add integration tests that mock the approved external boundary.
