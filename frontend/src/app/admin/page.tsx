"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@apollo/client/react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ME, TRIGGER_INGESTION, requestError, type Me } from "@/lib/gql";

export default function AdminPage() {
  const { data } = useQuery<{ me: Me }>(ME);
  const [trigger, { loading }] = useMutation<{ triggerIngestion: { id: string; state: string } }>(TRIGGER_INGESTION);
  const [msg, setMsg] = useState("");

  if (data && data.me?.role !== "ADMIN") return <p className="text-sm text-muted-foreground">Solo para administradores.</p>;

  async function run() {
    setMsg("");
    try {
      const r = (await trigger()).data?.triggerIngestion;
      setMsg(r ? `Ingesta programada (flow run ${r.id.slice(0, 8)}…, estado ${r.state}). Síguela en Prefect.` : "");
    } catch (err) {
      setMsg(requestError(err));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Operaciones</h1>
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Ingesta de tarifas</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            <p className="text-muted-foreground">
              Ejecuta ahora el scraping de Google Flights, Booking.com y Booking.com Cars en el clúster Dask
              (normalmente corre cada 6 horas).
            </p>
            <Button onClick={run} disabled={loading} className="self-start">
              <RefreshCw /> {loading ? "Programando…" : "Ejecutar ingesta"}
            </Button>
            {msg && <p role="status">{msg}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Observabilidad</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <a className="flex items-center gap-2 text-primary hover:underline" href="http://localhost:4200" target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" /> Prefect: flujos de ingesta y SAGA
            </a>
            <a className="flex items-center gap-2 text-primary hover:underline" href="http://localhost:8787" target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" /> Dask: workers y task stream
            </a>
            <p className="mt-2 text-muted-foreground">
              Para simular fallos SAGA, usa el panel «Simular fallo (admin)» al reservar un paquete.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
