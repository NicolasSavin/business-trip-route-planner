import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, searchRoutes } from "./api";
import type { RouteOption, RouteSearchPayload, RouteSearchResponse } from "./types";
import { buildRouteSearchPayload, type RouteFormState } from "./locationPayload";
import { hasHiddenUnconfirmedRoutes, routeSearchNotice, routesVisibleForStrictState } from "./routePresentation";

const payload: RouteSearchPayload = {
  origin: "Москва",
  destination: "Санкт-Петербург",
  departure_date: "2026-08-10",
  passengers: 2,
  allowed_transport: ["train"],
  max_transfers: 1,
  minimum_transfer_minutes: 45,
  maximum_transfer_minutes: 360,
  strict_availability: false,
  seat_preferences: {
    preferred_classes: [],
    berth_preference: "any",
    require_same_compartment: false,
    require_same_carriage: true,
    allow_split_group: false,
    maximum_compartments: null,
    strict_preferences: true,
  },
};

function mockFetch(handler: (url: string, init?: RequestInit) => Promise<Response>) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = ((url: string | URL | Request, init?: RequestInit) =>
    handler(String(url), init)) as typeof fetch;
  return () => {
    globalThis.fetch = originalFetch;
  };
}

test("searchRoutes returns successful 200 JSON", async () => {
  const restore = mockFetch(async () =>
    new Response(JSON.stringify({ routes: [] }), { status: 200 }),
  );
  try {
    assert.deepEqual(await searchRoutes(payload), { routes: [] });
  } finally {
    restore();
  }
});

test("searchRoutes exposes 422 JSON detail", async () => {
  const body = JSON.stringify({ detail: [{ loc: ["body", "passengers"], msg: "Input should be greater than or equal to 1" }] });
  const restore = mockFetch(async () =>
    new Response(body, { status: 422, statusText: "Unprocessable Entity" }),
  );
  try {
    await assert.rejects(searchRoutes(payload), (error) => {
      assert(error instanceof ApiError);
      assert.equal(error.status, 422);
      assert.equal(error.responseBody, body);
      return true;
    });
  } finally {
    restore();
  }
});

test("searchRoutes exposes 500 response body", async () => {
  const restore = mockFetch(async () =>
    new Response("Internal Server Error", { status: 500, statusText: "Internal Server Error" }),
  );
  try {
    await assert.rejects(searchRoutes(payload), (error) => {
      assert(error instanceof ApiError);
      assert.equal(error.status, 500);
      assert.equal(error.responseBody, "Internal Server Error");
      return true;
    });
  } finally {
    restore();
  }
});

test("searchRoutes reports invalid JSON and keeps response preview", async () => {
  const invalidJson = "not-json".repeat(400);
  const restore = mockFetch(async () => new Response(invalidJson, { status: 200 }));
  try {
    await assert.rejects(searchRoutes(payload), (error) => {
      assert(error instanceof ApiError);
      assert.equal(error.message, "Backend вернул некорректный JSON");
      assert.equal(error.responseBody, invalidJson.slice(0, 2000));
      return true;
    });
  } finally {
    restore();
  }
});

test("searchRoutes preserves network failure message", async () => {
  const restore = mockFetch(async () => {
    throw new TypeError("Failed to fetch");
  });
  try {
    await assert.rejects(searchRoutes(payload), (error) => {
      assert(error instanceof ApiError);
      assert.equal(error.status, undefined);
      assert.equal(error.message, "Failed to fetch");
      return true;
    });
  } finally {
    restore();
  }
});


const formState: RouteFormState = {
  origin: "Санкт-Петербург (train/bus)",
  destination: "Москва",
  originLocation: {
    id: "city:c2",
    provider_code: "c2",
    type: "city",
    title: "Санкт-Петербург",
    displayLabel: "Санкт-Петербург (train/bus)",
  },
  destinationLocation: {
    id: "city:c213",
    provider_code: "c213",
    type: "city",
    title: "Москва",
    displayLabel: "Москва (train/bus)",
  },
  departure_date: "2026-08-10",
  passengers: 2,
  transport: "both",
  max_transfers: 1,
  minimum_transfer_minutes: 45,
  maximum_transfer_minutes: 360,
  strict_availability: false,
  lower_only: false,
  same_compartment: false,
};

test("buildRouteSearchPayload sends selected title instead of display label", () => {
  const actual = buildRouteSearchPayload(formState);
  assert.equal(actual.origin, "Санкт-Петербург");
  assert.notEqual(actual.origin, "Санкт-Петербург (train/bus)");
});

test("buildRouteSearchPayload sends provider code separately", () => {
  const actual = buildRouteSearchPayload(formState);
  assert.equal(actual.origin_provider_code, "c2");
  assert.equal(actual.destination_provider_code, "c213");
  assert.equal(actual.origin_location_id, "city:c2");
  assert.equal(actual.destination_location_id, "city:c213");
});

test("buildRouteSearchPayload strips UI suffix fallback when no selected location", () => {
  const actual = buildRouteSearchPayload({
    ...formState,
    originLocation: null,
    origin: "Санкт-Петербург (поезд/автобус)",
  });
  assert.equal(actual.origin, "Санкт-Петербург");
  assert.equal(actual.origin_provider_code, null);
});

const partialRoute: RouteOption = {
  id: "route-partial",
  origin: "Москва",
  destination: "Санкт-Петербург",
  segments: [
    {
      id: "seg-partial",
      origin: "Москва",
      destination: "Санкт-Петербург",
      transport_type: "train",
      number: "001А",
      departure_time: "2026-08-10T10:00:00Z",
      arrival_time: "2026-08-10T14:00:00Z",
      available_seats: null,
      availability_status: "unconfirmed",
    },
  ],
  transfer_city: null,
  transfer_duration_minutes: null,
  total_duration_minutes: 240,
  transfers_count: 0,
  is_available_for_group: null,
};

test("strict empty response with partial routes surfaces unconfirmed state instead of empty routes", () => {
  const response: RouteSearchResponse = { routes: [], partially_confirmed_routes: [partialRoute] };
  assert.equal(hasHiddenUnconfirmedRoutes(response, true), true);
  assert.equal(routeSearchNotice(response, true).text, "Расписания найдены, но наличие мест не подтверждено. Отключите “Только подтверждённые варианты”, чтобы посмотреть маршруты.");
  assert.notEqual(routeSearchNotice(response, true).text, "Нет маршрутов: попробуйте другую дату, транспорт или пересадки.");
});

test("turning strict availability off reuses already loaded partial routes", () => {
  const response: RouteSearchResponse = { routes: [], partially_confirmed_routes: [partialRoute] };
  assert.deepEqual(routesVisibleForStrictState(response, false), [partialRoute]);
});
