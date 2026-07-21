# Provider Registry

Unified Transport Provider is the single transport-source interface for Route Engine. The Route Engine asks `UnifiedTransportProvider` for segments and does not know whether they came from Mock, GTFS, or a future RZD/Bus provider.

## Registered provider metadata

Each provider is registered in `ProviderRegistry` with:

- `id` and `name`;
- `priority` (`HIGH=100`, `NORMAL=50`, `LOW=10`);
- `enabled` flag;
- health: `healthy`, `degraded`, or `offline`;
- capabilities: `supported_transport`, `supports_availability`, `supports_realtime`;
- runtime stats: `routes_found`, `last_checked_at`, `error`.

## Merge and deduplication

`UnifiedTransportProvider.get_segments()` calls enabled and healthy providers by priority. Each segment is normalized with its source provider in `segment.provider` and `metadata.source_provider`. Duplicate segments are removed by this key:

1. carrier id;
2. departure datetime;
3. origin station id;
4. destination station id;
5. vehicle number;
6. transport type.

The first segment wins, so higher-priority providers take precedence.

## Health

Successful calls mark a provider as `healthy` and update `routes_found` and `last_checked_at`. Failed calls do not stop the merge. A provider with no previous successful data becomes `offline`; a provider that had previous results becomes `degraded`.

## API

- `GET /api/v1/providers` — provider registry with capabilities and stats.
- `GET /api/v1/providers/health` — same registry view focused on health checks.
- `POST /api/v1/providers/{id}/enable` — enable provider.
- `POST /api/v1/providers/{id}/disable` — disable provider.

## Adding RzdProvider

Create `RzdProvider` with the existing `TransportProvider.get_segments(departure_date, allowed_transport)` interface, map external records to `TransportSegment`, and register it:

```python
registry.register(
    RzdProvider(...),
    id="rzd",
    name="RZD Provider",
    priority=ProviderPriority.HIGH,
    capabilities=ProviderCapabilities(
        supported_transport=[TransportType.TRAIN],
        supports_availability=True,
        supports_realtime=True,
    ),
)
```

No Route Engine changes are required.
