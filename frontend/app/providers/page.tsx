"use client";

import { useEffect, useState } from "react";
import { disableProvider, enableProvider, listProviders } from "@/lib/api";
import type { ProviderRegistration } from "@/lib/types";

function readinessLabel(provider: ProviderRegistration) {
  const label = provider.metadata?.status_label;
  if (typeof label === "string") return label;
  return provider.metadata?.ready_to_connect ? "готов к подключению" : "—";
}

export default function ProvidersPage() {
  const [providers, setProviders] = useState<ProviderRegistration[]>([]);
  const [error, setError] = useState<string | null>(null);

  function capabilityLabels(provider: ProviderRegistration) {
    const capabilities = [
      [provider.capabilities.supports_schedule, "расписание"],
      [provider.capabilities.supports_availability, "наличие мест"],
      [provider.capabilities.supports_carriages, "вагоны"],
      [provider.capabilities.supports_place_map, "схема мест"],
      [provider.capabilities.supports_compartment_rules, "правила купе"],
      [provider.capabilities.supports_gender_restrictions, "ограничения пола"],
    ];
    return capabilities.filter(([enabled]) => enabled).map(([, label]) => label).join(", ") || "—";
  }

  async function load() {
    try {
      setProviders(await listProviders());
      setError(null);
    } catch {
      setError("Не удалось загрузить источники данных.");
    }
  }

  useEffect(() => { void load(); }, []);

  async function toggle(provider: ProviderRegistration) {
    try {
      const updated = provider.enabled ? await disableProvider(provider.id) : await enableProvider(provider.id);
      setProviders((items) => items.map((item) => item.id === updated.id ? updated : item));
      setError(null);
    } catch {
      setError("Не удалось изменить статус источника данных. Проверьте, настроен ли партнёрский доступ.");
    }
  }

  return <main className="min-h-screen bg-cloud p-8 text-ink">
    <section className="mx-auto max-w-6xl rounded-[2rem] bg-white p-8 shadow-card">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-brand">Unified Transport Provider</p>
          <h1 className="mt-2 text-3xl font-semibold">Источники данных</h1>
        </div>
        <button onClick={load} className="rounded-full bg-brand px-5 py-2 font-semibold text-white">Обновить</button>
      </div>
      {error && <p className="mt-4 rounded-2xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-muted"><tr><th>Источник</th><th>Тип</th><th>Приоритет</th><th>Статус</th><th>Готовность</th><th>Возможности</th><th>Настроен</th><th>Включён</th><th>Маршрутов</th><th>Последняя проверка</th><th></th></tr></thead>
          <tbody>{providers.map((provider) => <tr key={provider.id} className="border-t border-cloud">
            <td className="py-4 font-semibold">{provider.name}<div className="text-xs text-muted">{provider.id}</div></td>
            <td>{provider.capabilities.supported_transport.join(", ")}</td>
            <td>{provider.priority}</td>
            <td><span className="rounded-full bg-cloud px-3 py-1">{provider.enabled ? provider.health : "disabled"}</span></td>
            <td>{readinessLabel(provider)}</td>
            <td><div>{capabilityLabels(provider)}</div>{provider.id === "tutu" && <div className="mt-1 text-xs text-muted">Требуется партнёрский доступ · Реальные запросы не выполняются · Адаптер подготовлен</div>}</td>
            <td>{provider.metadata?.configured ? "Да" : "Нет"}</td>
            <td>{provider.enabled ? "Да" : "Нет"}</td>
            <td>{provider.routes_found}</td>
            <td>{provider.last_checked_at ? new Date(provider.last_checked_at).toLocaleString("ru-RU") : "—"}</td>
            <td><button onClick={() => toggle(provider)} className="rounded-full bg-ink px-4 py-2 text-white">{provider.enabled ? "Выключить" : "Включить"}</button></td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  </main>;
}
