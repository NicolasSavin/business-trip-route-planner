'use client';

import { FormEvent, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowDown, ArrowLeftRight, BadgeCheck, Bus, CalendarDays, Clock3, Loader2, MapPinned, Milestone, Route, Sparkles, TrainFront, UsersRound, WifiOff } from 'lucide-react';
import { demoResponse } from '@/lib/demoData';
import type { RouteOption, RouteSearchResponse, TransportType } from '@/lib/types';

const transportLabels: Record<TransportType, string> = { train: 'Поезд', bus: 'Автобус' };
const transportIcons: Record<TransportType, typeof TrainFront> = { train: TrainFront, bus: Bus };

type NoticeKind = 'demo' | 'api' | 'empty' | 'error';
type FormState = { origin: string; destination: string; departure_date: string; passengers: number; transport: 'both' | TransportType; max_transfers: number; minimum_transfer_minutes: number };

const initialForm: FormState = { origin: 'Москва', destination: 'Екатеринбург', departure_date: '2026-08-10', passengers: 2, transport: 'both', max_transfers: 1, minimum_transfer_minutes: 30 };

function minutesLabel(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function routeLabel(route: RouteOption, index: number) {
  if (index === 0) return 'Оптимальный';
  if (route.transfers_count === 0) return 'Без пересадок';
  if (route.segments.some((segment) => segment.transport_type === 'train') && route.segments.some((segment) => segment.transport_type === 'bus')) return 'Поезд + автобус';
  return 'Самый быстрый';
}

function minSeats(route: RouteOption) {
  return Math.min(...route.segments.map((segment) => segment.available_seats));
}

function TransportIllustration() {
  return <div className="relative hidden min-h-[320px] overflow-hidden rounded-[2rem] border border-white/70 bg-gradient-to-br from-white to-sky-50 p-8 shadow-card lg:block">
    <div className="absolute -right-14 -top-14 h-44 w-44 rounded-full bg-aqua/20 blur-2xl" />
    <div className="absolute -bottom-20 left-10 h-56 w-56 rounded-full bg-brand/10 blur-2xl" />
    <svg viewBox="0 0 420 280" className="relative h-full w-full" role="img" aria-label="Иллюстрация транспорта">
      <path d="M44 208 C112 120, 190 248, 284 132 S374 90, 388 64" fill="none" stroke="#d9e4f2" strokeWidth="14" strokeLinecap="round" />
      <path d="M44 208 C112 120, 190 248, 284 132 S374 90, 388 64" fill="none" stroke="#0f7bff" strokeWidth="4" strokeLinecap="round" strokeDasharray="10 14" />
      <rect x="72" y="72" width="154" height="70" rx="24" fill="#111827" />
      <rect x="96" y="92" width="36" height="22" rx="7" fill="#dff5ff" /><rect x="144" y="92" width="54" height="22" rx="7" fill="#dff5ff" />
      <circle cx="112" cy="148" r="13" fill="#12b7b5" /><circle cx="186" cy="148" r="13" fill="#12b7b5" />
      <rect x="242" y="154" width="112" height="54" rx="18" fill="#0f7bff" />
      <rect x="262" y="170" width="28" height="16" rx="5" fill="#eaf7ff" /><rect x="300" y="170" width="28" height="16" rx="5" fill="#eaf7ff" />
      <circle cx="270" cy="212" r="10" fill="#111827" /><circle cx="326" cy="212" r="10" fill="#111827" />
      <circle cx="44" cy="208" r="10" fill="#12b7b5" /><circle cx="388" cy="64" r="10" fill="#0f7bff" />
    </svg>
  </div>;
}

export default function Home() {
  const [formState, setFormState] = useState<FormState>(initialForm);
  const [routes, setRoutes] = useState<RouteOption[]>(demoResponse.routes);
  const [notice, setNotice] = useState<{ kind: NoticeKind; text: string }>({ kind: 'demo', text: 'Используются демонстрационные данные. Backend будет опрошен при поиске.' });
  const [loading, setLoading] = useState(false);
  const sortedRoutes = useMemo(() => [...routes].sort((a, b) => a.total_duration_minutes - b.total_duration_minutes), [routes]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) { setFormState((current) => ({ ...current, [key]: value })); }
  function swapCities() { setFormState((current) => ({ ...current, origin: current.destination, destination: current.origin })); }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setNotice({ kind: 'api', text: 'Loading: подбираем оптимальные маршруты и проверяем наличие мест.' });
    const allowed_transport = formState.transport === 'both' ? ['train', 'bus'] : [formState.transport];
    const payload = { ...formState, allowed_transport, transport: undefined };
    try {
      const response = await fetch('http://localhost:8000/api/v1/routes/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error('Backend недоступен');
      const data = (await response.json()) as RouteSearchResponse;
      setRoutes(data.routes);
      setNotice(data.routes.length ? { kind: 'api', text: 'Результаты получены из backend API.' } : { kind: 'empty', text: 'Нет маршрутов: попробуйте другую дату, транспорт или пересадки.' });
    } catch {
      setRoutes(demoResponse.routes);
      setNotice({ kind: 'error', text: 'Backend недоступен — показаны демонстрационные данные.' });
    } finally { setLoading(false); }
  }

  return <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#eef8ff,transparent_34%),linear-gradient(180deg,#fff_0%,#f7f9fc_100%)]">
    <header className="mx-auto flex w-full max-w-screen-2xl items-center justify-between px-5 py-5 sm:px-8 lg:px-12">
      <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-white shadow-soft"><Route size={22} /></div><div><p className="text-sm font-semibold uppercase tracking-[0.24em] text-muted">Business Trip Planner</p><p className="text-xs text-muted">Commercial-grade route planning MVP</p></div></div>
      <div className="hidden items-center gap-2 sm:flex"><span className="rounded-full border border-line bg-white px-3 py-1 text-xs font-semibold text-ink">MVP</span><span className="rounded-full border border-line bg-white px-3 py-1 text-xs font-semibold text-muted">Mock Data</span><span className="rounded-full bg-ink px-3 py-1 text-xs font-semibold text-white">v0.2</span></div>
    </header>

    <div className="mx-auto w-full max-w-screen-2xl px-5 pb-10 sm:px-8 lg:px-12">
      <section className="grid items-center gap-8 py-10 lg:grid-cols-[1.05fr_.95fr] lg:py-16">
        <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-4 py-2 text-sm font-medium text-muted shadow-soft"><Sparkles size={16} className="text-aqua" /> Используются демонстрационные данные</div>
          <h1 className="max-w-4xl text-5xl font-semibold tracking-[-0.055em] text-ink sm:text-6xl xl:text-7xl">Поиск оптимального маршрута для командировок</h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-muted sm:text-xl">Находит лучшие маршруты по России с учетом пересадок и доступности мест.</p>
        </motion.div>
        <TransportIllustration />
      </section>

      <form onSubmit={onSubmit} className="rounded-[2rem] border border-white bg-white/90 p-4 shadow-card backdrop-blur sm:p-6 lg:p-8">
        <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"><div><h2 className="text-2xl font-semibold tracking-tight text-ink">Параметры поездки</h2><p className="mt-1 text-sm text-muted">Дорогая форма без визуального шума: только ключевые ограничения маршрута.</p></div><button type="button" onClick={swapCities} className="inline-flex items-center justify-center gap-2 rounded-2xl border border-line bg-cloud px-4 py-3 text-sm font-semibold text-ink transition hover:-translate-y-0.5 hover:bg-white hover:shadow-soft"><ArrowLeftRight size={17} /> Поменять города местами</button></div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="space-y-2 text-sm font-semibold text-ink">Откуда<input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" value={formState.origin} onChange={(e) => updateField('origin', e.target.value)} required /></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Куда<input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" value={formState.destination} onChange={(e) => updateField('destination', e.target.value)} required /></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Дата<input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" type="date" value={formState.departure_date} onChange={(e) => updateField('departure_date', e.target.value)} required /></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Количество сотрудников<input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" type="number" min="1" value={formState.passengers} onChange={(e) => updateField('passengers', Number(e.target.value))} required /></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Тип транспорта<select className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" value={formState.transport} onChange={(e) => updateField('transport', e.target.value as FormState['transport'])}><option value="both">Поезд и автобус</option><option value="train">Только поезд</option><option value="bus">Только автобус</option></select></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Максимум пересадок<select className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" value={formState.max_transfers} onChange={(e) => updateField('max_transfers', Number(e.target.value))}><option value="0">0</option><option value="1">1</option></select></label>
          <label className="space-y-2 text-sm font-semibold text-ink">Минимальное время пересадки<input className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" type="number" min="0" value={formState.minimum_transfer_minutes} onChange={(e) => updateField('minimum_transfer_minutes', Number(e.target.value))} required /></label>
          <button className="mt-auto inline-flex items-center justify-center gap-2 rounded-2xl bg-ink px-5 py-3 font-semibold text-white shadow-soft transition hover:-translate-y-0.5 hover:bg-brand disabled:cursor-not-allowed disabled:opacity-70" disabled={loading}>{loading ? <Loader2 className="animate-spin" size={19} /> : <MapPinned size={19} />} {loading ? 'Ищем...' : 'Найти маршрут'}</button>
        </div>
        <div className={`mt-5 flex items-center gap-2 rounded-2xl px-4 py-3 text-sm font-medium ${notice.kind === 'error' ? 'bg-amber-50 text-amber-800' : notice.kind === 'empty' ? 'bg-slate-100 text-slate-700' : 'bg-sky-50 text-sky-800'}`}>{notice.kind === 'error' ? <WifiOff size={17} /> : <BadgeCheck size={17} />} {notice.text}</div>
      </form>

      <section className="mt-8 grid gap-5">
        {loading && Array.from({ length: 2 }).map((_, index) => <div key={index} className="h-72 animate-pulse rounded-[2rem] border border-line bg-white shadow-soft" />)}
        {!loading && sortedRoutes.length === 0 && <div className="rounded-[2rem] border border-line bg-white p-10 text-center shadow-soft"><Milestone className="mx-auto mb-4 text-muted" /><h3 className="text-xl font-semibold">Нет маршрутов</h3><p className="mt-2 text-muted">Измените город, дату или допустимое количество пересадок.</p></div>}
        {!loading && sortedRoutes.map((route, index) => <motion.article key={route.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: index * 0.06 }} whileHover={{ y: -3 }} className="rounded-[2rem] border border-line bg-white p-5 shadow-soft transition-shadow hover:shadow-card sm:p-7">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"><div><div className="flex flex-wrap gap-2"><span className="rounded-full bg-ink px-3 py-1 text-xs font-semibold text-white">{routeLabel(route, index)}</span><span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">{route.transfers_count === 0 ? 'Без пересадок' : `${route.transfers_count} пересадка`}</span><span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">{route.segments.map((s) => transportLabels[s.transport_type]).join(' + ')}</span></div><h2 className="mt-4 text-2xl font-semibold tracking-tight text-ink">{route.origin} → {route.destination}</h2></div><span className={`rounded-full px-3 py-1 text-xs font-semibold ${route.is_available_for_group ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{route.is_available_for_group ? 'Доступно для группы' : 'Недостаточно мест'}</span></div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{[[Clock3, 'Время в пути', minutesLabel(route.total_duration_minutes)], [Milestone, 'Пересадки', String(route.transfers_count)], [UsersRound, 'Свободных мест', String(route.segments.reduce((sum, segment) => sum + segment.available_seats, 0))], [BadgeCheck, 'Минимум мест', String(minSeats(route))], [CalendarDays, 'Пересадка', route.transfer_duration_minutes ? minutesLabel(route.transfer_duration_minutes) : '—']].map(([Icon, label, value]) => { const TypedIcon = Icon as typeof Clock3; return <div key={String(label)} className="rounded-2xl bg-cloud p-4"><TypedIcon size={18} className="mb-3 text-brand" /><p className="text-xs font-medium uppercase tracking-wide text-muted">{String(label)}</p><p className="mt-1 font-semibold text-ink">{String(value)}</p></div>; })}</div>
          <div className="mt-7 rounded-[1.5rem] border border-line p-4 sm:p-5"><div className="grid gap-4">{route.segments.map((segment, segmentIndex) => { const Icon = transportIcons[segment.transport_type]; return <div key={segment.id} className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center"><div className="rounded-2xl bg-cloud p-4"><p className="font-semibold text-ink">{segment.origin}</p><p className="text-sm text-muted">{dateTime(segment.departure_time)}</p></div><div className="flex items-center justify-center gap-2 text-muted sm:flex-col"><ArrowDown className="sm:hidden" size={18} /><Icon className="text-brand" size={22} /><span className="rounded-full bg-white px-3 py-1 text-xs font-semibold shadow-soft">{segment.number}</span>{segmentIndex < route.segments.length - 1 && <span className="text-xs font-medium text-aqua">пересадка</span>}</div><div className="rounded-2xl bg-cloud p-4"><p className="font-semibold text-ink">{segment.destination}</p><p className="text-sm text-muted">{dateTime(segment.arrival_time)} · {segment.available_seats} мест</p></div></div>; })}</div></div>
        </motion.article>)}
      </section>
    </div>

    <footer className="border-t border-line bg-white/80"><div className="mx-auto flex max-w-screen-2xl flex-col gap-3 px-5 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-12"><span className="font-semibold text-ink">Business Trip Planner</span><span>MVP · Mock Data · Internal Tool · 2026</span></div></footer>
  </main>;
}
