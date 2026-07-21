import type {
  RouteSearchPayload,
  RouteSearchResponse,
  SavedSearch,
  SavedSearchCheckResponse,
  SavedSearchCreatePayload,
  SavedSearchUpdatePayload,
  MonitoringHistory,
  MonitoringResult,
  Notification,
  RouteOption,
  DecisionAnalyzeResponse,
  DecisionCompareResponse,
} from "@/lib/types";

export function apiBaseUrl() {
  const hostname = process.env.NEXT_PUBLIC_API_HOSTNAME;
  return hostname ? `https://${hostname}` : "http://localhost:8000";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "Заявка на командировку не найдена"
        : "Backend недоступен",
    );
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function searchRoutes(payload: RouteSearchPayload) {
  return request<RouteSearchResponse>("/api/v1/routes/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
export function createSavedSearch(payload: SavedSearchCreatePayload) {
  return request<SavedSearch>("/api/v1/saved-searches", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
export function listSavedSearches() {
  return request<SavedSearch[]>("/api/v1/saved-searches");
}
export function getSavedSearch(id: string) {
  return request<SavedSearch>(`/api/v1/saved-searches/${id}`);
}
export function updateSavedSearch(
  id: string,
  payload: SavedSearchUpdatePayload,
) {
  return request<SavedSearch>(`/api/v1/saved-searches/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
export function deleteSavedSearch(id: string) {
  return request<void>(`/api/v1/saved-searches/${id}`, { method: "DELETE" });
}
export function checkSavedSearch(id: string) {
  return request<SavedSearchCheckResponse>(
    `/api/v1/saved-searches/${id}/check`,
    { method: "POST" },
  );
}

export function monitoringHistory(id: string) {
  return request<MonitoringHistory[]>(`/api/v1/monitoring/history/${id}`);
}
export function runMonitoring(id: string) {
  return request<MonitoringResult>(`/api/v1/monitoring/run/${id}`, { method: "POST" });
}
export function runAllMonitoring() {
  return request<MonitoringResult[]>("/api/v1/monitoring/run-all", { method: "POST" });
}


export function listNotifications() {
  return request<Notification[]>("/api/v1/notifications");
}
export function listUnreadNotifications() {
  return request<Notification[]>("/api/v1/notifications/unread");
}
export function markNotificationRead(id: string) {
  return request<Notification>(`/api/v1/notifications/${id}/read`, { method: "PATCH" });
}
export function markAllNotificationsRead() {
  return request<Notification[]>("/api/v1/notifications/read-all", { method: "PATCH" });
}
export function deleteNotification(id: string) {
  return request<void>(`/api/v1/notifications/${id}`, { method: "DELETE" });
}

export function analyzeRoutes(routes: RouteOption[], passengers: number) {
  return request<DecisionAnalyzeResponse>("/api/v1/decision/analyze", {
    method: "POST",
    body: JSON.stringify({ routes, passengers }),
  });
}
export function compareRoutes(left: RouteOption, right: RouteOption, passengers: number) {
  return request<DecisionCompareResponse>("/api/v1/decision/compare", {
    method: "POST",
    body: JSON.stringify({ left, right, passengers }),
  });
}
