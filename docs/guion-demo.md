# Guion de demostración (≈ 12 min)

Cubre los cuatro puntos exigidos por el enunciado (§6): **(a)** Prefect monitoreando los flujos, **(b)** tareas distribuidas en Dask, **(c)** el frontend consumiendo la API GraphQL y **(d)** un fallo transaccional con compensaciones SAGA. Sirve igual para la sustentación en vivo y para la grabación de respaldo (Q-23).

## Preparación (15 min antes)

```bash
cd wandersync
cp -n .env.example .env
./start.sh                      # docker compose up -d --build --wait: 13 contenedores healthy
docker compose exec -T ingestion prefect deployment run 'ingest-travel-offers/scheduled' --watch
```

- La ingesta previa (≈ 2,5 min) deja ofertas reales y frescas de Google Flights, Booking.com y Booking.com Cars para **Bogotá → Cartagena, ida +7 días, 3 noches**.
- Abrir cuatro pestañas:
  1. http://localhost:3000 (app)
  2. http://localhost:4200 (Prefect)
  3. http://localhost:8787/status (Dask)
  4. http://localhost:8000/graphql (GraphiQL)
- Iniciar sesión en la app como **admin@wandersync.co / WanderSync-Admin-2026**.
- **Plan B:** si un sitio real bloquea el scraping ese día, el catálogo base (seed) mantiene la búsqueda y la reserva funcionando. Explicarlo como la política de éxito parcial (AC-04.3).

## Guion

| Min | Pantalla | Qué hacer | Qué decir |
|---|---|---|---|
| 0:00 | `docs/arquitectura.pdf`, diagrama de componentes | Mostrar el diagrama | 13 contenedores con un solo `docker compose up`. Gateway GraphQL como única entrada. Cuatro microservicios con un esquema y un rol propios. SAGA orquestada por Prefect. Ingesta en Dask. |
| 1:00 | App, Buscar | BOG → CTG, fechas por defecto, **Buscar** | Una sola query GraphQL trae vuelos, hoteles, autos y el paquete más barato. Las etiquetas «Google Flights / Booking.com» indican ofertas extraídas de sitios reales. |
| 2:00 | GraphiQL | Ejecutar la query de la sección «Consultas para GraphiQL» | **(c)** Sin over-fetching: el gateway traduce la selección a **un** documento `pg_graphql` con solo las columnas pedidas. Mostrar la línea `pg_graphql round-trip` con `docker compose logs gateway --tail 3`. |
| 3:00 | App | Reservar el paquete sin simular fallo | **Camino feliz:** cobro → vuelo → hotel → auto, en vivo. Termina en «Confirmada». |
| 4:00 | Prefect → Runs → `order-…` | Abrir el flow run del camino feliz | **(a)** Cada paso de la SAGA es una task de Prefect. |
| 4:30 | App, Buscar | Panel «Simular fallo (admin)»: paso **Auto**, tipo **Rechazo**. **Reservar** | **(d)** Fallo en el auto: compensaciones en orden inverso (cancelar auto → hotel → vuelo → reembolso). Termina en «Cancelada y reembolsada». |
| 5:30 | Prefect, el flow run de esa orden | Señalar la task roja `reserve_CAR` y las compensaciones verdes | La compensación es automática, sin intervención manual. |
| 6:00 | App | Repetir con paso **Hotel**, tipo **Timeout (confirmación perdida)** | El escenario de «reservas huérfanas» del enunciado: el hotel **sí** reservó, pero la confirmación se perdió. La cancelación encuentra la reserva y la libera. |
| 7:00 | App | Paso **Auto** y marcar «La primera compensación de cada servicio falla» | Cada cancelación falla una vez y Prefect la reintenta con backoff: resiliencia de las compensaciones. |
| 8:00 | App → **Operaciones** → **Ejecutar ingesta**, luego la pestaña Dask | Mirar el Task Stream y el panel Progress | **(b)** 28 tareas de scraping con Selenium repartidas en 3 workers de Dask. |
| 9:00 | Prefect → Runs → `ingest-travel-offers` | Abrir el run en curso | **(a)** Retries explícitos (3, backoff exponencial 10/20/40 s con jitter), artefacto `ingestion-summary`, programación cron cada 6 h. |
| 10:00 | Terminal | `docker compose exec -T postgres psql -U supabase_admin -d postgres -f - < scripts/reconcile.sql` | Consistencia eventual comprobada: 0 reservas huérfanas, 0 cobros retenidos. |
| 10:30 | `evidence/gate-4/GATE.md`, sección Security | Mostrar AC-08.2 y AC-08.4 | Rotación del ID de sesión al iniciar sesión (anti session fixation), Argon2id, rate limiting (429), auditoría de dependencias: `next` crítico detectado y corregido. |
| 11:30 | Cierre | | Resumen de la rúbrica y dónde está la evidencia (`evidence/`). |

## Consultas para GraphiQL

```graphql
query Paquete {
  packageAvailability(input: {origin: "BOG", destination: "CTG", departDate: "AAAA-MM-DD", returnDate: "AAAA-MM-DD"}) {
    flights(limit: 3) { airline departAt priceCop source }
    cheapestPackage { totalCop hotel { name } car { model } }
  }
}
```

Reemplazar las fechas por **hoy + 7** y **hoy + 10**. Luego quitar campos y volver a ejecutar para mostrar que el documento `pg_graphql` del log también se reduce.

## Fallos simulados disponibles

| Panel «Simular fallo» | Resultado esperado |
|---|---|
| Ninguno | Confirmada |
| Pago | Rechazada (no hay nada que compensar) |
| Vuelo / Hotel / Auto, tipo Rechazo | Cancelada y reembolsada, compensaciones en orden inverso |
| Hotel, tipo Timeout | Igual, pero la reserva del hotel sí se había confirmado (orphan booking) y se libera |
| Cualquiera + «primera compensación falla» | Cada cancelación falla una vez y Prefect la reintenta |

Caída del orquestador (opcional, desde la terminal): reservar con fallo **Hotel / Timeout** y, durante el paso del hotel, ejecutar `docker compose kill orders-billing-svc && docker compose up -d orders-billing-svc`. Al arrancar, la recuperación compensa la orden (AC-06.10).

## Límites del demo

Rate limits: 5 logins por minuto por IP y 5 reservas por minuto por usuario. Si se reserva muchas veces seguidas, esperar un minuto.
