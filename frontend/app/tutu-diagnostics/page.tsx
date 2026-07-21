"use client";

import { useState } from "react";
import { testTutuSearch } from "@/lib/api";
import type { TutuDiagnosticsResponse } from "@/lib/types";

export default function TutuDiagnosticsPage() {
  const [result, setResult] = useState<TutuDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSearch() {
    setLoading(true);
    try {
      setResult(await testTutuSearch());
      setError(null);
    } catch {
      setError("Tutu test search failed.");
    } finally {
      setLoading(false);
    }
  }

  return <main className="min-h-screen bg-cloud p-8 text-ink">
    <section className="mx-auto max-w-5xl rounded-[2rem] bg-white p-8 shadow-card">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand">Tutu Diagnostics</p>
      <h1 className="mt-2 text-3xl font-semibold">Tutu Playwright Provider</h1>
      <p className="mt-3 text-muted">Тест открывает tutu.ru в Playwright и выполняет только просмотр результатов поиска Москва → Санкт-Петербург на завтра.</p>
      <button onClick={runSearch} disabled={loading} className="mt-6 rounded-full bg-brand px-5 py-3 font-semibold text-white disabled:opacity-60">{loading ? "Searching..." : "Test Search"}</button>
      {error && <p className="mt-4 rounded-2xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {result && <div className="mt-6 space-y-4">
        <div className="text-sm text-muted">{result.origin} → {result.destination}, {result.date}</div>
        {result.routes.map((option) => option.route.segments.map((segment) => <article key={`${option.rank}-${segment.id}`} className="rounded-2xl border border-cloud p-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Поезд {segment.vehicle_number ?? segment.number}</h2><span className="font-semibold text-brand">{segment.price ? `${segment.price} ₽` : "Цена не найдена"}</span></div>
          <div className="mt-2 text-sm text-muted">{segment.origin_station} → {segment.destination_station} · {segment.departure_datetime ?? segment.departure_time} → {segment.arrival_datetime ?? segment.arrival_time}</div>
          <div className="mt-3 grid gap-2 md:grid-cols-4">{Object.entries(option.availability).map(([key, value]) => <div key={key} className="rounded-xl bg-cloud p-3"><div className="text-xs uppercase text-muted">{key}</div><div className="font-semibold">{String(value)}</div></div>)}</div>
          <div className="mt-3 text-sm">Тип вагона: {String(segment.metadata?.carriage_type ?? "Unknown")}</div>
        </article>))}
      </div>}
    </section>
  </main>;
}
