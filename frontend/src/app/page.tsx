"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLazyQuery, useMutation, useQuery } from "@apollo/client/react";
import { BedDouble, Car, Loader2, Plane, Search, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BOOK, CITIES, ME, SEARCH, requestError, type Me, type UserError } from "@/lib/gql";
import { SOURCE_LABEL, isoDay, money, time } from "@/lib/format";
import { cn } from "@/lib/utils";

type Flight = { id: string; airline: string; departAt: string; arriveAt: string | null; durationMinutes: number | null; stops: number | null; priceCop: number; seatsAvailable: number; source: string };
type Hotel = { id: string; name: string; rating: number | null; priceTotalCop: number; roomsAvailable: number; source: string };
type CarOffer = { id: string; vendor: string; model: string; category: string | null; priceTotalCop: number; unitsAvailable: number; source: string };
type SearchResult = {
  packageAvailability: {
    flights: Flight[]; hotels: Hotel[]; cars: CarOffer[];
    cheapestPackage: { totalCop: number; flight: { id: string }; hotel: { id: string }; car: { id: string } } | null;
  };
};

const selectCls = "h-9 w-full rounded-md border border-input bg-card px-3 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none";

function addDays(iso: string, n: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function Option({ selected, onSelect, children }: { selected: boolean; onSelect: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "w-full rounded-md border p-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        selected ? "border-primary bg-accent" : "border-border bg-card hover:bg-secondary"
      )}
    >
      {children}
    </button>
  );
}

function Source({ s }: { s: string }) {
  return <span className="text-xs text-muted-foreground">{SOURCE_LABEL[s] ?? s}</span>;
}

