"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@apollo/client/react";
import { BedDouble, Car, CheckCircle2, CircleDashed, CreditCard, Loader2, Plane, RotateCcw, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge, TERMINAL } from "@/components/status-badge";
import { ORDER } from "@/lib/gql";
import { dateTime, day, money, shortId, time } from "@/lib/format";
import { cn } from "@/lib/utils";

type Step = { name: string; action: string; status: string; error: string | null; startedAt: string; endedAt: string | null };
type Order = {
  id: string; status: string; totalCop: number; failureReason: string | null; createdAt: string; steps: Step[];
  flight: { airline: string; origin: string; destination: string; departAt: string; priceCop: number } | null;
  hotel: { name: string; city: string; checkIn: string; checkOut: string; priceTotalCop: number } | null;
  car: { vendor: string; model: string; pickupDate: string; dropoffDate: string; priceTotalCop: number } | null;
};

const STEPS = [
  { name: "PAYMENT", label: "Cobro", undo: "Reembolso", icon: CreditCard },
  { name: "FLIGHT", label: "Vuelo", undo: "Cancelar vuelo", icon: Plane },
  { name: "HOTEL", label: "Hotel", undo: "Cancelar hotel", icon: BedDouble },
  { name: "CAR", label: "Auto", undo: "Cancelar auto", icon: Car },
];
const META = Object.fromEntries(STEPS.map((s) => [s.name, s]));

const BANNER: Record<string, { cls: string; text: string }> = {
  PENDING: { cls: "bg-state-pending-bg text-state-pending-fg", text: "Reserva registrada. Iniciando la transacción…" },
  RUNNING: { cls: "bg-state-running-bg text-state-running-fg", text: "Cobrando y reservando cada componente…" },
  COMPENSATING: { cls: "bg-state-compensating-bg text-state-compensating-fg", text: "Un paso falló. Revirtiendo lo ya reservado en orden inverso…" },
  CONFIRMED: { cls: "bg-state-success-bg text-state-success-fg", text: "¡Listo! Vuelo, hotel y auto confirmados." },
  CANCELLED: { cls: "bg-state-compensated-bg text-state-compensated-fg", text: "No pudimos completar el paquete: todo fue cancelado y el cobro reembolsado." },
  REJECTED: { cls: "bg-state-failed-bg text-state-failed-fg", text: "El pago fue rechazado. No se reservó nada." },
};

/** Saga errors are technical ("StepTimeout: …"); travelers get a plain explanation, the raw text stays in the tooltip. */
function friendly(error: string | null): string {
  if (!error) return "";
  if (error.includes("StepTimeout")) return "Sin confirmación a tiempo (timeout de red)";
  if (error.includes("payment declined")) return "Pago rechazado";
  if (error.includes("StepRejected")) return "El proveedor rechazó la reserva";
  if (error.includes("interrupted") || error.includes("recovered_after_crash")) return "Interrumpido por una caída del orquestador";
  return "Error temporal";
}

function StepIcon({ status }: { status?: string }) {
  if (status === "RUNNING") return <Loader2 className="size-4 animate-spin text-state-running-fg" aria-label="en curso" />;
  if (status === "SUCCEEDED") return <CheckCircle2 className="size-4 text-state-success-fg" aria-label="ok" />;
  if (status === "FAILED") return <XCircle className="size-4 text-state-failed-fg" aria-label="falló" />;
  return <CircleDashed className="size-4 text-muted-foreground" aria-label="pendiente" />;
}

