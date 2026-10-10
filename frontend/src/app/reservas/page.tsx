"use client";

import Link from "next/link";
import { useQuery } from "@apollo/client/react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/status-badge";
import { MY_ORDERS } from "@/lib/gql";
import { dateTime, money, shortId } from "@/lib/format";

type Row = { id: string; status: string; totalCop: number; createdAt: string;
  flight: { origin: string; destination: string; departAt: string } | null; hotel: { name: string } | null };

export default function MyOrdersPage() {
  const { data, loading } = useQuery<{ myOrders: Row[] }>(MY_ORDERS, { fetchPolicy: "network-only" });

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Mis reservas</h1>
      {loading && <Skeleton className="h-32 w-full" />}
      {data?.myOrders.length === 0 && (
        <p className="text-sm text-muted-foreground">Aún no tienes reservas. <Link className="text-primary underline" href="/">Busca un paquete</Link>.</p>
      )}
      <div className="flex flex-col gap-3">
        {data?.myOrders.map((o) => (
          <Link key={o.id} href={`/reservas/${o.id}`} className="focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 rounded-xl">
            <Card className="transition-colors hover:bg-secondary">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <div>
                  <div className="font-medium">
                    {o.flight ? `${o.flight.origin} → ${o.flight.destination}` : "Paquete"} · {o.hotel?.name ?? ""}
                  </div>
                  <div className="text-muted-foreground">{shortId(o.id)} · {dateTime(o.createdAt)}</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-medium">{money(o.totalCop)}</span>
                  <StatusBadge status={o.status} />
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
