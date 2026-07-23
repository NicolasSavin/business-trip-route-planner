"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowDown,
  ArrowLeftRight,
  BadgeCheck,
  Bell,
  Bus,
  CalendarDays,
  Clock3,
  Loader2,
  MapPinned,
  Milestone,
  Route,
  Sparkles,
  TrainFront,
  UsersRound,
  Trash2,
  WifiOff,
} from "lucide-react";
import { demoResponse } from "@/lib/demoData";
import { LocationAutocomplete } from "@/components/LocationAutocomplete";
import { buildRouteSearchPayload, type SelectedLocation } from "@/lib/locationPayload";
import {
  checkSavedSearch,
  createSavedSearch,
  deleteSavedSearch,
  listSavedSearches,
  deleteNotification,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  monitoringHistory,
  runAllMonitoring,
  runMonitoring,
  searchRoutes,
  analyzeRoutes,
  compareRoutes,
  updateSavedSearch,
  ApiError,
  apiBaseUrl,
} from "@/lib/api";
import type { DecisionCompareResponse, DecisionSummary, MonitoringHistory, Notification, RouteOption, RouteSearchPayload, RouteSearchResponse, SavedSearch, TransportType } from "@/lib/types";
import { hasHiddenUnconfirmedRoutes, routeSearchNotice, routesVisibleForStrictState } from "@/lib/routePresentation";

const transportLabels: Record<TransportType, string> = {
  train: "Поезд",
  bus: "Автобус",
};
const transportIcons: Record<TransportType, typeof TrainFront> = {
  train: TrainFront,
  bus: Bus,
};

type NoticeKind = "demo" | "api" | "empty" | "error" | "success";
type ViewMode = "search" | "requests";
type FormState = {
  origin: string;
  destination: string;
  originLocation: SelectedLocation;
  destinationLocation: SelectedLocation;
  departure_date: string;
  passengers: number;
  transport: "both" | TransportType;
  max_transfers: number;
  minimum_transfer_minutes: number;
  maximum_transfer_minutes: number;
  strict_availability: boolean;
  lower_only: boolean;
  same_compartment: boolean;
};

const initialForm: FormState = {
  origin: "Москва",
  destination: "Санкт-Петербург",
  originLocation: { id: "city:c213", provider_code: "c213", type: "city", title: "Москва", displayLabel: "Москва" },
  destinationLocation: { id: "city:c2", provider_code: "c2", type: "city", title: "Санкт-Петербург", displayLabel: "Санкт-Петербург" },
  departure_date: "2026-08-10",
  passengers: 2,
  transport: "both",
  max_transfers: 1,
  minimum_transfer_minutes: 45,
  maximum_transfer_minutes: 360,
  strict_availability: true,
  lower_only: true,
  same_compartment: true,
};

