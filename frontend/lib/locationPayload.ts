import type { LocationSuggestion, LocationType, RouteSearchPayload, TransportType } from "@/lib/types";

export type SelectedLocation = (Pick<LocationSuggestion, "id" | "provider_code" | "type"> & {
  title: string;
  displayLabel: string;
}) | null;

export type RouteFormState = {
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

const uiSuffixPattern = /\s*\((?:train|bus|train\/bus|поезд|автобус|поезд\/автобус)\)\s*$/i;

export function cleanLocationSearchValue(value: string) {
  return value.replace(uiSuffixPattern, "").trim();
}

function locationTitle(selected: SelectedLocation, fallback: string) {
  return selected?.title?.trim() || cleanLocationSearchValue(fallback);
}

function locationProviderCode(selected: SelectedLocation) {
  return selected?.provider_code ?? null;
}

function locationId(selected: SelectedLocation) {
  return selected?.id ?? null;
}

function locationType(selected: SelectedLocation): LocationType | null {
  return selected?.type ?? null;
}

export function buildRouteSearchPayload(formState: RouteFormState): RouteSearchPayload {
  const allowed_transport: TransportType[] =
    formState.transport === "both" ? ["train", "bus"] : [formState.transport];
  return {
    origin: locationTitle(formState.originLocation, formState.origin),
    destination: locationTitle(formState.destinationLocation, formState.destination),
    origin_location_id: locationId(formState.originLocation),
    origin_provider_code: locationProviderCode(formState.originLocation),
    origin_location_type: locationType(formState.originLocation),
    destination_location_id: locationId(formState.destinationLocation),
    destination_provider_code: locationProviderCode(formState.destinationLocation),
    destination_location_type: locationType(formState.destinationLocation),
    departure_date: formState.departure_date,
    passengers: formState.passengers,
    allowed_transport,
    allowed_transport_types: allowed_transport,
    max_transfers: formState.max_transfers,
    minimum_transfer_minutes: formState.minimum_transfer_minutes,
    maximum_transfer_minutes: formState.maximum_transfer_minutes,
    strict_availability: formState.strict_availability,
    preferred_classes: formState.same_compartment ? ["coupe"] : [],
    seat_policy_scope: "every_rail_segment",
    seat_preferences: {
      preferred_classes: formState.same_compartment ? ["coupe"] : [],
      berth_preference: formState.lower_only ? "lower_only" : "any",
      require_same_compartment: formState.same_compartment,
      require_same_carriage: true,
      allow_split_group: false,
      maximum_compartments: formState.same_compartment ? 1 : null,
      strict_preferences: true,
    },
    require_group_together: true,
    allow_split_group: false,
  };
}
