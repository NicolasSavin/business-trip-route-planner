import { strict as assert } from "node:assert";
import { filterHotels, rubles, type Hotel } from "./hotels";

const rows: Hotel[] = [
  { id: 1, name: "Причал", locality: "Мамадыш", address: "Набережная", photo_url: "", report_amount: 3500, actual_price: null, notes: "" },
  { id: 2, name: "Уют", locality: "Пермь", address: "Объездная", photo_url: "", report_amount: 4000, actual_price: null, notes: "" },
];
assert.deepEqual(filterHotels(rows, "  мамаДЫШ ").map(row => row.id), [1]);
assert.deepEqual(filterHotels(rows, "объездная").map(row => row.id), [2]);
assert.equal(rubles(3500).replace(/\s/g, " "), "3 500 ₽");
assert.equal(rubles(null), "Не указана");
console.log("hotel helpers passed");
