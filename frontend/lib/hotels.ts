export type Hotel = { id: number; name: string; locality: string; address: string; photo_url: string; report_amount: number; actual_price: number | null; notes: string };

export const filterHotels = (hotels: Hotel[], query: string) => {
  const normalized = query.trim().toLocaleLowerCase("ru");
  return hotels.filter((hotel) => !normalized || [hotel.name, hotel.locality, hotel.address].some((value) => value.toLocaleLowerCase("ru").includes(normalized)));
};

export const rubles = (amount: number | null) => amount === null ? "Не указана" : `${new Intl.NumberFormat("ru-RU").format(amount)} ₽`;
