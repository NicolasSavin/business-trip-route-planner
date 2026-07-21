export type TransportType = "train" | "bus";
export type TransportClass =
  | "economy"
  | "coupe"
  | "platzkart"
  | "sleeper"
  | "seated"
  | "express";
export type RouteSegment = {
  id: string;
  origin: string;
  destination: string;
  transport_type: TransportType;
  number: string;
  departure_time: string;
  arrival_time: string;
  available_seats: number;
};
export type RouteOption = {
  id: string;
  origin: string;
  destination: string;
  segments: RouteSegment[];
  transfer_city: string | null;
  transfer_duration_minutes: number | null;
  total_duration_minutes: number;
  transfers_count: number;
  is_available_for_group: boolean;
};
export type RouteSearchResponse = { routes: RouteOption[] };
export type RouteSearchPayload = {
  origin: string;
  destination: string;
  departure_date: string;
  passengers: number;
  allowed_transport: TransportType[];
  max_transfers: number;
  minimum_transfer_minutes: number;
  preferred_classes?: TransportClass[];
  require_group_together?: boolean;
  allow_split_group?: boolean;
};
export type LastCheckStatus =
  | "never_checked"
  | "checking"
  | "routes_found"
  | "no_available_routes"
  | "failed";
export type SavedSearch = RouteSearchPayload & {
  id: string;
  title: string;
  monitoring_enabled: boolean;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
  last_check_status: LastCheckStatus;
  last_routes_count: number;
  last_available_routes_count: number;
  last_error: string | null;
};
export type SavedSearchCreatePayload = RouteSearchPayload & {
  title?: string;
  monitoring_enabled?: boolean;
};
export type SavedSearchUpdatePayload = Partial<SavedSearchCreatePayload>;
export type SavedSearchCheckResponse = {
  saved_search: SavedSearch;
  routes: RouteOption[];
};

export type MonitoringStatus = "success" | "failed" | "skipped";
export type MonitoringHistory = {
  id: string;
  saved_search_id: string;
  checked_at: string;
  duration_ms: number;
  routes_found: number;
  available_routes: number;
  best_score: number | null;
  status: MonitoringStatus;
  change_detected: boolean;
  summary: string;
  changes: string[];
  route_ids: string[];
  free_seats: number;
};
export type MonitoringResult = {
  saved_search_id: string;
  is_changed: boolean;
  changes: string[];
  summary: string;
  timestamp: string;
  history: MonitoringHistory;
};


export type NotificationType =
  | "new_route"
  | "seats_available"
  | "better_route"
  | "price_changed"
  | "monitoring_failed"
  | "monitoring_resumed";
export type NotificationSeverity = "info" | "success" | "warning" | "critical";
export type Notification = {
  id: string;
  created_at: string;
  saved_search_id: string;
  type: NotificationType;
  title: string;
  message: string;
  is_read: boolean;
  severity: NotificationSeverity;
  metadata: Record<string, unknown>;
};