function minutesLabel(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function routeLabel(route: RouteOption, index: number) {
  if (index === 0) return "Оптимальный";
  if (route.transfers_count === 0) return "Без пересадок";
  if (
    route.segments.some((segment) => segment.transport_type === "train") &&
    route.segments.some((segment) => segment.transport_type === "bus")
  )
    return "Поезд + автобус";
  return "Самый быстрый";
}

function minSeats(route: RouteOption) {
  const knownSeats = route.segments.map((segment) => segment.available_seats).filter((value): value is number => value !== null);
  return knownSeats.length ? Math.min(...knownSeats) : null;
}

function seatCountLabel(value: number | null) {
  return value === null ? "не проверено" : String(value);
}

function totalSeats(route: RouteOption) {
  const knownSeats = route.segments.map((segment) => segment.available_seats).filter((value): value is number => value !== null);
  return knownSeats.length ? knownSeats.reduce((sum, value) => sum + value, 0) : null;
}

function availabilityBadge(route: RouteOption) {
  const statuses = route.segments.map((segment) => segment.availability_status);
  if (statuses.includes("provider_error")) {
    return { className: "bg-rose-50 text-rose-700", text: "Проверка временно недоступна" };
  }
  if (statuses.includes("unconfirmed") || statuses.includes("unknown") || statuses.includes("partially_confirmed")) {
    return { className: "bg-amber-50 text-amber-700", text: "Наличие мест не подтверждено" };
  }
  if (statuses.includes("confirmed")) {
    return { className: "bg-emerald-50 text-emerald-700", text: "Наличие мест подтверждено" };
  }
  if (route.is_available_for_group === true) {
    return { className: "bg-emerald-50 text-emerald-700", text: "Доступно для группы" };
  }
  if (route.is_available_for_group === false) {
    return { className: "bg-rose-50 text-rose-700", text: "Недостаточно мест" };
  }
  return { className: "bg-amber-50 text-amber-700", text: "Наличие мест не подтверждено" };
}

function TransportIllustration() {
  return (
    <div className="relative hidden min-h-[320px] overflow-hidden rounded-[2rem] border border-white/70 bg-gradient-to-br from-white to-sky-50 p-8 shadow-card lg:block">
      <div className="absolute -right-14 -top-14 h-44 w-44 rounded-full bg-aqua/20 blur-2xl" />
      <div className="absolute -bottom-20 left-10 h-56 w-56 rounded-full bg-brand/10 blur-2xl" />
      <svg
        viewBox="0 0 420 280"
        className="relative h-full w-full"
        role="img"
        aria-label="Иллюстрация транспорта"
      >
        <path
          d="M44 208 C112 120, 190 248, 284 132 S374 90, 388 64"
          fill="none"
          stroke="#d9e4f2"
          strokeWidth="14"
          strokeLinecap="round"
        />
        <path
          d="M44 208 C112 120, 190 248, 284 132 S374 90, 388 64"
          fill="none"
          stroke="#0f7bff"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray="10 14"
        />
        <rect x="72" y="72" width="154" height="70" rx="24" fill="#111827" />
        <rect x="96" y="92" width="36" height="22" rx="7" fill="#dff5ff" />
        <rect x="144" y="92" width="54" height="22" rx="7" fill="#dff5ff" />
        <circle cx="112" cy="148" r="13" fill="#12b7b5" />
        <circle cx="186" cy="148" r="13" fill="#12b7b5" />
        <rect x="242" y="154" width="112" height="54" rx="18" fill="#0f7bff" />
        <rect x="262" y="170" width="28" height="16" rx="5" fill="#eaf7ff" />
        <rect x="300" y="170" width="28" height="16" rx="5" fill="#eaf7ff" />
        <circle cx="270" cy="212" r="10" fill="#111827" />
        <circle cx="326" cy="212" r="10" fill="#111827" />
        <circle cx="44" cy="208" r="10" fill="#12b7b5" />
        <circle cx="388" cy="64" r="10" fill="#0f7bff" />
      </svg>
    </div>
  );
}

export default function Home() {
  const [formState, setFormState] = useState<FormState>(initialForm);
  const [routes, setRoutes] = useState<RouteOption[]>(demoResponse.routes);
  const [lastRouteResponse, setLastRouteResponse] = useState<RouteSearchResponse | null>(null);
  const [apiDiagnostics, setApiDiagnostics] = useState<ApiDiagnostics | null>(null);
  const [tutuEnrichmentWarning, setTutuEnrichmentWarning] = useState(false);
  const [notice, setNotice] = useState<{ kind: NoticeKind; text: string }>({
    kind: "demo",
    text: "Используются демонстрационные данные. Backend будет опрошен при поиске.",
  });
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("search");
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [requestsNotice, setRequestsNotice] = useState(
    "Загрузка заявок ещё не выполнялась.",
  );
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [openedSearch, setOpenedSearch] = useState<SavedSearch | null>(null);
  const [checkedRoutes, setCheckedRoutes] = useState<RouteOption[]>([]);
  const [historyBySearch, setHistoryBySearch] = useState<Record<string, MonitoringHistory[]>>({});
  const [runningAll, setRunningAll] = useState(false);
  const [lastPayload, setLastPayload] = useState(buildPayload(initialForm));
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [decisionByRoute, setDecisionByRoute] = useState<Record<string, DecisionSummary>>({});
  const [selectedDecision, setSelectedDecision] = useState<DecisionSummary | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<DecisionCompareResponse | null>(null);
  const unreadNotifications = notifications.filter((item) => !item.is_read).length;
  const sortedRoutes = useMemo(
    () =>
      [...routes].sort(
        (a, b) => a.total_duration_minutes - b.total_duration_minutes,
      ),
    [routes],
  );

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setFormState((current) => ({ ...current, [key]: value }));
  }
  function buildPayloadFromForm() {
    return buildPayload(formState);
  }
  function swapCities() {
    setFormState((current) => ({
      ...current,
      origin: current.destination,
      destination: current.origin,
      originLocation: current.destinationLocation,
      destinationLocation: current.originLocation,
    }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setNotice({
      kind: "api",
      text: "Loading: подбираем оптимальные маршруты и проверяем наличие мест.",
    });
    const payload = buildPayloadFromForm();
    try {
      const data = await searchRoutes(payload);
      setLastPayload(payload);
      setLastRouteResponse(data);
      setRoutes(routesVisibleForStrictState(data, payload.strict_availability ?? true));
      setDecisionByRoute({});
      setCompareIds([]);
      setComparison(null);
      setApiDiagnostics(null);
      setTutuEnrichmentWarning(Boolean(data.provider_errors?.tutu_playwright || data.search_summary?.provider_errors?.tutu_playwright));
      setNotice(routeSearchNotice(data, payload.strict_availability ?? true));
    } catch (error) {
      console.error("Route search failed", error);
      setApiDiagnostics(buildApiDiagnostics(error, "/api/v1/routes/search"));
      setNotice({
        kind: "error",
        text: routeSearchErrorMessage(error),
      });
    } finally {
      setLoading(false);
    }
  }


  function disableStrictAvailabilityWithLoadedRoutes() {
    if (lastRouteResponse?.partially_confirmed_routes?.length && routes.length === 0) {
      setRoutes(lastRouteResponse.partially_confirmed_routes);
      setDecisionByRoute({});
      setCompareIds([]);
      setComparison(null);
      setNotice({ kind: "api", text: "Показаны маршруты с неподтверждённым наличием мест без повторного запроса." });
    }
  }

  function showUnconfirmedRoutes() {
    if (!lastRouteResponse?.partially_confirmed_routes?.length) return;
    setFormState((current) => ({ ...current, strict_availability: false }));
    disableStrictAvailabilityWithLoadedRoutes();
  }

  async function explainRoute(route: RouteOption) {
    const cached = decisionByRoute[route.id];
    if (cached) {
      setSelectedDecision(cached);
      return;
    }
    try {
      const result = await analyzeRoutes(routes, lastPayload.passengers);
      const next = Object.fromEntries(result.summaries.map((item) => [item.route_id, item]));
      setDecisionByRoute(next);
      setSelectedDecision(next[route.id] ?? null);
    } catch (error) {
      console.error("Route analysis failed", error);
      const fallback = localDecision(route, lastPayload.passengers);
      setSelectedDecision(fallback);
    }
  }

  function toggleCompareRoute(id: string) {
    setCompareIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id].slice(-2));
    setComparison(null);
  }

  async function runCompare() {
    const picked = compareIds.map((id) => routes.find((route) => route.id === id)).filter(Boolean) as RouteOption[];
    if (picked.length !== 2) return;
    try {
      setComparison(await compareRoutes(picked[0], picked[1], lastPayload.passengers));
    } catch (error) {
      console.error("Route comparison failed", error);
      setComparison(localCompare(picked[0], picked[1], lastPayload.passengers));
    }
  }

  async function saveCurrentSearch() {
    const title =
      window.prompt(
        "Название заявки на командировку",
        `${formState.origin} → ${formState.destination}`,
      ) || undefined;
    try {
      const saved = await createSavedSearch({ ...lastPayload, title });
      setSavedSearches((current) => [
        saved,
        ...current.filter((item) => item.id !== saved.id),
      ]);
      setNotice({ kind: "success", text: "Заявка сохранена." });
    } catch (error) {
      console.error("Save search failed", error);
      setNotice({
        kind: "error",
        text: "Не удалось сохранить заявку: функция требует работающий backend.",
      });
    }
  }

  async function loadSavedSearches() {
    setRequestsLoading(true);
    try {
      const items = await listSavedSearches();
      setSavedSearches(items);
      setRequestsNotice(
        items.length
          ? "Заявки загружены."
          : "Заявок ещё нет. Сохраните поиск маршрута как заявку.",
      );
    } catch (error) {
      console.error("Load saved searches failed", error);
      setRequestsNotice(
        "Backend недоступен: сохранённые заявки требуют работающий сервер.",
      );
    } finally {
      setRequestsLoading(false);
    }
  }

  useEffect(() => {
    void loadNotifications();
  }, []);

  useEffect(() => {
    if (viewMode === "requests") void loadSavedSearches();
  }, [viewMode]);

  async function loadNotifications() {
    try {
      setNotifications(await listNotifications());
    } catch (error) {
      console.error("Load notifications failed", error);
      setNotifications([]);
    }
  }

  async function readNotification(id: string) {
    const updated = await markNotificationRead(id);
    setNotifications((current) => current.map((item) => item.id === id ? updated : item));
  }

  async function readAllNotifications() {
    setNotifications(await markAllNotificationsRead());
  }

  async function removeNotification(id: string) {
    await deleteNotification(id);
    setNotifications((current) => current.filter((item) => item.id !== id));
  }

  async function runCheck(item: SavedSearch) {
    setCheckingId(item.id);
    setOpenedSearch(item);
    setCheckedRoutes([]);
    try {
      const result = await checkSavedSearch(item.id);
      setOpenedSearch(result.saved_search);
      setCheckedRoutes(result.routes);
      setSavedSearches((current) =>
        current.map((row) => (row.id === item.id ? result.saved_search : row)),
      );
      setRequestsNotice(
        result.saved_search.last_available_routes_count
          ? "Проверка выполнена: доступны маршруты для группы."
          : "Проверка выполнена: доступных маршрутов нет.",
      );
    } catch (error) {
      console.error("Saved search check failed", error);
      setRequestsNotice(
        "Проверка не удалась. Ошибка сохранена в заявке на backend, если сервер доступен.",
      );
    } finally {
      setCheckingId(null);
    }
  }


  async function runMonitoringCheck(item: SavedSearch) {
    setCheckingId(item.id);
    try {
      const result = await runMonitoring(item.id);
      setHistoryBySearch((current) => ({
        ...current,
        [item.id]: [result.history, ...(current[item.id] ?? [])],
      }));
      setRequestsNotice(result.summary);
      void loadNotifications();
    } catch (error) {
      console.error("Monitoring check failed", error);
      setRequestsNotice("Monitoring Engine не смог выполнить проверку заявки.");
    } finally {
      setCheckingId(null);
    }
  }

  async function runMonitoringForAll() {
    setRunningAll(true);
    try {
      const results = await runAllMonitoring();
      setHistoryBySearch((current) => {
        const next = { ...current };
        for (const result of results) {
          next[result.saved_search_id] = [
            result.history,
            ...(next[result.saved_search_id] ?? []),
          ];
        }
        return next;
      });
      setRequestsNotice(`Monitoring Engine проверил заявок: ${results.length}.`);
      void loadNotifications();
    } catch (error) {
      console.error("Run all monitoring failed", error);
      setRequestsNotice("Не удалось запустить Monitoring Engine для всех заявок.");
    } finally {
      setRunningAll(false);
    }
  }

  async function openHistory(item: SavedSearch) {
    setOpenedSearch(item);
    setCheckedRoutes([]);
    try {
      const history = await monitoringHistory(item.id);
      setHistoryBySearch((current) => ({ ...current, [item.id]: history }));
      setRequestsNotice(history.length ? "История проверок загружена." : "История проверок пока пуста.");
    } catch (error) {
      console.error("Load monitoring history failed", error);
      setRequestsNotice("Не удалось загрузить историю мониторинга.");
    }
  }

  async function toggleMonitoring(item: SavedSearch) {
    const updated = await updateSavedSearch(item.id, {
      monitoring_enabled: !item.monitoring_enabled,
    });
    setSavedSearches((current) =>
      current.map((row) => (row.id === item.id ? updated : row)),
    );
  }

  async function removeSearch(item: SavedSearch) {
    await deleteSavedSearch(item.id);
    setSavedSearches((current) => current.filter((row) => row.id !== item.id));
    setRequestsNotice("Заявка удалена.");
    if (openedSearch?.id === item.id) {
      setOpenedSearch(null);
      setCheckedRoutes([]);
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#eef8ff,transparent_34%),linear-gradient(180deg,#fff_0%,#f7f9fc_100%)]">
      <header className="mx-auto flex w-full max-w-screen-2xl items-center justify-between px-5 py-5 sm:px-8 lg:px-12">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-white shadow-soft">
            <Route size={22} />
          </div>
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-muted">
              Business Trip Planner
            </p>
            <p className="text-xs text-muted">
              Commercial-grade route planning MVP
            </p>
          </div>
        </div>
        <nav className="flex items-center gap-2">
          <button
            onClick={() => setViewMode("search")}
            className={`rounded-full px-4 py-2 text-sm font-semibold ${viewMode === "search" ? "bg-ink text-white" : "border border-line bg-white text-ink"}`}
          >
            Поиск маршрута
          </button>
          <button
            onClick={() => setViewMode("requests")}
            className={`rounded-full px-4 py-2 text-sm font-semibold ${viewMode === "requests" ? "bg-ink text-white" : "border border-line bg-white text-ink"}`}
          >
            Заявки
          </button>
        </nav>
        <div className="relative flex items-center gap-2">
          <button
            onClick={() => setNotificationsOpen((value) => !value)}
            className="relative rounded-2xl border border-line bg-white p-3 text-ink shadow-soft transition hover:-translate-y-0.5"
            aria-label="Открыть центр уведомлений"
          >
            <Bell size={20} />
            {unreadNotifications > 0 && (
              <span className="absolute -right-2 -top-2 rounded-full bg-rose-500 px-2 py-0.5 text-xs font-bold text-white">
                {unreadNotifications}
              </span>
            )}
          </button>
          <span className="hidden rounded-full bg-ink px-3 py-1 text-xs font-semibold text-white sm:inline-flex">
            v0.3
          </span>
          {notificationsOpen && (
            <NotificationCenter
              notifications={notifications}
              onRefresh={loadNotifications}
              onRead={readNotification}
              onReadAll={readAllNotifications}
              onDelete={removeNotification}
            />
          )}
        </div>
      </header>

      {viewMode === "search" ? (
        <div className="mx-auto w-full max-w-screen-2xl px-5 pb-10 sm:px-8 lg:px-12">
          <section className="grid items-center gap-8 py-10 lg:grid-cols-[1.05fr_.95fr] lg:py-16">
            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.55 }}
            >
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-4 py-2 text-sm font-medium text-muted shadow-soft">
                <Sparkles size={16} className="text-aqua" /> Используются
                демонстрационные данные
              </div>
              <h1 className="max-w-4xl text-5xl font-semibold tracking-[-0.055em] text-ink sm:text-6xl xl:text-7xl">
                Поиск оптимального маршрута для командировок
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-muted sm:text-xl">
                Находит лучшие маршруты по России с учетом пересадок и
                доступности мест.
              </p>
            </motion.div>
            <TransportIllustration />
          </section>

          <form
            onSubmit={onSubmit}
            className="rounded-[2rem] border border-white bg-white/90 p-4 shadow-card backdrop-blur sm:p-6 lg:p-8"
          >
            <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-2xl font-semibold tracking-tight text-ink">
                  Параметры поездки
                </h2>
                <p className="mt-1 text-sm text-muted">
                  Дорогая форма без визуального шума: только ключевые
                  ограничения маршрута.
                </p>
              </div>
              <button
                type="button"
                onClick={swapCities}
                className="inline-flex items-center justify-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-3 text-sm font-semibold text-ink transition hover:-translate-y-0.5 hover:bg-white hover:shadow-soft"
              >
                <ArrowLeftRight size={17} /> Поменять города местами
              </button>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <LocationAutocomplete
                label="Откуда"
                value={formState.origin}
                selected={formState.originLocation}
                onChange={(value) => updateField("origin", value)}
                onSelect={(location, displayName) => setFormState((current) => ({ ...current, origin: displayName, originLocation: location }))}
                required
              />
              <LocationAutocomplete
                label="Куда"
                value={formState.destination}
                selected={formState.destinationLocation}
                onChange={(value) => updateField("destination", value)}
                onSelect={(location, displayName) => setFormState((current) => ({ ...current, destination: displayName, destinationLocation: location }))}
                required
              />
              <label className="space-y-2 text-sm font-semibold text-ink">
                Дата
                <input
                  className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  type="date"
                  value={formState.departure_date}
                  onChange={(e) =>
                    updateField("departure_date", e.target.value)
                  }
                  required
                />
              </label>
              <label className="space-y-2 text-sm font-semibold text-ink">
                Количество сотрудников
                <input
                  className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  type="number"
                  min="1"
                  value={formState.passengers}
                  onChange={(e) =>
                    updateField("passengers", Number(e.target.value))
                  }
                  required
                />
              </label>
              <label className="space-y-2 text-sm font-semibold text-ink">
                Тип транспорта
                <select
                  className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  value={formState.transport}
                  onChange={(e) =>
                    updateField(
                      "transport",
                      e.target.value as FormState["transport"],
                    )
                  }
                >
                  <option value="both">Поезд и автобус</option>
                  <option value="train">Только поезд</option>
                  <option value="bus">Только автобус</option>
                </select>
              </label>
              <label className="space-y-2 text-sm font-semibold text-ink">
                Максимум пересадок
                <select
                  className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  value={formState.max_transfers}
                  onChange={(e) =>
                    updateField("max_transfers", Number(e.target.value))
                  }
                >
                  <option value="0">0</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                </select>
              </label>
              <label className="space-y-2 text-sm font-semibold text-ink">
                Минимальное время пересадки
                <input
                  className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
                  type="number"
                  min="0"
                  value={formState.minimum_transfer_minutes}
                  onChange={(e) =>
                    updateField(
                      "minimum_transfer_minutes",
                      Number(e.target.value),
                    )
                  }
                  required
                />
              </label>
              <label className="space-y-2 text-sm font-semibold text-ink">
                Максимальное время пересадки
                <input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" type="number" min="0" value={formState.maximum_transfer_minutes} onChange={(e) => updateField("maximum_transfer_minutes", Number(e.target.value))} required />
              </label>
              <label className="flex items-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-3 text-sm font-semibold text-ink">
                <input
                  type="checkbox"
                  checked={formState.strict_availability}
                  onChange={(e) => {
                    updateField("strict_availability", e.target.checked);
                    if (!e.target.checked) disableStrictAvailabilityWithLoadedRoutes();
                  }}
                /> Только подтверждённые варианты
              </label>
              <label className="flex items-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-3 text-sm font-semibold text-ink">
                <input type="checkbox" checked={formState.lower_only} onChange={(e) => updateField("lower_only", e.target.checked)} /> Только нижние места
              </label>
              <label className="flex items-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-3 text-sm font-semibold text-ink">
                <input type="checkbox" checked={formState.same_compartment} onChange={(e) => updateField("same_compartment", e.target.checked)} /> Все сотрудники в одном купе
              </label>
              <button
                className="mt-auto inline-flex items-center justify-center gap-2 rounded-2xl bg-ink px-5 py-3 font-semibold text-white shadow-soft transition hover:-translate-y-0.5 hover:bg-brand disabled:cursor-not-allowed disabled:opacity-70"
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="animate-spin" size={19} />
                ) : (
                  <MapPinned size={19} />
                )}{" "}
                {loading ? "Ищем..." : "Найти маршрут"}
              </button>
            </div>
            <div
              className={`mt-5 flex items-center gap-2 rounded-2xl px-4 py-3 text-sm font-medium ${notice.kind === "error" ? "bg-amber-50 text-amber-800" : notice.kind === "empty" ? "bg-slate-100 text-slate-700" : notice.kind === "success" ? "bg-emerald-50 text-emerald-800" : "bg-sky-50 text-sky-800"}`}
            >
              {notice.kind === "error" ? (
                <WifiOff size={17} />
              ) : (
                <BadgeCheck size={17} />
              )}{" "}
              {notice.text}
            </div>
            {apiDiagnostics && isDiagnosticsEnabled() && (
              <ApiDiagnosticsBlock diagnostics={apiDiagnostics} />
            )}
            {tutuEnrichmentWarning && (
              <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
                Расписание найдено, но проверить наличие мест через Туту не удалось.
              </div>
            )}
            {!loading && routes.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" onClick={saveCurrentSearch} className="inline-flex items-center justify-center gap-2 rounded-2xl bg-brand px-5 py-3 font-semibold text-white shadow-soft transition hover:-translate-y-0.5 hover:bg-ink">
                  <BadgeCheck size={18} /> Сохранить заявку
                </button>
                <button type="button" onClick={() => { setCompareMode((value) => !value); setComparison(null); }} className="inline-flex items-center justify-center gap-2 rounded-2xl border border-line bg-white px-5 py-3 font-semibold text-ink shadow-soft transition hover:-translate-y-0.5">
                  <ArrowLeftRight size={18} /> {compareMode ? "Выключить сравнение" : "Сравнить"}
                </button>
                {compareMode && <button type="button" disabled={compareIds.length !== 2} onClick={runCompare} className="inline-flex items-center justify-center gap-2 rounded-2xl bg-ink px-5 py-3 font-semibold text-white shadow-soft disabled:opacity-50">Показать сравнение</button>}
              </div>
            )}
          </form>

          <section className="mt-8 grid gap-5">
            {loading &&
              Array.from({ length: 2 }).map((_, index) => (
                <div
                  key={index}
                  className="h-72 animate-pulse rounded-[2rem] border border-line bg-white shadow-soft"
                />
              ))}
            {!loading && sortedRoutes.length === 0 && hasHiddenUnconfirmedRoutes(lastRouteResponse ?? { routes: [] }, formState.strict_availability) && (
              <div className="rounded-[2rem] border border-amber-100 bg-amber-50 p-10 text-center shadow-soft">
                <Milestone className="mx-auto mb-4 text-amber-600" />
                <h3 className="text-xl font-semibold text-ink">Расписания найдены</h3>
                <p className="mx-auto mt-2 max-w-2xl text-muted">
                  Расписания найдены, но наличие мест не подтверждено. Отключите “Только подтверждённые варианты”, чтобы посмотреть маршруты.
                </p>
                <button type="button" onClick={showUnconfirmedRoutes} className="mt-5 rounded-2xl bg-brand px-5 py-3 font-semibold text-white shadow-soft transition hover:-translate-y-0.5 hover:bg-ink">
                  Показать неподтверждённые маршруты
                </button>
              </div>
            )}
            {!loading && sortedRoutes.length === 0 && !hasHiddenUnconfirmedRoutes(lastRouteResponse ?? { routes: [] }, formState.strict_availability) && (
              <div className="rounded-[2rem] border border-line bg-white p-10 text-center shadow-soft">
                <Milestone className="mx-auto mb-4 text-muted" />
                <h3 className="text-xl font-semibold">Нет маршрутов</h3>
                <p className="mt-2 text-muted">
                  Измените город, дату или допустимое количество пересадок.
                </p>
              </div>
            )}
            {!loading &&
              sortedRoutes.map((route, index) => (
                <motion.article
                  key={route.id}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.35, delay: index * 0.06 }}
                  whileHover={{ y: -3 }}
                  className="rounded-[2rem] border border-line bg-white p-5 shadow-soft transition-shadow hover:shadow-card sm:p-7"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="flex flex-wrap gap-2">
                        <span className="rounded-full bg-ink px-3 py-1 text-xs font-semibold text-white">
                          {routeLabel(route, index)}
                        </span>
                        <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
                          {route.transfers_count === 0
                            ? "Без пересадок"
                            : `${route.transfers_count} пересадка`}
                        </span>
                        <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">
                          {route.segments
                            .map((s) => transportLabels[s.transport_type])
                            .join(" + ")}
                        </span>
                      </div>
                      <h2 className="mt-4 text-2xl font-semibold tracking-tight text-ink">
                        {route.origin} → {route.destination}
                      </h2>
                    </div>
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${availabilityBadge(route).className}`}
                    >
                      {availabilityBadge(route).text}
                    </span>
                  </div>
                  <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                    {[
                      [
                        Clock3,
                        "Время в пути",
                        minutesLabel(route.total_duration_minutes),
                      ],
                      [Milestone, "Пересадки", String(route.transfers_count)],
                      [
                        UsersRound,
                        "Свободных мест",
                        seatCountLabel(totalSeats(route)),
                      ],
                      [BadgeCheck, "Минимум мест", seatCountLabel(minSeats(route))],
                      [
                        CalendarDays,
                        "Пересадка",
                        route.transfer_duration_minutes
                          ? minutesLabel(route.transfer_duration_minutes)
                          : "—",
                      ],
                    ].map(([Icon, label, value]) => {
                      const TypedIcon = Icon as typeof Clock3;
                      return (
                        <div
                          key={String(label)}
                          className="rounded-2xl bg-cloud p-4"
                        >
                          <TypedIcon size={18} className="mb-3 text-brand" />
                          <p className="text-xs font-medium uppercase tracking-wide text-muted">
                            {String(label)}
                          </p>
                          <p className="mt-1 font-semibold text-ink">
                            {String(value)}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-6 flex flex-wrap gap-2">
                    <button type="button" onClick={() => explainRoute(route)} className="rounded-2xl bg-brand px-4 py-2 text-sm font-semibold text-white">Почему этот маршрут?</button>
                    {compareMode && (
                      <label className="inline-flex items-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-2 text-sm font-semibold text-ink">
                        <input type="checkbox" checked={compareIds.includes(route.id)} onChange={() => toggleCompareRoute(route.id)} /> Сравнить
                      </label>
                    )}
                  </div>
                  <div className="mt-7 rounded-[1.5rem] border border-line p-4 sm:p-5">
                    <div className="grid gap-4">
                      {route.segments.map((segment, segmentIndex) => {
                        const Icon = transportIcons[segment.transport_type];
                        return (
                          <div
                            key={segment.id}
                            className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center"
                          >
                            <div className="rounded-2xl bg-cloud p-4">
                              <p className="font-semibold text-ink">
                                {segment.origin}
                              </p>
                              <p className="text-sm text-muted">
                                {segment.origin_station || "Станция не указана"} · {dateTime(segment.departure_time)}
                              </p>
                            </div>
                            <div className="flex items-center justify-center gap-2 text-muted sm:flex-col">
                              <ArrowDown className="sm:hidden" size={18} />
                              <Icon className="text-brand" size={22} />
                              <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold shadow-soft">
                                {transportLabels[segment.transport_type]} {segment.number}
                              </span>
                              <span className="text-center text-xs text-muted">
                                {segment.carrier || "Перевозчик не указан"}<br />{segment.source || "Источник не указан"}
                              </span>
                              {segmentIndex < route.segments.length - 1 && (
                                <span className="text-center text-xs font-medium text-aqua">
                                  пересадка: {route.transfers?.[segmentIndex]?.duration_minutes ? minutesLabel(route.transfers[segmentIndex].duration_minutes) : "проверяется"}
                                  {route.transfers?.[segmentIndex]?.station_change_required ? " · смена вокзала" : ""}
                                </span>
                              )}
                            </div>
                            <div className="rounded-2xl bg-cloud p-4">
                              <p className="font-semibold text-ink">
                                {segment.destination}
                              </p>
                              <p className="text-sm text-muted">
                                {segment.destination_station || "Станция не указана"} · {dateTime(segment.arrival_time)} · {minutesLabel(Math.round((new Date(segment.arrival_time).getTime() - new Date(segment.departure_time).getTime()) / 60000))}
                              </p>
                              <p className="mt-1 text-xs font-medium text-aqua">
                                {segment.availability_message || (segment.available_seats === null ? "Наличие мест не подтверждено" : `${segment.available_seats} мест`)}
                                {segment.selected_places?.length ? ` · места ${segment.selected_places.join(", ")}` : ""}
                              </p>
                              <div className="mt-2 flex flex-wrap gap-1 text-[11px] font-semibold">
                                <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">Расписание найдено</span>
                                {segment.availability_status === "confirmed" && <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700">Наличие мест подтверждено</span>}
                                {(!segment.availability_status || ["unconfirmed", "unknown", "partially_confirmed"].includes(segment.availability_status)) && <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700">Наличие мест не проверено</span>}
                                {segment.availability_status === "provider_error" && <span className="rounded-full bg-rose-50 px-2 py-1 text-rose-700">Проверка временно недоступна</span>}
                                {segment.availability_status === "confirmed" && formState.lower_only && <span className="rounded-full bg-sky-50 px-2 py-1 text-sky-700">Нижние места подтверждены</span>}
                                {segment.availability_status === "confirmed" && formState.same_compartment && segment.selected_compartments?.length === 1 && <span className="rounded-full bg-sky-50 px-2 py-1 text-sky-700">Одно купе подтверждено</span>}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </motion.article>
              ))}
          </section>
          {comparison && <ComparisonTable comparison={comparison} />}
        </div>
      ) : (
        <RequestsScreen
          items={savedSearches}
          notice={requestsNotice}
          loading={requestsLoading}
          checkingId={checkingId}
          openedSearch={openedSearch}
          checkedRoutes={checkedRoutes}
          onRefresh={loadSavedSearches}
          onCheck={runCheck}
          onMonitoringCheck={runMonitoringCheck}
          onRunAll={runMonitoringForAll}
          runningAll={runningAll}
          historyBySearch={historyBySearch}
          onOpen={(item) => {
            void openHistory(item);
          }}
          onToggle={toggleMonitoring}
          onDelete={removeSearch}
        />
      )}

      {selectedDecision && <DecisionModal summary={selectedDecision} onClose={() => setSelectedDecision(null)} />}
      <footer className="border-t border-line bg-white/80">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-3 px-5 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-12">
          <span className="font-semibold text-ink">Business Trip Planner</span>
          <span>MVP · Mock Data · Internal Tool · 2026</span>
        </div>
      </footer>
    </main>
  );
}

type ApiDiagnostics = {
  apiBaseUrl: string;
  requestPath: string;
  status: string;
  responsePreview: string;
};

function isDiagnosticsEnabled() {
  return process.env.NODE_ENV === "development" || process.env.NEXT_PUBLIC_DEBUG_API === "true";
}

function preview(value: string | undefined) {
  return (value ?? "").slice(0, 2000);
}

function formatResponseBody(body: string | undefined) {
  if (!body) return "";
  try {
    const parsed = JSON.parse(body) as unknown;
    if (typeof parsed === "object" && parsed && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail);
    }
    return body;
  } catch {
    return body;
  }
}

function routeSearchErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    const detail = formatResponseBody(error.responseBody);
    if (error.message === "Backend вернул некорректный JSON") {
      return "Backend вернул некорректный ответ";
    }
    if (error.status === 422) {
      return `Ошибка параметров запроса${detail ? `: ${detail}` : ""}`;
    }
    if (error.status && error.status >= 500) {
      return `Ошибка backend${detail ? `: ${detail}` : ""}`;
    }
    if (!error.status) {
      return "Не удалось подключиться к backend";
    }
    return detail || `Ошибка API: HTTP ${error.status}`;
  }
  return "Не удалось выполнить поиск маршрута";
}

function buildApiDiagnostics(error: unknown, requestPath: string): ApiDiagnostics {
  if (error instanceof ApiError) {
    return {
      apiBaseUrl: apiBaseUrl(),
      requestPath,
      status: error.status ? `${error.status} ${error.statusText ?? ""}`.trim() : "network error",
      responsePreview: preview(error.responseBody ?? (error.cause instanceof Error ? error.cause.message : error.message)),
    };
  }
  return {
    apiBaseUrl: apiBaseUrl(),
    requestPath,
    status: "unknown error",
    responsePreview: error instanceof Error ? error.message : String(error),
  };
}

function ApiDiagnosticsBlock({ diagnostics }: { diagnostics: ApiDiagnostics }) {
  return (
    <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
      <p className="font-semibold">API diagnostics</p>
      <dl className="mt-2 grid gap-1">
        <div><dt className="inline font-semibold">Base URL: </dt><dd className="inline break-all">{diagnostics.apiBaseUrl}</dd></div>
        <div><dt className="inline font-semibold">Request path: </dt><dd className="inline break-all">{diagnostics.requestPath}</dd></div>
        <div><dt className="inline font-semibold">HTTP status: </dt><dd className="inline">{diagnostics.status}</dd></div>
        <div><dt className="font-semibold">Response preview:</dt><dd className="mt-1 whitespace-pre-wrap break-words">{diagnostics.responsePreview || "—"}</dd></div>
      </dl>
    </div>
  );
}

function buildPayload(formState: FormState): RouteSearchPayload {
  return buildRouteSearchPayload(formState);
}

const checkLabels: Record<SavedSearch["last_check_status"], string> = {
  never_checked: "Ещё не проверялась",
  checking: "Проверяется",
  routes_found: "Маршруты найдены",
  no_available_routes: "Доступных маршрутов нет",
  failed: "Ошибка проверки",
};

function RequestsScreen(props: {
  items: SavedSearch[];
  notice: string;
  loading: boolean;
  checkingId: string | null;
  openedSearch: SavedSearch | null;
  checkedRoutes: RouteOption[];
  onRefresh: () => void;
  onCheck: (item: SavedSearch) => void;
  onMonitoringCheck: (item: SavedSearch) => void;
  onRunAll: () => void;
  runningAll: boolean;
  historyBySearch: Record<string, MonitoringHistory[]>;
  onOpen: (item: SavedSearch) => void;
  onToggle: (item: SavedSearch) => void;
  onDelete: (item: SavedSearch) => void;
}) {
  return (
    <div className="mx-auto w-full max-w-screen-2xl px-5 pb-10 sm:px-8 lg:px-12">
      <section className="py-10">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-5xl font-semibold tracking-[-0.055em] text-ink">
              Заявки на командировку
            </h1>
            <p className="mt-4 max-w-2xl text-lg text-muted">
              Сохранённые параметры поиска и ручная повторная проверка маршрутов
              с историей проверок Monitoring Engine без уведомлений и бронирований.
            </p>
          </div>
<div className="flex flex-wrap gap-2">
            <button
              onClick={props.onRunAll}
              disabled={props.runningAll}
              className="rounded-2xl bg-brand px-5 py-3 font-semibold text-white shadow-soft disabled:opacity-60"
            >
              {props.runningAll ? "Проверяем..." : "Проверить все"}
            </button>
            <button
              onClick={props.onRefresh}
              className="rounded-2xl bg-ink px-5 py-3 font-semibold text-white shadow-soft"
            >
              Обновить список
            </button>
          </div>
        </div>
      </section>
      <div className="mb-5 rounded-2xl bg-sky-50 px-4 py-3 text-sm font-medium text-sky-800">
        {props.loading ? "Загружаем заявки..." : props.notice}
      </div>
      {!props.loading && props.items.length === 0 && (
        <div className="rounded-[2rem] border border-line bg-white p-10 text-center shadow-soft">
          <Milestone className="mx-auto mb-4 text-muted" />
          <h3 className="text-xl font-semibold">Заявок ещё нет</h3>
          <p className="mt-2 text-muted">
            Перейдите в «Поиск маршрута», получите результаты и нажмите
            «Сохранить заявку».
          </p>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        {props.items.map((item) => {
          const history = props.historyBySearch[item.id] ?? [];
          const latest = history[0];
          const changesCount = history.filter((row) => row.change_detected).length;
          return (
          <article
            key={item.id}
            className="rounded-[2rem] border border-line bg-white p-6 shadow-soft"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-2xl font-semibold text-ink">
                  {item.title}
                </h2>
                <p className="mt-1 text-muted">
                  {item.origin} → {item.destination} ·{" "}
                  {new Date(item.departure_date).toLocaleDateString("ru-RU")}
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${item.monitoring_enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
              >
                {item.monitoring_enabled
                  ? "Мониторинг включён"
                  : "Мониторинг приостановлен"}
              </span>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Info label="Сотрудников" value={String(item.passengers)} />
              <Info
                label="Транспорт"
                value={item.allowed_transport
                  .map((type) => transportLabels[type])
                  .join(", ")}
              />
              <Info
                label="Последняя проверка"
                value={latest ? new Date(latest.checked_at).toLocaleString("ru-RU") : item.last_checked_at ? new Date(item.last_checked_at).toLocaleString("ru-RU") : "—"}
              />
              <Info
                label="Статус проверки"
                value={checkLabels[item.last_check_status]}
              />
              <Info
                label="Маршрутов найдено"
                value={String(item.last_routes_count)}
              />
              <Info
                label="Доступных маршрутов"
                value={String(latest?.available_routes ?? item.last_available_routes_count)}
              />
              <Info label="Количество изменений" value={String(changesCount)} />
            </div>
            {item.last_error && (
              <p className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {item.last_error}
              </p>
            )}
            <div className="mt-5 flex flex-wrap gap-2">
              <button
                onClick={() => props.onCheck(item)}
                disabled={props.checkingId === item.id}
                className="rounded-2xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {props.checkingId === item.id
                  ? "Проверка выполняется..."
                  : "Проверить сейчас"}
              </button>
<button
                onClick={() => props.onMonitoringCheck(item)}
                disabled={props.checkingId === item.id}
                className="rounded-2xl border border-line bg-cloud px-4 py-2 text-sm font-semibold text-ink disabled:opacity-60"
              >
                Мониторинг
              </button>
              <button
                onClick={() => props.onOpen(item)}
                className="rounded-2xl border border-line bg-cloud px-4 py-2 text-sm font-semibold text-ink"
              >
                История
              </button>
              <button
                onClick={() => props.onToggle(item)}
                className="rounded-2xl border border-line bg-cloud px-4 py-2 text-sm font-semibold text-ink"
              >
                {item.monitoring_enabled ? "Приостановить" : "Возобновить"}
              </button>
              <button
                onClick={() => props.onDelete(item)}
                className="rounded-2xl bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700"
              >
                Удалить
              </button>
            </div>
          </article>
          );
        })}
      </div>
      {props.openedSearch && (
        <section className="mt-8">
          <h2 className="mb-4 text-3xl font-semibold text-ink">
            Открыта заявка: {props.openedSearch.title}
          </h2>
          {props.checkingId === props.openedSearch.id && (
            <div className="rounded-2xl bg-sky-50 p-4 text-sky-800">
              Проверка выполняется...
            </div>
          )}
          <MonitoringTimeline history={props.historyBySearch[props.openedSearch.id] ?? []} />
          {!props.checkingId && props.checkedRoutes.length === 0 && (
            <div className="mt-4 rounded-2xl bg-slate-100 p-4 text-slate-700">
              Нажмите «Проверить сейчас», чтобы увидеть найденные маршруты, или «Мониторинг», чтобы зафиксировать изменение.
            </div>
          )}
          <div className="grid gap-5">
            {props.checkedRoutes.map((route, index) => (
              <RouteCard key={route.id} route={route} index={index} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-cloud p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">
        {label}
      </p>
      <p className="mt-1 font-semibold text-ink">{value}</p>
    </div>
  );
}

function RouteCard({ route, index }: { route: RouteOption; index: number }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.06 }}
      className="rounded-[2rem] border border-line bg-white p-5 shadow-soft sm:p-7"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full bg-ink px-3 py-1 text-xs font-semibold text-white">
              {routeLabel(route, index)}
            </span>
            <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
              {route.transfers_count === 0
                ? "Без пересадок"
                : `${route.transfers_count} пересадка`}
            </span>
          </div>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight text-ink">
            {route.origin} → {route.destination}
          </h2>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${availabilityBadge(route).className}`}
        >
          {availabilityBadge(route).text}
        </span>
      </div>
      <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {[
          [Clock3, "Время в пути", minutesLabel(route.total_duration_minutes)],
          [Milestone, "Пересадки", String(route.transfers_count)],
          [
            UsersRound,
            "Свободных мест",
            seatCountLabel(totalSeats(route)),
          ],
          [BadgeCheck, "Минимум мест", seatCountLabel(minSeats(route))],
          [
            CalendarDays,
            "Пересадка",
            route.transfer_duration_minutes
              ? minutesLabel(route.transfer_duration_minutes)
              : "—",
          ],
        ].map(([Icon, label, value]) => {
          const TypedIcon = Icon as typeof Clock3;
          return (
            <div key={String(label)} className="rounded-2xl bg-cloud p-4">
              <TypedIcon size={18} className="mb-3 text-brand" />
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                {String(label)}
              </p>
              <p className="mt-1 font-semibold text-ink">{String(value)}</p>
            </div>
          );
        })}
      </div>
    </motion.article>
  );
}


