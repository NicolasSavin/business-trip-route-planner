import { expect, test } from "@playwright/test";

test("selects Kazan and sends both strict placement requirements", async ({ page }) => {
  await page.route("**/api/v1/locations/suggest**", async route => route.fulfill({ json: { items: [{
    id: "city:c43", name: "Казань", display_name: "Казань, Республика Татарстан (train/bus)",
    type: "city", provider_code: "c43", region: "Республика Татарстан", country: "Россия",
  }] } }));
  let payload: Record<string, any> | undefined;
  await page.route("**/api/v1/routes/search", async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ json: { routes: [], partially_confirmed_routes: [], rejected_routes: [], warnings: [], search_summary: {} } });
  });

  await page.goto("/");
  const destination = page.getByRole("combobox", { name: "Куда" });
  await destination.clear();
  await destination.fill("Казань");
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.getByRole("option", { name: /Казань/ }).click();
  await expect(destination).toHaveAttribute("data-selected-provider-code", "c43");
  await page.getByRole("button", { name: /Найти маршрут/ }).click();
  await expect.poll(() => payload).toBeTruthy();
  expect(payload?.destination_provider_code).toBe("c43");
  expect(payload?.seat_preferences).toMatchObject({ berth_preference: "lower_only", require_same_compartment: true, require_same_carriage: true });
});
