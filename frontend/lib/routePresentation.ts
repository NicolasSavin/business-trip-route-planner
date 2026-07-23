import type { RouteOption, RouteSearchResponse } from "./types";

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
