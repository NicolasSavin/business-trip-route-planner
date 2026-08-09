"use client";

import { FormEvent, useEffect, useState } from "react";
import { Building2, LogOut, Pencil, Search, X } from "lucide-react";
import { ApiError, currentUser, Hotel, listHotels, login, logout, SessionUser, updateHotel } from "@/lib/api";

const fields: { key: keyof Omit<Hotel, "id">; label: string; kind?: string }[] = [
  { key: "name", label: "Название" }, { key: "report_amount", label: "Для отчёта", kind: "number" },
  { key: "actual_price", label: "Фактическое проживание", kind: "number" }, { key: "city", label: "Город" },
  { key: "address", label: "Адрес" }, { key: "phone", label: "Телефон" }, { key: "website", label: "Сайт" },
  { key: "photo_url", label: "Фото (URL)" }, { key: "notes", label: "Примечание" },
];
const money = (value: number | null) => value === null ? "—" : `${new Intl.NumberFormat("ru-RU").format(value)} ₽`;

export default function HotelsPage() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [hotels, setHotels] = useState<Hotel[]>([]);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Hotel | null>(null);
  const [error, setError] = useState("");

  const load = async (query = search) => { try { setHotels(await listHotels(query)); } catch { setError("Не удалось загрузить гостиницы"); } };
  useEffect(() => { currentUser().then(value => { setUser(value); return listHotels(); }).then(setHotels).catch(() => {}).finally(() => setAuthChecked(true)); }, []);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); const data = new FormData(event.currentTarget);
    try { const value = await login(String(data.get("username")), String(data.get("password"))); setUser(value); await load(""); }
    catch { setError("Неверный логин или пароль"); }
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!editing) return; const data = new FormData(event.currentTarget);
    const payload = { ...editing, report_amount: Number(data.get("report_amount")), actual_price: data.get("actual_price") === "" ? null : Number(data.get("actual_price")) };
    for (const { key } of fields) if (!["report_amount", "actual_price"].includes(key)) Object.assign(payload, { [key]: String(data.get(key) ?? "") });
    try { const saved = await updateHotel(editing.id, payload); setHotels(items => items.map(item => item.id === saved.id ? saved : item)); setEditing(null); }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 403 ? "Редактирование доступно только администратору" : "Не удалось сохранить изменения"); }
  }

  if (!authChecked) return <main className="grid min-h-screen place-items-center text-slate-500">Загрузка…</main>;
  if (!user) return <main className="grid min-h-screen place-items-center bg-slate-50 p-5"><form onSubmit={authenticate} className="w-full max-w-md rounded-[2rem] border border-slate-200 bg-white p-8 shadow-xl"><Building2 className="mb-5 h-10 w-10 text-blue-600"/><h1 className="text-3xl font-bold">Гостиницы</h1><p className="mt-2 text-slate-500">Войдите, чтобы открыть защищённый справочник.</p><input name="username" required autoComplete="username" placeholder="Логин" className="mt-7 w-full rounded-xl border p-3"/><input name="password" required type="password" autoComplete="current-password" placeholder="Пароль" className="mt-3 w-full rounded-xl border p-3"/>{error && <p className="mt-3 text-sm text-rose-600">{error}</p>}<button className="mt-5 w-full rounded-xl bg-blue-600 p-3 font-semibold text-white">Войти</button></form></main>;

  return <main className="min-h-screen bg-slate-50 px-5 py-8 sm:px-8"><div className="mx-auto max-w-7xl"><header className="flex flex-wrap items-center justify-between gap-4"><div><a href="/" className="text-sm font-semibold text-blue-600">← Маршруты</a><h1 className="mt-2 text-4xl font-bold">Гостиницы</h1><p className="mt-2 text-slate-500">Справочник проживания для командировок · {hotels.length}</p></div><button onClick={async()=>{await logout();setUser(null)}} className="flex items-center gap-2 rounded-xl border bg-white px-4 py-3"><LogOut size={18}/>Выйти</button></header>
    <form onSubmit={e=>{e.preventDefault();load()}} className="relative mt-8 max-w-xl"><Search className="absolute left-4 top-3.5 text-slate-400" size={20}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Поиск по названию гостиницы" className="w-full rounded-2xl border bg-white py-3 pl-12 pr-4 shadow-sm"/></form>{error && <p className="mt-4 text-rose-600">{error}</p>}
    <section className="mt-6 grid gap-5 lg:grid-cols-2">{hotels.map(hotel=><article key={hotel.id} className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><div className="flex justify-between gap-3"><h2 className="text-xl font-bold">{hotel.name}</h2>{user.is_admin && <button onClick={()=>setEditing({...hotel})} className="flex items-center gap-2 text-sm font-semibold text-blue-600"><Pencil size={16}/>Редактировать</button>}</div><dl className="mt-5 grid gap-x-5 gap-y-4 sm:grid-cols-2">{fields.slice(1).map(({key,label})=><div key={key} className={key === "notes" ? "sm:col-span-2" : ""}><dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label.replace(" (URL)","")}</dt><dd className="mt-1 break-words text-sm">{key === "report_amount" || key === "actual_price" ? money(hotel[key] as number|null) : String(hotel[key] || "—")}</dd></div>)}</dl></article>)}</section>{!hotels.length && <p className="mt-16 text-center text-slate-500">Ничего не найдено</p>}
  </div>{editing && <div className="fixed inset-0 z-20 overflow-y-auto bg-slate-950/50 p-4"><form onSubmit={save} className="mx-auto my-8 max-w-2xl rounded-3xl bg-white p-6 shadow-2xl"><div className="flex justify-between"><h2 className="text-2xl font-bold">Редактировать гостиницу</h2><button type="button" onClick={()=>setEditing(null)} aria-label="Отмена"><X/></button></div><div className="mt-6 grid gap-4 sm:grid-cols-2">{fields.map(({key,label,kind})=><label key={key} className={key === "notes" ? "sm:col-span-2" : ""}><span className="text-sm font-semibold">{label}</span>{key === "notes" ? <textarea name={key} defaultValue={String(editing[key]??"")} className="mt-1 min-h-24 w-full rounded-xl border p-3"/> : <input name={key} type={kind} min={kind ? 0 : undefined} required={key==="name"||key==="report_amount"} defaultValue={editing[key]??""} className="mt-1 w-full rounded-xl border p-3"/>}</label>)}</div><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={()=>setEditing(null)} className="rounded-xl border px-5 py-3 font-semibold">Отмена</button><button className="rounded-xl bg-blue-600 px-5 py-3 font-semibold text-white">Сохранить</button></div></form></div>}</main>;
}
