"use client";

import { KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Building2, Loader2, MapPin, TrainFront, X } from "lucide-react";
import { suggestLocations } from "@/lib/api";
import type { LocationSuggestion } from "@/lib/types";
import type { SelectedLocation } from "@/lib/locationPayload";
import { canRequestSuggestions, nextActiveSuggestion, selectedLocationFromSuggestion, suggestionAccessibleLabel } from "@/lib/locationAutocompleteModel";

const typeLabels: Record<LocationSuggestion["type"], string> = {
  city: "город",
  settlement: "город",
  railway_station: "ж/д вокзал",
  bus_station: "автовокзал",
  station: "станция",
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
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestRef = useRef(0);
  const focusedRef = useRef(false);
  const [items, setItems] = useState<LocationSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);
  const [active, setActive] = useState(-1);
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});
  const query = value.trim();
  const canSuggest = canRequestSuggestions(query, selected);
  const showHint = query.length > 0 && !selected;

  const positionDropdown = useCallback(() => {
    const rect = inputRef.current?.getBoundingClientRect();
    if (rect) setDropdownStyle({ left: rect.left, top: rect.bottom + 8, width: rect.width });
  }, []);

  useEffect(() => {
    const closeOnOutsidePointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !dropdownRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsidePointer);
    return () => document.removeEventListener("mousedown", closeOnOutsidePointer);
  }, []);

  useEffect(() => {
    if (!open) return;
    positionDropdown();
    window.addEventListener("resize", positionDropdown);
    window.addEventListener("scroll", positionDropdown, true);
    return () => {
      window.removeEventListener("resize", positionDropdown);
      window.removeEventListener("scroll", positionDropdown, true);
    };
  }, [open, positionDropdown]);

  useEffect(() => {
    const requestId = ++requestRef.current;
    abortRef.current?.abort();
    setError(false);
    setHasSearched(false);
    setActive(-1);

    if (!canSuggest) {
      setItems([]);
      setLoading(false);
      setOpen(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    if (focusedRef.current) setOpen(true);
    const timer = window.setTimeout(async () => {
      try {
        const response = await suggestLocations(query, 8, controller.signal);
        if (requestRef.current !== requestId || controller.signal.aborted) return;
        setItems(response.items);
        setHasSearched(true);
        if (focusedRef.current) setOpen(true);
      } catch {
        if (requestRef.current !== requestId || controller.signal.aborted) return;
        setItems([]);
        setHasSearched(true);
        setError(true);
        if (focusedRef.current) setOpen(true);
      } finally {
        if (requestRef.current === requestId && !controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [canSuggest, query, retryNonce]);

  function pick(item: LocationSuggestion) {
    onSelect(selectedLocationFromSuggestion(item), item.display_name);
    setItems([]);
    setOpen(false);
    setActive(-1);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" || event.key === "Tab") { setOpen(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (canSuggest) setOpen(true);
      setActive((current) => nextActiveSuggestion(current, items.length, event.key === "ArrowDown" ? 1 : -1));
    }
    if (event.key === "Enter" && open && active >= 0 && items[active]) { event.preventDefault(); pick(items[active]); }
  }

  const stateText = loading || !hasSearched ? "Ищем варианты…" : error ? "Не удалось получить подсказки. Попробуйте ещё раз" : items.length ? "Выберите город или станцию" : "Ничего не найдено";
  const dropdown = open && canSuggest ? (
    <div ref={dropdownRef} id={`${baseId}-listbox`} role="listbox" style={dropdownStyle} className="fixed z-[100] max-h-80 overflow-y-auto rounded-2xl border border-line bg-white shadow-card">
      <div role="status" className="border-b border-line px-4 py-2 text-xs font-semibold text-muted">{stateText}</div>
      {error && <button type="button" className="w-full px-4 py-3 text-left text-sm font-semibold text-brand hover:bg-cloud" onMouseDown={(event) => event.preventDefault()} onClick={() => setRetryNonce((value) => value + 1)}>Повторить запрос</button>}
      {!loading && !error && items.map((item, index) => (
        <button key={item.id} id={`${baseId}-option-${index}`} role="option" aria-selected={active === index} type="button" onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActive(index)} onClick={() => pick(item)} className={`flex w-full items-start gap-3 px-4 py-3 text-left transition ${active === index ? "bg-sky-50" : "hover:bg-cloud"}`}>
          <LocationIcon type={item.type} />
          <span className="font-semibold text-ink" aria-label={suggestionAccessibleLabel(item, typeLabels[item.type])}><Highlight text={item.display_name} query={query} />{item.region ? ` · ${item.region}` : ""} · {typeLabels[item.type]}</span>
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div ref={rootRef} className="relative space-y-2 text-sm font-semibold text-ink">
      <label htmlFor={`${baseId}-input`}>{label}</label>
      <div className="relative">
        <input ref={inputRef} id={`${baseId}-input`} className="w-full rounded-2xl border border-line bg-cloud px-4 py-3 pr-10 outline-none transition focus:border-brand focus:bg-white focus:ring-4 focus:ring-brand/10" value={value}
          data-selected-provider-code={selected?.provider_code ?? ""}
          onChange={(event) => { onChange(event.target.value); if (selected) onSelect(null, event.target.value); }}
          onFocus={() => { focusedRef.current = true; if (canSuggest) setOpen(true); }}
          onBlur={(event) => { focusedRef.current = false; if (!dropdownRef.current?.contains(event.relatedTarget as Node)) window.setTimeout(() => setOpen(false), 0); }}
          onKeyDown={onKeyDown} required={required} role="combobox" aria-expanded={open && canSuggest} aria-controls={`${baseId}-listbox`} aria-activedescendant={active >= 0 ? `${baseId}-option-${active}` : undefined} aria-autocomplete="list" />
        {loading ? <Loader2 className="absolute right-3 top-3.5 animate-spin text-muted" size={18} /> : value ? <button type="button" aria-label="Очистить поле" onClick={() => { onSelect(null, ""); onChange(""); inputRef.current?.focus(); }} className="absolute right-3 top-3.5 text-muted hover:text-ink"><X size={18} /></button> : null}
      </div>
      {showHint && <p className="text-xs font-medium text-muted">Выберите вариант из списка для более точного поиска</p>}
      {typeof document !== "undefined" && dropdown ? createPortal(dropdown, document.body) : null}
    </div>
  );
}
