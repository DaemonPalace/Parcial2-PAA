const cop = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const BOGOTA = "America/Bogota";

export const money = (v: number) => cop.format(v);

export const time = (iso: string) =>
  new Intl.DateTimeFormat("es-CO", { timeStyle: "short", timeZone: BOGOTA }).format(new Date(iso));

export const dateTime = (iso: string) =>
  new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeStyle: "short", timeZone: BOGOTA }).format(new Date(iso));

/** "2026-10-17" (a calendar date, no time zone) -> "17 oct 2026" */
export const day = (isoDate: string) =>
  new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(isoDate + "T00:00:00Z"));

export const isoDay = (offsetDays: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toLocaleDateString("en-CA", { timeZone: BOGOTA }); // YYYY-MM-DD
};

export const shortId = (id: string) => `${id.slice(0, 8)}…`;

export const SOURCE_LABEL: Record<string, string> = {
  google_flights: "Google Flights",
  booking: "Booking.com",
  booking_cars: "Booking.com Cars",
  seed: "Catálogo base",
};
