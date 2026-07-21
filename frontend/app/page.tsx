'use client';

import { FormEvent, useMemo, useState } from 'react';
import { demoResponse } from '@/lib/demoData';
import type { RouteOption, RouteSearchResponse, RouteSegment, TransportType } from '@/lib/types';

const transportLabels: Record<TransportType, string> = { train: 'Поезд', bus: 'Автобус' };
const transportIcons: Record<TransportType, string> = { train: '🚆', bus: '🚌' };

type SearchState = 'demo' | 'api' | 'empty' | 'error';
type TimelinePoint =
  | { type: 'city'; label: string; meta: string }
  | { type: 'transport'; label: string; meta: string; icon: string };

function minutesLabel(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours} ч ${rest} мин`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
}

function segmentDuration(segment: RouteSegment) {
  const diff = new Date(segment.arrival_time).getTime() - new Date(segment.departure_time).getTime();
  return minutesLabel(Math.max(0, Math.round(diff / 60000)));
}

function routeBadge(route: RouteOption, index: number) {
  if (route.transfers_count === 0) return 'Без пересадок';
  if (index === 0) return 'Самый быстрый';
  return 'Оптимальный';
}

function Timeline({ route }: { route: RouteOption }) {
  const points: TimelinePoint[] = route.segments.flatMap((segment, index) => [
    { type: 'city', label: segment.origin, meta: index === 0 ? 'Старт маршрута' : 'Пересадка' },
    { type: 'transport', label: `${transportLabels[segment.transport_type]} ${segment.number}`, meta: `${dateTime(segment.departure_time)} → ${dateTime(segment.arrival_time)}`, icon: transportIcons[segment.transport_type] },
    ...(index === route.segments.length - 1 ? [{ type: 'city', label: segment.destination, meta: 'Пункт назначения' }] : []),
  ]);

  return <div className="timeline" aria-label="Timeline маршрута">
    {points.map((point, index) => <div className={`timelineItem ${point.type}`} key={`${point.label}-${index}`}>
      <div className="timelineMarker">{point.type === 'transport' ? point.icon : '●'}</div>
      <div><strong>{point.label}</strong><span>{point.meta}</span></div>
    </div>)}
  </div>;
}

function SkeletonResults() {
  return <section className="results" aria-label="Загрузка результатов">
    {[1, 2].map(item => <div className="card skeletonCard" key={item}>
      <div className="skeletonLine wide" /><div className="skeletonGrid"><span /><span /><span /></div><div className="skeletonLine" /><div className="skeletonLine short" />
    </div>)}
  </section>;
}

export default function Home() {
  const [routes, setRoutes] = useState<RouteOption[]>(demoResponse.routes);
  const [message, setMessage] = useState('Используются демонстрационные данные. При доступном backend будет выполнен API-запрос.');
  const [status, setStatus] = useState<SearchState>('demo');
  const [loading, setLoading] = useState(false);
  const [origin, setOrigin] = useState('Москва');
  const [destination, setDestination] = useState('Екатеринбург');

  const bestDuration = useMemo(() => Math.min(...routes.map(route => route.total_duration_minutes)), [routes]);

  function swapCities() {
    setOrigin(destination);
    setDestination(origin);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    const form = new FormData(event.currentTarget);
    const transport = String(form.get('transport'));
    const allowed_transport = transport === 'both' ? ['train', 'bus'] : [transport];
    const payload = {
      origin: form.get('origin'), destination: form.get('destination'), departure_date: form.get('departure_date'),
      passengers: Number(form.get('passengers')), allowed_transport, max_transfers: Number(form.get('max_transfers')),
      minimum_transfer_minutes: Number(form.get('minimum_transfer_minutes')),
    };

    try {
      const response = await fetch('http://localhost:8000/api/v1/routes/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error('Backend недоступен');
      const data = (await response.json()) as RouteSearchResponse;
      setRoutes(data.routes);
      setStatus(data.routes.length ? 'api' : 'empty');
      setMessage(data.routes.length ? 'Результаты получены из backend API.' : 'Маршрут не найден. Попробуйте изменить параметры поиска.');
    } catch {
      setRoutes(demoResponse.routes);
      setStatus('error');
      setMessage('Ошибка поиска: backend недоступен, поэтому показаны демонстрационные данные.');
    } finally {
      setLoading(false);
    }
  }

  return <main className="page">
    <section className="hero">
      <div className="heroContent"><span className="eyebrow">MVP · корпоративное планирование</span><h1>Business Trip Route Planner</h1><p>Поиск оптимального маршрута для командировок по России с учетом пересадок и доступности мест.</p><div className="heroStats"><span>🚆 Поезда</span><span>🚌 Автобусы</span><span>👥 Группы сотрудников</span></div></div>
      <div className="heroArt" aria-hidden="true"><svg viewBox="0 0 360 260" role="img"><path d="M39 184c50-64 100-96 151-96s93 32 131 96" fill="none" stroke="#b9d4ff" strokeWidth="18" strokeLinecap="round"/><rect x="73" y="78" width="184" height="86" rx="24" fill="#fff"/><path d="M96 102h137v35H96z" fill="#2563eb"/><circle cx="117" cy="172" r="17" fill="#0f172a"/><circle cx="213" cy="172" r="17" fill="#0f172a"/><path d="M271 135h43c16 0 29 13 29 29v19h-72z" fill="#38bdf8"/><circle cx="296" cy="190" r="14" fill="#0f172a"/><path d="M55 205h286" stroke="#d7e3f5" strokeWidth="10" strokeLinecap="round"/></svg></div>
    </section>

    <form className="searchCard" onSubmit={onSubmit}>
      <div className="searchHeader"><div><span className="eyebrow">Новый поиск</span><h2>Параметры командировки</h2></div><button className="swapButton" type="button" onClick={swapCities}>⇅ Поменять города</button></div>
      <div className="formGrid">
        <label className="field iconPin">Откуда<input name="origin" value={origin} onChange={event => setOrigin(event.target.value)} required /></label>
        <label className="field iconFlag">Куда<input name="destination" value={destination} onChange={event => setDestination(event.target.value)} required /></label>
        <label className="field iconCalendar">Дата<input name="departure_date" type="date" defaultValue="2026-08-10" required /></label>
        <label className="field iconUsers">Количество сотрудников<input name="passengers" type="number" min="1" defaultValue="2" required /></label>
        <label className="field iconTransport">Транспорт<select name="transport" defaultValue="both"><option value="both">Поезд и автобус</option><option value="train">Только поезд</option><option value="bus">Только автобус</option></select></label>
        <label className="field iconTransfer">Максимум пересадок<select name="max_transfers" defaultValue="1"><option value="0">0</option><option value="1">1</option></select></label>
        <label className="field iconClock">Минимальное время пересадки<input name="minimum_transfer_minutes" type="number" min="0" defaultValue="30" required /></label>
      </div>
      <div className="actions"><button className="primaryButton" disabled={loading}>{loading ? 'Ищем маршрут...' : 'Найти оптимальный маршрут'}</button><span className={`hint ${status}`}>{message}</span></div>
    </form>

    {loading ? <SkeletonResults /> : <section className="results">
      <div className="sectionTitle"><span className="eyebrow">Результаты</span><h2>Подходящие маршруты</h2></div>
      {routes.length === 0 ? <div className="card empty"><div>🧭</div><h3>Маршрут не найден</h3><p>Попробуйте увеличить максимум пересадок, изменить дату или выбрать оба типа транспорта.</p></div> : routes.map((route, index) => <article className="card resultCard" key={route.id}>
        <div className="cardHeader"><div><span className="routeBadge">{route.total_duration_minutes === bestDuration ? routeBadge(route, index) : 'Оптимальный'}</span><h3>{route.origin} → {route.destination}</h3></div><span className={`statusBadge ${route.is_available_for_group ? 'ok' : 'warn'}`}>{route.is_available_for_group ? 'Доступно для группы' : 'Недостаточно мест'}</span></div>
        <div className="metrics"><span>🚆 Поезд</span><span>🚌 Автобус</span><span>🕘 Время: {dateTime(route.segments[0].departure_time)}</span><span>🔁 Пересадки: {route.transfers_count}</span><span>👥 Мест: {Math.min(...route.segments.map(segment => segment.available_seats))}</span><span>⏱ Общее время: {minutesLabel(route.total_duration_minutes)}</span></div>
        <Timeline route={route} />
        <div className="segments">{route.segments.map(segment => <div className="segment" key={segment.id}><strong>{transportIcons[segment.transport_type]} {transportLabels[segment.transport_type]} · {segment.number}</strong><span>{segment.origin} → {segment.destination}</span><span>{segmentDuration(segment)} · доступно мест: {segment.available_seats}</span></div>)}</div>
      </article>)}
    </section>}

    <footer className="footer"><span>Версия MVP</span><span>Mock Data</span><span>Внутренний сервис команды</span></footer>
  </main>;
}
