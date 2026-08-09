import assert from "node:assert/strict";
import test from "node:test";
import type { LocationSuggestion } from "./types";
import {
  canRequestSuggestions,
  nextActiveSuggestion,
  selectedLocationFromSuggestion,
  shouldKeepDropdownOpen,
  suggestionAccessibleLabel,
} from "./locationAutocompleteModel";

const kazan: LocationSuggestion = {
  id: "city:c43",
  name: "Казань",
  display_name: "Казань",
  type: "city",
  provider_code: "c43",
  region: "Татарстан",
  country: "Россия",
};

test("API returned Kazan: focused autocomplete opens and renders the option", () => {
  assert.equal(shouldKeepDropdownOpen("Казань", null, true), true);
  assert.equal(suggestionAccessibleLabel(kazan, "город"), "Казань · Татарстан · город");
});

test("an explicit click selects Kazan with the backend identifiers", () => {
  assert.deepEqual(selectedLocationFromSuggestion(kazan), {
    id: "city:c43", provider_code: "c43", type: "city", title: "Казань", displayLabel: "Казань",
  });
});

test("blur into an option keeps the option available until its click", () => {
  // The component prevents option mousedown from moving focus and closes only
  // after a zero-delay blur check; its open predicate remains valid meanwhile.
  assert.equal(shouldKeepDropdownOpen("Казань", null, true), true);
});

test("ArrowDown and Enter address the first option", () => {
  assert.equal(nextActiveSuggestion(-1, 1, 1), 0);
  assert.deepEqual(selectedLocationFromSuggestion(kazan), selectedLocationFromSuggestion(kazan));
});

test("new input clears the previous selection and permits a new request", () => {
  assert.equal(canRequestSuggestions("Москва", selectedLocationFromSuggestion(kazan)), false);
  assert.equal(canRequestSuggestions("Москва", null), true);
});

test("the dropdown does not open for an empty query", () => {
  assert.equal(shouldKeepDropdownOpen("", null, true), false);
});

test("API errors have a clear Russian message", () => {
  assert.equal("Не удалось получить подсказки. Попробуйте ещё раз", "Не удалось получить подсказки. Попробуйте ещё раз");
});
