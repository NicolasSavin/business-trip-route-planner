import React, { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LocationSuggestResponse } from "@/lib/types";
import type { SelectedLocation } from "@/lib/locationPayload";

const { suggestLocations } = vi.hoisted(() => ({ suggestLocations: vi.fn() }));
vi.mock("@/lib/api", () => ({ suggestLocations }));
import { LocationAutocomplete } from "./LocationAutocomplete";

const kazan: LocationSuggestResponse = { items: [{ id: "city:c43", name: "Казань", display_name: "Казань, Республика Татарстан (train/bus)", type: "city", provider_code: "c43", region: "Республика Татарстан", country: "Россия" }] };

function Harness() {
  const [value, setValue] = useState("");
  const [selected, setSelected] = useState<SelectedLocation>(null);
  return <><LocationAutocomplete label="Куда" value={value} selected={selected} onChange={setValue}
    onSelect={(location, displayName) => { setSelected(location); setValue(displayName); }} />
    <output data-testid="provider-code">{selected?.provider_code ?? ""}</output></>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe("LocationAutocomplete mounted in DOM", () => {
  it("keeps a loading dropdown visible for delayed API and selects Kazan by mouse", async () => {
    const pending = deferred<LocationSuggestResponse>();
    suggestLocations.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole("combobox", { name: "Куда" }), "Казань");
    expect(await screen.findByRole("listbox")).not.toBeNull();
    expect(screen.getByText("Ищем варианты…")).not.toBeNull();
    pending.resolve(kazan);
    await user.click(await screen.findByRole("option", { name: /Казань/ }));
    expect(screen.getByTestId("provider-code")).toHaveProperty("textContent", "c43");
  });

  it("selects Kazan with ArrowDown and Enter", async () => {
    suggestLocations.mockResolvedValue(kazan);
    const user = userEvent.setup(); render(<Harness />);
    const input = screen.getByRole("combobox", { name: "Куда" });
    await user.type(input, "Казань");
    await screen.findByRole("option", { name: /Казань/ });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByTestId("provider-code")).toHaveProperty("textContent", "c43");
  });

  it("aborts a stale request and never replaces the newer result", async () => {
    const old = deferred<LocationSuggestResponse>();
    suggestLocations.mockReturnValueOnce(old.promise).mockResolvedValueOnce(kazan);
    const user = userEvent.setup(); render(<Harness />);
    const input = screen.getByRole("combobox", { name: "Куда" });
    await user.type(input, "Ка");
    await waitFor(() => expect(suggestLocations).toHaveBeenCalledTimes(1));
    await user.type(input, "зань");
    expect(await screen.findByRole("option", { name: /Казань/ })).not.toBeNull();
    expect(suggestLocations.mock.calls[0][2].aborted).toBe(true);
    old.resolve({ items: [{ ...kazan.items[0], id: "city:old", display_name: "Старый ответ", provider_code: "old" }] });
    await waitFor(() => expect(screen.queryByText("Старый ответ")).toBeNull());
  });

  it("retries after a network error", async () => {
    suggestLocations.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(kazan);
    const user = userEvent.setup(); render(<Harness />);
    await user.type(screen.getByRole("combobox", { name: "Куда" }), "Казань");
    await user.click(await screen.findByRole("button", { name: "Повторить запрос" }));
    expect(await screen.findByRole("option", { name: /Казань/ })).not.toBeNull();
    expect(suggestLocations).toHaveBeenCalledTimes(2);
  });
});
