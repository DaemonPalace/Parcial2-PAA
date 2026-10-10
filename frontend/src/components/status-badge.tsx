import { cn } from "@/lib/utils";

const STYLES: Record<string, { cls: string; label: string }> = {
  PENDING: { cls: "bg-state-pending-bg text-state-pending-fg", label: "Pendiente" },
  RUNNING: { cls: "bg-state-running-bg text-state-running-fg", label: "En curso" },
  CONFIRMED: { cls: "bg-state-success-bg text-state-success-fg", label: "Confirmada" },
  COMPENSATING: { cls: "bg-state-compensating-bg text-state-compensating-fg", label: "Compensando" },
  CANCELLED: { cls: "bg-state-compensated-bg text-state-compensated-fg", label: "Cancelada y reembolsada" },
  REJECTED: { cls: "bg-state-failed-bg text-state-failed-fg", label: "Rechazada" },
  SUCCEEDED: { cls: "bg-state-success-bg text-state-success-fg", label: "OK" },
  FAILED: { cls: "bg-state-failed-bg text-state-failed-fg", label: "Falló" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = STYLES[status] ?? { cls: "bg-state-pending-bg text-state-pending-fg", label: status };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", s.cls, className)}>
      {s.label}
    </span>
  );
}

export const TERMINAL = new Set(["CONFIRMED", "CANCELLED", "REJECTED"]);
