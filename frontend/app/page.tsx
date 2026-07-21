'use client';

import { FormEvent, useState } from 'react';
import { demoResponse } from '@/lib/demoData';
import type { RouteOption, RouteSearchResponse, TransportType } from '@/lib/types';

const transportLabels: Record<TransportType, string> = { train: 'Поезд', bus: 'Автобус' };

function minutesLabel(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours} ч ${rest} мин`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
}

export default function Home() {
  const [routes, setRoutes] = useState<RouteOption[]>(demoResponse.routes);
  const [message, setMessage] = useState('Показаны демонстрационные данные. При доступном backend будет выполнен API-запрос.');
  const [loading, setLoading] = useState(false);

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
      setMessage(data.routes.length ? 'Результаты получены из backend API.' : 'Маршрут не найден. Попробуйте изменить параметры поиска.');
    } catch {
      setRoutes(demoResponse.routes);
      setMessage('Backend недоступен, поэтому показаны демонстрационные данные.');
    } finally {
      setLoading(false);
    }
  }

  return <main className="page">
    <section className="hero"><h1>Поиск маршрута для командировки</h1><p>Внутренний MVP для подбора поездов и автобусов по mock-данным.</p></section>
    <form className="panel" onSubmit={onSubmit}>
      <div className="grid">
        <label className="field">Откуда<input name="origin" defaultValue="Москва" required /></label>
        <label className="field">Куда<input name="destination" defaultValue="Екатеринбург" required /></label>
        <label className="field">Дата<input name="departure_date" type="date" defaultValue="2026-08-10" required /></label>
        <label className="field">Количество сотрудников<input name="passengers" type="number" min="1" defaultValue="2" required /></label>
        <label className="field">Транспорт<select name="transport" defaultValue="both"><option value="both">поезд и автобус</option><option value="train">поезд</option><option value="bus">автобус</option></select></label>
        <label className="field">Максимум пересадок<select name="max_transfers" defaultValue="1"><option value="0">0</option><option value="1">1</option></select></label>
        <label className="field">Мин. время пересадки, мин<input name="minimum_transfer_minutes" type="number" min="0" defaultValue="30" required /></label>
      </div>
      <div className="actions"><button className="button" disabled={loading}>{loading ? 'Ищем...' : 'Найти маршрут'}</button><span className="hint">{message}</span></div>
    </form>
    <section className="results">{routes.length === 0 ? <div className="card empty">Маршрут не найден.</div> : routes.map(route => <article className="card" key={route.id}>
      <div className="cardHeader"><div><h2>{route.origin} → {route.destination}</h2><div className="meta"><span>Пересадок: {route.transfers_count}</span><span>В пути: {minutesLabel(route.total_duration_minutes)}</span>{route.transfer_city && <span>Пересадка: {route.transfer_city}, {minutesLabel(route.transfer_duration_minutes ?? 0)}</span>}</div></div><span className={`badge ${route.is_available_for_group ? '' : 'warn'}`}>{route.is_available_for_group ? 'Доступно для группы' : 'Недостаточно мест'}</span></div>
      <div className="segments">{route.segments.map(segment => <div className="segment" key={segment.id}><strong>{transportLabels[segment.transport_type]} · {segment.number}</strong><div>{segment.origin} → {segment.destination}</div><div className="meta"><span>{dateTime(segment.departure_time)} — {dateTime(segment.arrival_time)}</span><span>Доступно мест: {segment.available_seats}</span></div></div>)}</div>
    </article>)}</section>
  </main>;
}
