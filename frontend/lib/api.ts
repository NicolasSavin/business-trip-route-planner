import type {
  RouteSearchPayload,
  RouteSearchResponse,
  LocationSuggestResponse,
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

export class ApiError extends Error {
  status?: number;
  statusText?: string;
  url: string;
  responseBody?: string;
  cause?: unknown;

  constructor(
    message: string,
    options: {
      status?: number;
      statusText?: string;
      url: string;
      responseBody?: string;
      cause?: unknown;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.statusText = options.statusText;
    this.url = options.url;
    this.responseBody = options.responseBody;
    this.cause = options.cause;
  }
}

export function apiBaseUrl() {
  const hostname = process.env.NEXT_PUBLIC_API_HOSTNAME;
  return hostname ? `https://${hostname}` : "http://localhost:8000";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${apiBaseUrl()}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ApiError(message || "Network request failed", { url, cause: error });
  }

  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(
      response.status === 404 ? "Заявка на командировку не найдена" : response.statusText,
      {
        status: response.status,
        statusText: response.statusText,
        url: response.url || url,
        responseBody: text,
      },
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch (error) {
    throw new ApiError("Backend вернул некорректный JSON", {
      status: response.status,
      statusText: response.statusText,
      url: response.url || url,
      responseBody: text.slice(0, 2000),
      cause: error,
    });
  }
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

export function listProviders() {
  return request<import("@/lib/types").ProviderRegistration[]>("/api/v1/providers");
}
export function providersHealth() {
  return request<import("@/lib/types").ProviderRegistration[]>("/api/v1/providers/health");
}
export function enableProvider(id: string) {
  return request<import("@/lib/types").ProviderRegistration>(`/api/v1/providers/${id}/enable`, { method: "POST" });
}
export function disableProvider(id: string) {
  return request<import("@/lib/types").ProviderRegistration>(`/api/v1/providers/${id}/disable`, { method: "POST" });
}

export function suggestLocations(query: string, limit = 8, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return request<LocationSuggestResponse>(`/api/v1/locations/suggest?${params.toString()}`, { signal });
}

export function browserPing() {
  return request<import("@/lib/types").BrowserPingResponse>("/api/v1/browser/ping");
}
export function browserScreenshotUrl() {
  return `${apiBaseUrl()}/api/v1/browser/screenshot`;
}

export function testTutuSearch() {
  return request<import("@/lib/types").TutuDiagnosticsResponse>("/api/v1/providers/tutu/test");
}
