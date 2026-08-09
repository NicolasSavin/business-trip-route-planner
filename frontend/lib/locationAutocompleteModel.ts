import type { LocationSuggestion } from "@/lib/types";
import type { SelectedLocation } from "@/lib/locationPayload";

export const AUTOCOMPLETE_MIN_QUERY_LENGTH = 2;

export function canRequestSuggestions(query: string, selected: SelectedLocation) {
  return query.trim().length >= AUTOCOMPLETE_MIN_QUERY_LENGTH && !selected;
}

export function shouldKeepDropdownOpen(query: string, selected: SelectedLocation, focused: boolean) {
  return focused && canRequestSuggestions(query, selected);
}

export function nextActiveSuggestion(current: number, itemCount: number, direction: 1 | -1) {
  if (itemCount === 0) return -1;
  return direction === 1 ? Math.min(current + 1, itemCount - 1) : Math.max(current - 1, 0);
}

export function selectedLocationFromSuggestion(item: LocationSuggestion): NonNullable<SelectedLocation> {
  return {
    id: item.id,
    provider_code: item.provider_code,
    type: item.type,
    title: item.name,
    displayLabel: item.display_name,
  };
}

export function suggestionAccessibleLabel(item: LocationSuggestion, typeLabel: string) {
  return [item.display_name, item.region, typeLabel].filter(Boolean).join(" · ");
}
