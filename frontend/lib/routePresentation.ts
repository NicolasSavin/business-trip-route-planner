import type { CarriageAvailability, RouteOption, RouteSearchResponse, RouteSegment } from "./types";

function placesInCarriages(carriages: CarriageAvailability[] | undefined): number | null {
  if (!carriages?.length) return null;
  const counts = carriages
    .map((carriage) => carriage.available_places)
    .filter((count): count is number => typeof count === "number");
  return counts.length ? counts.reduce((total, count) => total + count, 0) : null;
}

export function availableSeatsForSegment(route: RouteOption, segment: RouteSegment): number | null {
  const availability = route.availability?.segment_results.find((item) => item.segment_id === segment.id);
  const carriageCount = placesInCarriages(segment.carriages) ?? placesInCarriages(availability?.carriages);
  const confirmedCount = availability?.available_seats;
  const candidates = [segment.available_seats, confirmedCount, carriageCount]
    .filter((count): count is number => typeof count === "number");
  return candidates.length ? Math.max(...candidates) : null;
}

export function minimumAvailableSeats(route: RouteOption): number | null {
  if (route.availability?.minimum_available_seats != null) {
    return route.availability.minimum_available_seats;
  }
  const counts = route.segments
    .map((segment) => availableSeatsForSegment(route, segment))
    .filter((count): count is number => count !== null);
  return counts.length ? Math.min(...counts) : null;
}

export function sortRoutesForPresentation(routes: RouteOption[]): RouteOption[] {
  return [...routes].sort((left, right) =>
    (left.rank ?? Number.MAX_SAFE_INTEGER) - (right.rank ?? Number.MAX_SAFE_INTEGER)
    || left.total_duration_minutes - right.total_duration_minutes
  );
}

export function selectedSeatEvidenceLabel(segment: RouteSegment): string {
  if (!segment.selected_places?.length) return "";
  return ` · вагон ${segment.selected_carriages?.join(", ")} · купе ${segment.selected_compartments?.join(", ")} · места ${segment.selected_places.join(", ")}`;
}

export function routesVisibleForStrictState(data: RouteSearchResponse, strictAvailability: boolean): RouteOption[] {
  if (!strictAvailability && data.routes.length === 0 && (data.partially_confirmed_routes?.length ?? 0) > 0) {
    return data.partially_confirmed_routes ?? [];
  }
  return data.routes;
}

export function hasHiddenUnconfirmedRoutes(data: RouteSearchResponse, strictAvailability: boolean): boolean {
  return strictAvailability && data.routes.length === 0 && (data.partially_confirmed_routes?.length ?? 0) > 0;
}

export function routeSearchNotice(data: RouteSearchResponse, strictAvailability: boolean): { kind: "api" | "empty"; text: string } {
  if (data.routes.length > 0 || (!strictAvailability && (data.partially_confirmed_routes?.length ?? 0) > 0)) {
    return { kind: "api", text: "Результаты получены из backend API." };
  }
  if (hasHiddenUnconfirmedRoutes(data, strictAvailability)) {
    return { kind: "api", text: "Расписания найдены, но наличие мест не подтверждено. Отключите “Только подтверждённые варианты”, чтобы посмотреть маршруты." };
  }
  return { kind: "empty", text: "Нет маршрутов: попробуйте другую дату, транспорт или пересадки." };
}
