"use client";

import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Building2, Loader2, MapPin, TrainFront, X } from "lucide-react";
import { suggestLocations } from "@/lib/api";
import type { LocationSuggestion } from "@/lib/types";
import type { SelectedLocation } from "@/lib/locationPayload";

const typeLabels: Record<LocationSuggestion["type"], string> = {
  city: "Город",
  settlement: "Город",
  railway_station: "ЖД вокзал",
  bus_station: "Автовокзал",
  station: "Станция",
};

function LocationIcon({ type }: { type: LocationSuggestion["type"] }) {
  const Icon = type === "city" || type === "settlement" ? Building2 : type === "railway_station" ? TrainFront : MapPin;
  return <Icon size={17} className="shrink-0 text-brand" />;
}

function Highlight({ text, query }: { text: string; query: string }) {
  const index = text.toLowerCase().replace("ё", "е").indexOf(query.toLowerCase().replace("ё", "е"));
  if (index < 0 || !query) return <>{text}</>;
  return <>{text.slice(0, index)}<mark className="rounded bg-aqua/20 px-0.5 text-ink">{text.slice(index, index + query.length)}</mark>{text.slice(index + query.length)}</>;
}

export type { SelectedLocation } from "@/lib/locationPayload";

export function LocationAutocomplete({ label, value, selected, onChange, onSelect, required }: {
  label: string;
  value: string;
  selected: SelectedLocation;
  onChange: (value: string) => void;
  onSelect: (location: SelectedLocation, displayName: string) => void;
  required?: boolean;
}) {
  const baseId = useId();
  const rootRef = useRef<HTMLLabelElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [items, setItems] = useState<LocationSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [active, setActive] = useState(-1);
  const showHint = value.trim().length > 0 && !selected;

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  useEffect(() => {
    abortRef.current?.abort();
    setError(false);
    setHasSearched(false);
    setActive(-1);
    if (value.trim().length < 2) {
      setItems([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const response = await suggestLocations(value, 8, controller.signal);
        setItems(response.items);
        setHasSearched(true);
        setOpen(true);
      } catch (err) {
        if (!controller.signal.aborted) {
          setItems([]);
          setHasSearched(true);
          setError(true);
          setOpen(true);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  function pick(item: LocationSuggestion) {
    onSelect({ id: item.id, provider_code: item.provider_code, type: item.type, title: item.name, displayLabel: item.display_name }, item.display_name);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { setOpen(false); return; }
    if (event.key === "Tab") { setOpen(false); return; }
    if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) setOpen(true);
    if (event.key === "ArrowDown") { event.preventDefault(); setActive((current) => Math.min(current + 1, items.length - 1)); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActive((current) => Math.max(current - 1, 0)); }
    if (event.key === "Enter" && active >= 0 && items[active]) { event.preventDefault(); pick(items[active]); }
  }

  const stateText = value.trim().length < 2 ? "Начните вводить название города или станции" : loading || !hasSearched ? "Ищем варианты…" : error ? "Сервис подсказок временно недоступен" : items.length ? "Выберите город, регион и конкретную станцию" : "Ничего не найдено";

  return (
    <label ref={rootRef} className="relative space-y-2 text-sm font-semibold text-ink">
      {label}
      <div className="relative">
        <input
          className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 pr-10 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10"
          value={value}
          onChange={(e) => { onChange(e.target.value); onSelect(null, e.target.value); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          required={required}
          role="combobox"
          aria-expanded={open}
          aria-controls={`${baseId}-listbox`}
          aria-activedescendant={active >= 0 ? `${baseId}-option-${active}` : undefined}
          aria-autocomplete="list"
        />
        {loading ? <Loader2 className="absolute right-3 top-3.5 animate-spin text-muted" size={18} /> : value ? <button type="button" aria-label="Очистить поле" onClick={() => { onSelect(null, ""); onChange(""); }} className="absolute right-3 top-3.5 text-muted hover:text-ink"><X size={18} /></button> : null}
      </div>
      {showHint && <p className="text-xs font-medium text-muted">Выберите вариант из списка для более точного поиска</p>}
      {open && <div id={`${baseId}-listbox`} role="listbox" className="absolute z-30 mt-2 w-full overflow-hidden rounded-2xl border border-line bg-white shadow-card">
        <div className="border-b border-line px-4 py-2 text-xs font-semibold text-muted">{stateText}</div>
        {!loading && !error && items.map((item, index) => <button key={item.id} id={`${baseId}-option-${index}`} role="option" aria-selected={active === index} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(item)} className={`flex w-full items-start gap-3 px-4 py-3 text-left transition ${active === index ? "bg-sky-50" : "hover:bg-cloud"}`}>
          <LocationIcon type={item.type} />
          <span><span className="block font-semibold text-ink"><Highlight text={item.display_name} query={value} /></span><span className="text-xs font-medium text-muted">{typeLabels[item.type]}{item.region ? ` · ${item.region}` : ""}{item.provider_code ? ` · ${item.provider_code}` : ""}</span></span>
        </button>)}
      </div>}
    </label>
  );
}