export default function TrackerPage() {
  const { id } = useParams<{ id: string }>();
  const { data, loading, stopPolling } = useQuery<{ order: Order | null }>(ORDER, {
    variables: { id }, pollInterval: 1000, fetchPolicy: "network-only",
  });
  const order = data?.order;
  if (order && TERMINAL.has(order.status)) stopPolling();

  if (loading && !order) return <Skeleton className="h-64 w-full" />;
  if (!order) return <p className="text-sm text-muted-foreground">Reserva no encontrada.</p>;

  const forward = Object.fromEntries(order.steps.filter((s) => s.action === "FORWARD").map((s) => [s.name, s]));
  const compensations = order.steps.filter((s) => s.action === "COMPENSATE");
  const banner = BANNER[order.status];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Reserva {shortId(order.id)}</h1>
          <p className="text-sm text-muted-foreground">{dateTime(order.createdAt)} · {money(order.totalCop)}</p>
        </div>
        <StatusBadge status={order.status} className="text-sm" />
      </div>

      <div role="status" aria-live="polite" className={cn("flex items-center gap-2 rounded-md px-4 py-3 text-sm font-medium", banner.cls)}>
        {!TERMINAL.has(order.status) && <Loader2 className="size-4 animate-spin" />}
        {banner.text}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Transacción (SAGA)</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <ol className="flex flex-col gap-2">
              {STEPS.map(({ name, label, icon: Icon }) => {
                const s = forward[name];
                return (
                  <li key={name} className="flex items-start gap-3 text-sm">
                    <StepIcon status={s?.status} />
                    <Icon className="size-4 text-muted-foreground" aria-hidden />
                    <div className="flex-1">
                      <div className="font-medium">{label}</div>
                      {s?.error && <div className="text-xs text-state-failed-fg" title={s.error}>{friendly(s.error)}</div>}
                    </div>
                    {s && <span className="text-xs text-muted-foreground">{time(s.startedAt)}</span>}
                  </li>
                );
              })}
            </ol>

            {compensations.length > 0 && (
              <div className="border-t border-border pt-4">
                <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-state-compensating-fg">
                  <RotateCcw className="size-4" /> Compensaciones (orden inverso)
                </h2>
                <ol className="flex flex-col gap-2">
                  {compensations.map((s, i) => (
                    <li key={i} className="flex items-start gap-3 text-sm">
                      <StepIcon status={s.status} />
                      <div className="flex-1">
                        <div>{META[s.name]?.undo ?? s.name}</div>
                        {s.status === "FAILED" && <div className="text-xs text-state-failed-fg" title={s.error ?? ""}>Falló ({friendly(s.error)}); se reintentó automáticamente</div>}
                      </div>
                      <span className="text-xs text-muted-foreground">{time(s.startedAt)}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Tu paquete</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            {order.flight && (
              <div className="flex justify-between gap-2">
                <div><div className="font-medium">{order.flight.airline} · {order.flight.origin} → {order.flight.destination}</div>
                  <div className="text-muted-foreground">{dateTime(order.flight.departAt)}</div></div>
                <span>{money(order.flight.priceCop)}</span>
              </div>
            )}
            {order.hotel && (
              <div className="flex justify-between gap-2">
                <div><div className="font-medium">{order.hotel.name}</div>
                  <div className="text-muted-foreground">{day(order.hotel.checkIn)} – {day(order.hotel.checkOut)}</div></div>
                <span>{money(order.hotel.priceTotalCop)}</span>
              </div>
            )}
            {order.car && (
              <div className="flex justify-between gap-2">
                <div><div className="font-medium">{order.car.model} · {order.car.vendor}</div>
                  <div className="text-muted-foreground">{day(order.car.pickupDate)} – {day(order.car.dropoffDate)}</div></div>
                <span>{money(order.car.priceTotalCop)}</span>
              </div>
            )}
            <div className="flex justify-between border-t border-border pt-2 font-semibold"><span>Total</span><span>{money(order.totalCop)}</span></div>
            {order.failureReason && <p className="text-xs text-muted-foreground" title={order.failureReason}>Motivo: {friendly(order.failureReason) === "Error temporal" ? order.failureReason : friendly(order.failureReason)}</p>}
          </CardContent>
        </Card>
      </div>

      <Link href="/reservas" className="text-sm text-primary underline-offset-4 hover:underline">← Mis reservas</Link>
    </div>
  );
}
