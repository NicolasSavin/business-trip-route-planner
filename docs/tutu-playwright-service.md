# Tutu Playwright Availability Service

## Architecture

Yandex Rasp remains the schedule and route source. The main FastAPI backend does **not** start Chromium. Instead, it calls an isolated `tutu-playwright-service` over HTTP to enrich at most `TUTU_MAX_JOURNEYS_TO_ENRICH` best railway journeys with real-seat availability evidence from the public tutu.ru UI.

The service exposes:

- `GET /health` — unauthenticated readiness check.
- `POST /api/v1/availability/check` — one railway segment availability check.
- `POST /api/v1/availability/check-journey` — multiple segment check.
- `POST /api/v1/debug/test-search` — safe diagnostic search.

POST endpoints require `X-Service-Token` when `SERVICE_API_TOKEN` is configured.

## What it checks

The enrichment response can include: matched train, available seats, carriage class, lower/upper berth suitability, same carriage, same compartment, carriage/place numbers, visible price and diagnostics. Yandex values such as `available_seats=999` are treated as placeholders, not real availability.

## Limitations and safety rules

The service uses only the public user interface of tutu.ru. It must not use private APIs, bypass authorization, solve CAPTCHA, log in, book tickets, pay, or hold seats. If the UI changes or the service is unavailable, the backend marks affected routes as unconfirmed instead of rejecting them.

## Environment variables

Service:

```env
TUTU_PLAYWRIGHT_ENABLED=false
TUTU_PLAYWRIGHT_HEADLESS=true
TUTU_PLAYWRIGHT_TIMEOUT_SECONDS=45
TUTU_PLAYWRIGHT_CONCURRENCY=1
TUTU_PLAYWRIGHT_CACHE_TTL_SECONDS=300
TUTU_PLAYWRIGHT_ARTIFACT_DIR=/tmp/tutu-playwright-artifacts
TUTU_PLAYWRIGHT_MOCK=true
SERVICE_API_TOKEN=
PORT=8000
```

Backend:

```env
TUTU_PLAYWRIGHT_SERVICE_URL=
TUTU_PLAYWRIGHT_SERVICE_TOKEN=
TUTU_PLAYWRIGHT_ENABLED=false
TUTU_MAX_JOURNEYS_TO_ENRICH=3
```

Production must keep `TUTU_PLAYWRIGHT_ENABLED=false` until `/health` and `/api/v1/debug/test-search` pass in the target environment.

## Local Windows run with Docker Desktop

1. Install Docker Desktop and enable WSL2 integration.
2. From the repository root, run:

```powershell
$env:SERVICE_API_TOKEN="local-dev-token"
docker compose up --build
```

3. Verify the service:

```powershell
curl http://localhost:8010/health
curl -X POST http://localhost:8010/api/v1/debug/test-search -H "Content-Type: application/json" -H "X-Service-Token: local-dev-token" -d '{"origin":"Москва","destination":"Санкт-Петербург","departure_date":"2026-08-10","train_number":"008С","departure_time":"2026-08-10T23:06:00+03:00","passengers":2,"preferred_classes":["coupe"],"berth_preference":"lower_only","require_same_carriage":true,"require_same_compartment":true,"maximum_compartments":1}'
```

## Deployment notes

Deploy the Playwright service as a separate Render service with the official Playwright image Dockerfile. Allocate it separately from the backend; recommended minimum is 1 GB RAM for a single headless Chromium worker, with `TUTU_PLAYWRIGHT_CONCURRENCY=1`.

Add the backend environment variables in Render only after the Playwright service health and debug checks succeed. Use a strong shared `SERVICE_API_TOKEN` and set the same value as `TUTU_PLAYWRIGHT_SERVICE_TOKEN` in the backend.

## Diagnostics

On provider errors, screenshots and HTML artifacts are written under `TUTU_PLAYWRIGHT_ARTIFACT_DIR`. These artifacts are for debugging visible UI state only and should not contain payment or authentication data because the service never logs in or purchases tickets.
