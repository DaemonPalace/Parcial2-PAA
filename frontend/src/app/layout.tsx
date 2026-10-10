import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";
import { Providers } from "@/lib/apollo";
import { Header } from "@/components/header";

export const metadata: Metadata = {
  title: "WanderSync",
  description: "Paquetes turísticos dinámicos: vuelo + hotel + auto en una sola reserva",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <Providers>
          <Header />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-8">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
