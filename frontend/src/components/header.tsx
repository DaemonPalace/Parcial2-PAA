"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@apollo/client/react";
import { Plane } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LOGOUT, ME, type Me } from "@/lib/gql";

export function Header() {
  const router = useRouter();
  const { data, client } = useQuery<{ me: Me }>(ME);
  const [logout] = useMutation(LOGOUT);
  const me = data?.me;

  async function handleLogout() {
    await logout();
    await client.resetStore();
    router.push("/");
  }

  return (
    <header className="border-b border-border bg-card">
      <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 md:px-8">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-primary">
          <Plane className="size-5" aria-hidden /> WanderSync
        </Link>
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">Buscar paquete</Link>
        {me && <Link href="/reservas" className="text-sm text-muted-foreground hover:text-foreground">Mis reservas</Link>}
        {me?.role === "ADMIN" && (
          <Link href="/admin" className="text-sm text-muted-foreground hover:text-foreground">Operaciones</Link>
        )}
        <div className="ml-auto flex items-center gap-3 text-sm">
          {me ? (
            <>
              <span className="hidden text-muted-foreground sm:inline">
                {me.email}
                {me.role === "ADMIN" && <span className="ml-1 rounded bg-accent px-1.5 py-0.5 text-xs text-accent-foreground">admin</span>}
              </span>
              <Button variant="outline" size="sm" onClick={handleLogout}>Cerrar sesión</Button>
            </>
          ) : (
            <Button asChild size="sm"><Link href="/ingresar">Ingresar</Link></Button>
          )}
        </div>
      </nav>
    </header>
  );
}