export default function SearchPage() {
  const router = useRouter();
  const { data: citiesData } = useQuery<{ cities: { code: string; name: string }[] }>(CITIES);
  const { data: meData } = useQuery<{ me: Me }>(ME);
  const me = meData?.me;

  // Defaults match the scraping plan (+7 days, 3 nights) so the demo shows live-scraped offers.
  const [form, setForm] = useState({ origin: "BOG", destination: "CTG", departDate: isoDay(7), returnDate: isoDay(10) });
  const [search, { data, loading, error }] = useLazyQuery<SearchResult>(SEARCH, { fetchPolicy: "network-only" });
  const [pick, setPick] = useState<{ flight?: string; hotel?: string; car?: string }>({});
  const [chaos, setChaos] = useState({ failAt: "", mode: "REJECT", flaky: false });
  const [book, { loading: booking }] = useMutation<{ bookPackage: { order: { id: string } | null; userErrors: UserError[] } }>(BOOK);
  const [errors, setErrors] = useState<UserError[]>([]);

  const result = data?.packageAvailability;
  useEffect(() => {
    const c = result?.cheapestPackage;
    setPick(c ? { flight: c.flight.id, hotel: c.hotel.id, car: c.car.id } : {});
  }, [result]);

  // One idempotency key per selection: a double click or a network retry can't book twice.
  const idempotencyKey = useMemo(() => crypto.randomUUID(), [pick.flight, pick.hotel, pick.car]);

  const flight = result?.flights.find((f) => f.id === pick.flight);
  const hotel = result?.hotels.find((h) => h.id === pick.hotel);
  const car = result?.cars.find((c) => c.id === pick.car);
  const total = (flight?.priceCop ?? 0) + (hotel?.priceTotalCop ?? 0) + (car?.priceTotalCop ?? 0);

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    setErrors([]);
    await search({ variables: { input: form } });
  }

  async function onBook() {
    if (!flight || !hotel || !car) return;
    setErrors([]);
    const input: Record<string, unknown> = { idempotencyKey, flightOfferId: flight.id, hotelOfferId: hotel.id, carOfferId: car.id };
    if (me?.role === "ADMIN" && chaos.failAt) {
      input.chaos = { failAt: chaos.failAt, mode: chaos.mode, flakyCompensation: chaos.flaky };
    }
    try {
      const payload = (await book({ variables: { input } })).data?.bookPackage;
      if (payload?.order) router.push(`/reservas/${payload.order.id}`);
      else setErrors(payload?.userErrors ?? []);
    } catch (err) {
      setErrors([{ code: "ERROR", message: requestError(err) }]);
    }
  }

  const cities = citiesData?.cities ?? [];
  const maxReturn = addDays(form.departDate, 7);

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Arma tu paquete</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Vuelo + hotel + auto en una sola reserva. Si una parte falla, revertimos todo y te reembolsamos.
        </p>
      </section>

      <Card>
        <CardContent>
          <form onSubmit={onSearch} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="origin">Origen</Label>
              <select id="origin" className={selectCls} value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })}>
                {cities.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="destination">Destino</Label>
              <select id="destination" className={selectCls} value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })}>
                {cities.filter((c) => c.code !== form.origin).map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="depart">Ida</Label>
              <Input id="depart" type="date" required min={isoDay(1)} value={form.departDate}
                onChange={(e) => setForm({ ...form, departDate: e.target.value, returnDate: addDays(e.target.value, 3) })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="return">Regreso (máx. 7 noches)</Label>
              <Input id="return" type="date" required min={addDays(form.departDate, 1)} max={maxReturn} value={form.returnDate}
                onChange={(e) => setForm({ ...form, returnDate: e.target.value })} />
            </div>
            <Button type="submit" disabled={loading || form.origin === form.destination}>
              {loading ? <Loader2 className="animate-spin" /> : <Search />} Buscar
            </Button>
          </form>
        </CardContent>
      </Card>

      {error && <p role="alert" className="text-sm text-destructive">{error.message}</p>}

      {result && (
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <div className="grid gap-6 md:grid-cols-3">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Plane className="size-4" /> Vuelos</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-2">
                {result.flights.length === 0 && <p className="text-sm text-muted-foreground">Sin vuelos para esa fecha.</p>}
                {result.flights.map((f) => (
                  <Option key={f.id} selected={pick.flight === f.id} onSelect={() => setPick({ ...pick, flight: f.id })}>
                    <div className="flex justify-between font-medium"><span>{f.airline}</span><span>{money(f.priceCop)}</span></div>
                    <div className="text-muted-foreground">
                      {time(f.departAt)}{f.arriveAt && ` → ${time(f.arriveAt)}`} · {f.stops ? `${f.stops} escala(s)` : "Directo"}
                      {f.durationMinutes && ` · ${Math.floor(f.durationMinutes / 60)} h ${f.durationMinutes % 60} min`}
                    </div>
                    <Source s={f.source} />
                  </Option>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><BedDouble className="size-4" /> Hoteles</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-2">
                {result.hotels.length === 0 && <p className="text-sm text-muted-foreground">Sin hoteles para esas fechas.</p>}
                {result.hotels.map((h) => (
                  <Option key={h.id} selected={pick.hotel === h.id} onSelect={() => setPick({ ...pick, hotel: h.id })}>
                    <div className="font-medium">{h.name}</div>
                    <div className="flex justify-between text-muted-foreground">
                      <span>{h.rating ? `★ ${h.rating.toFixed(1)}` : "Sin calificación"}</span><span className="font-medium text-foreground">{money(h.priceTotalCop)}</span>
                    </div>
                    <Source s={h.source} />
                  </Option>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Car className="size-4" /> Autos</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-2">
                {result.cars.length === 0 && <p className="text-sm text-muted-foreground">Sin autos para esas fechas.</p>}
                {result.cars.map((c) => (
                  <Option key={c.id} selected={pick.car === c.id} onSelect={() => setPick({ ...pick, car: c.id })}>
                    <div className="flex justify-between font-medium"><span>{c.model}</span><span>{money(c.priceTotalCop)}</span></div>
                    <div className="text-muted-foreground">{c.vendor}{c.category && ` · ${c.category}`}</div>
                    <Source s={c.source} />
                  </Option>
                ))}
              </CardContent>
            </Card>
          </div>

          <Card className="h-fit lg:sticky lg:top-6">
            <CardHeader><CardTitle className="text-base">Tu paquete</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <dl className="flex flex-col gap-1">
                <div className="flex justify-between"><dt className="text-muted-foreground">Vuelo</dt><dd>{flight ? money(flight.priceCop) : "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-muted-foreground">Hotel</dt><dd>{hotel ? money(hotel.priceTotalCop) : "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-muted-foreground">Auto</dt><dd>{car ? money(car.priceTotalCop) : "—"}</dd></div>
                <div className="mt-2 flex justify-between border-t border-border pt-2 text-base font-semibold"><dt>Total</dt><dd>{money(total)}</dd></div>
              </dl>

              {me?.role === "ADMIN" && (
                <fieldset className="flex flex-col gap-2 rounded-md border border-dashed border-state-compensating-fg/50 bg-state-compensating-bg/40 p-3">
                  <legend className="flex items-center gap-1 px-1 text-xs font-semibold text-state-compensating-fg">
                    <ShieldAlert className="size-3.5" /> Simular fallo (admin)
                  </legend>
                  <Label htmlFor="failAt" className="text-xs">Paso que falla</Label>
                  <select id="failAt" className={selectCls} value={chaos.failAt} onChange={(e) => setChaos({ ...chaos, failAt: e.target.value })}>
                    <option value="">Ninguno (camino feliz)</option>
                    <option value="PAYMENT">Pago</option>
                    <option value="FLIGHT">Vuelo</option>
                    <option value="HOTEL">Hotel</option>
                    <option value="CAR">Auto</option>
                  </select>
                  <Label htmlFor="mode" className="text-xs">Tipo de fallo</Label>
                  <select id="mode" className={selectCls} value={chaos.mode} disabled={!chaos.failAt} onChange={(e) => setChaos({ ...chaos, mode: e.target.value })}>
                    <option value="REJECT">Rechazo</option>
                    <option value="TIMEOUT">Timeout (confirmación perdida)</option>
                  </select>
                  <label className="flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={chaos.flaky} disabled={!chaos.failAt} onChange={(e) => setChaos({ ...chaos, flaky: e.target.checked })} />
                    La primera compensación de cada servicio falla
                  </label>
                </fieldset>
              )}

              {me ? (
                <Button onClick={onBook} disabled={!flight || !hotel || !car || booking}>
                  {booking && <Loader2 className="animate-spin" />} Reservar paquete
                </Button>
              ) : (
                <Button asChild><Link href="/ingresar">Ingresa para reservar</Link></Button>
              )}
              {errors.map((e) => <p key={e.code + e.message} role="alert" className="text-destructive">{e.message}</p>)}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