function MonitoringTimeline({ history }: { history: MonitoringHistory[] }) {
  if (!history.length) {
    return <div className="rounded-2xl bg-slate-100 p-4 text-slate-700">История проверок пока пуста.</div>;
  }
  return (
    <div className="rounded-[2rem] border border-line bg-white p-6 shadow-soft">
      <h3 className="mb-4 text-2xl font-semibold text-ink">История проверок</h3>
      <div className="space-y-4">
        {history.map((row) => (
          <div key={row.id} className="border-l-2 border-brand pl-4">
            <p className="text-sm font-semibold text-brand">{new Date(row.checked_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</p>
            <p className="mt-1 font-semibold text-ink">{row.summary}</p>
            <p className="mt-1 text-sm text-muted">Дата: {new Date(row.checked_at).toLocaleString("ru-RU")} · Маршрутов найдено: {row.routes_found} · Доступных маршрутов: {row.available_routes} · Изменения: {row.change_detected ? "да" : "нет"}</p>
            <div className="mt-3 border-t border-dashed border-line" />
          </div>
        ))}
      </div>
    </div>
  );
}

const notificationLabels: Record<Notification["type"], string> = {
  new_route: "Новый маршрут",
  seats_available: "Есть места",
  better_route: "Лучший маршрут",
  price_changed: "Цена",
  monitoring_failed: "Ошибка мониторинга",
  monitoring_resumed: "Мониторинг восстановлен",
};

const severityStyles: Record<Notification["severity"], string> = {
  info: "border-sky-200 bg-sky-50 text-sky-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  critical: "border-rose-200 bg-rose-50 text-rose-800",
};

function NotificationCenter(props: {
  notifications: Notification[];
  onRefresh: () => void;
  onRead: (id: string) => void;
  onReadAll: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="absolute right-0 top-14 z-20 w-[min(92vw,440px)] rounded-[2rem] border border-line bg-white p-4 shadow-card">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-ink">Центр уведомлений</h2>
          <p className="text-sm text-muted">Внутренние события Monitoring Engine.</p>
        </div>
        <button onClick={props.onRefresh} className="rounded-full bg-cloud px-3 py-1 text-xs font-semibold text-ink">
          Обновить
        </button>
      </div>
      <div className="mb-3 flex justify-between text-xs font-semibold text-muted">
        <span>Непрочитанных: {props.notifications.filter((item) => !item.is_read).length}</span>
        <button onClick={props.onReadAll} className="text-brand">Прочитать всё</button>
      </div>
      <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        {props.notifications.length === 0 && (
          <div className="rounded-2xl bg-slate-100 p-4 text-sm text-slate-700">Уведомлений пока нет.</div>
        )}
        {props.notifications.map((item) => (
          <article key={item.id} className={`rounded-2xl border p-4 ${severityStyles[item.severity]} ${item.is_read ? "opacity-65" : ""}`}>
            <div className="flex gap-3">
              <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/80">
                <Bell size={17} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide">{notificationLabels[item.type]}</span>
                  <time className="text-xs opacity-75">{new Date(item.created_at).toLocaleString("ru-RU")}</time>
                </div>
                <h3 className="mt-2 font-semibold">{item.title}</h3>
                <p className="mt-1 text-sm leading-5">{item.message}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {!item.is_read && (
                    <button onClick={() => props.onRead(item.id)} className="rounded-full bg-white px-3 py-1 text-xs font-semibold">
                      Прочитано
                    </button>
                  )}
                  <button onClick={() => props.onDelete(item.id)} className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-xs font-semibold">
                    <Trash2 size={13} /> Удалить
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function localDecision(route: RouteOption, passengers: number): DecisionSummary {
  const minimum_available_seats = minSeats(route) ?? 0;
  const advantages = [
    ...(route.is_available_for_group ? [{ code: "available", message: `Подходит для группы из ${passengers} человек.`, kind: "advantage" as const, weight: 22 }] : []),
    ...(route.transfers_count === 0 ? [{ code: "direct", message: "Маршрут без пересадок.", kind: "advantage" as const, weight: 14 }] : []),
  ];
  const warnings = route.transfer_duration_minutes && route.transfer_duration_minutes < 45 ? [{ code: "short_transfer", message: "Очень короткая пересадка.", kind: "warning" as const, weight: -18 }] : [];
  return { route_id: route.id, total_duration_minutes: route.total_duration_minutes, transfer_wait_minutes: route.transfer_duration_minutes ?? 0, transfers_count: route.transfers_count, has_available_seats: route.is_available_for_group === true, minimum_available_seats, score: 70, rating: route.is_available_for_group ? 72 : 30, explanation: advantages[0]?.message ?? warnings[0]?.message ?? "Маршрут оценён по прозрачным правилам.", advantages, disadvantages: [], warnings, recommendations: warnings.length ? [{ code: "miss_risk", message: "Большой риск пропустить следующий поезд.", kind: "recommendation", weight: 0 }] : [] };
}

function localCompare(left: RouteOption, right: RouteOption, passengers: number): DecisionCompareResponse {
  const left_summary = localDecision(left, passengers);
  const right_summary = localDecision(right, passengers);
  const winner_route_id = left_summary.rating === right_summary.rating ? null : left_summary.rating > right_summary.rating ? left.id : right.id;
  return { winner_route_id, left_summary, right_summary, differences: [], recommendations: [{ code: "choose_winner", message: winner_route_id ? "Рекомендуется маршрут-победитель: выше детерминированный рейтинг." : "Маршруты равноценны по детерминированному рейтингу.", kind: "recommendation", weight: 0 }], criteria: [
    { name: "Общий рейтинг", left: String(left_summary.rating), right: String(right_summary.rating), winner: winner_route_id, difference: `разница ${Math.abs(left_summary.rating - right_summary.rating)}` },
    { name: "Время поездки", left: minutesLabel(left.total_duration_minutes), right: minutesLabel(right.total_duration_minutes), winner: left.total_duration_minutes === right.total_duration_minutes ? null : left.total_duration_minutes < right.total_duration_minutes ? left.id : right.id, difference: `разница ${Math.abs(left.total_duration_minutes - right.total_duration_minutes)} мин` },
  ] };
}

function DecisionModal({ summary, onClose }: { summary: DecisionSummary; onClose: () => void }) {
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"><div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-[2rem] bg-white p-6 shadow-card"><div className="flex items-start justify-between gap-4"><div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand">Decision Engine</p><h2 className="mt-2 text-3xl font-semibold text-ink">Почему этот маршрут?</h2><p className="mt-2 text-muted">{summary.explanation}</p></div><button onClick={onClose} className="rounded-full bg-cloud px-4 py-2 font-semibold text-ink">Закрыть</button></div><div className="mt-6 grid gap-3 sm:grid-cols-3"><Info label="Общий рейтинг" value={`${summary.rating}/100`} /><Info label="Ожидание" value={minutesLabel(summary.transfer_wait_minutes)} /><Info label="Минимум мест" value={String(summary.minimum_available_seats)} /></div><ReasonList title="Преимущества" items={summary.advantages} tone="emerald" /><ReasonList title="Недостатки" items={summary.disadvantages} tone="amber" /><ReasonList title="Предупреждения" items={summary.warnings} tone="rose" /><ReasonList title="Рекомендации" items={summary.recommendations} tone="sky" /></div></div>;
}

function ReasonList({ title, items, tone }: { title: string; items: { message: string }[]; tone: "emerald" | "amber" | "rose" | "sky" }) {
  const styles = { emerald: "bg-emerald-50 text-emerald-800", amber: "bg-amber-50 text-amber-800", rose: "bg-rose-50 text-rose-800", sky: "bg-sky-50 text-sky-800" }[tone];
  return <section className="mt-5"><h3 className="mb-2 text-lg font-semibold text-ink">{title}</h3>{items.length ? <div className="grid gap-2">{items.map((item, index) => <p key={index} className={`rounded-2xl px-4 py-3 text-sm font-medium ${styles}`}>{item.message}</p>)}</div> : <p className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-600">Нет факторов.</p>}</section>;
}

function ComparisonTable({ comparison }: { comparison: DecisionCompareResponse }) {
  return <section className="mt-8 rounded-[2rem] border border-line bg-white p-6 shadow-card"><p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand">Compare Mode</p><h2 className="mt-2 text-3xl font-semibold text-ink">Сравнение маршрутов</h2><p className="mt-2 text-muted">Победитель: {comparison.winner_route_id ?? "ничья"}</p><div className="mt-5 overflow-hidden rounded-2xl border border-line"><table className="w-full text-left text-sm"><thead className="bg-cloud text-muted"><tr><th className="p-3">Критерий</th><th className="p-3">Маршрут 1</th><th className="p-3">Маршрут 2</th><th className="p-3">Разница</th></tr></thead><tbody>{comparison.criteria.map((row) => <tr key={row.name} className="border-t border-line"><td className="p-3 font-semibold text-ink">{row.name}</td><td className="p-3">{row.left}</td><td className="p-3">{row.right}</td><td className="p-3">{row.difference}</td></tr>)}</tbody></table></div><ReasonList title="Рекомендации" items={comparison.recommendations} tone="sky" /></section>;
}
