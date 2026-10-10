# WanderSync Travel Solutions

Plataforma de empaquetamiento turístico dinámico (vuelo + hotel + auto en una sola reserva). Parcial 2 de Patrones Arquitectónicos Avanzados. Autor: Santiago Prieto.

- **Documento técnico de arquitectura:** [`docs/arquitectura.pdf`](docs/arquitectura.pdf) (fuente: [`docs/arquitectura.md`](docs/arquitectura.md))
- **Guion de la demostración:** [`docs/guion-demo.md`](docs/guion-demo.md)
- **Diseño detallado y contrato GraphQL:** [`docs/design.md`](docs/design.md), [`docs/schema.graphql`](docs/schema.graphql)
- **Especificación, flujo por etapas y decisiones:** [`requirements.md`](requirements.md)
- **Evidencias de verificación por etapa y aprobaciones:** [`evidence/`](evidence/) (`gate-N/GATE.md`)
- **Enunciado:** [`context/`](context/)

## Inicio rápido

Requisitos: Docker con Compose v2 y unos 3 GB de RAM libres. Todo corre localmente; solo el scraping sale a internet.

```bash
cp .env.example .env
docker compose up -d        # o ./start.sh (agrega --build --wait e imprime las URLs)
```

| Servicio | URL |
|---|---|
| Aplicación | http://localhost:3000 |
| Gateway GraphQL (GraphiQL) | http://localhost:8000/graphql |
| Prefect (flujos de ingesta y SAGA) | http://localhost:4200 |
| Dask (workers y task stream) | http://localhost:8787 |

Cuenta administradora de demo: `admin@wandersync.co` / `WanderSync-Admin-2026` (definida en `.env.example`, valores solo locales). El administrador ve el panel «Simular fallo» al reservar y la página «Operaciones». Los viajeros se registran desde «Ingresar».

Primera carga de tarifas reales (si no se quiere esperar al cron de 6 h): página «Operaciones» → «Ejecutar ingesta», o:

```bash
docker compose exec -T ingestion prefect deployment run 'ingest-travel-offers/scheduled' --watch
```

## Pruebas

```bash
./scripts/e2e_all.sh /tmp/wandersync-e2e     # regresión completa (~12 min)
docker compose exec -T orders-billing-svc python - < scripts/simulate_saga.py   # solo los casos SAGA
./scripts/build_pdf.sh                        # regenera docs/arquitectura.pdf
```

## Estructura

```
docker-compose.yml   13 contenedores (healthchecks, arranque ordenado)
db/                  esquema por servicio, roles, vistas catalog (pg_graphql), datos semilla
ingestion/           flow Prefect + scrapers Selenium + limpieza (imagen de Dask scheduler/workers)
services/
  gateway/           GraphQL (Strawberry), sesiones, Argon2id, rate limiting
  orders-billing/    órdenes, pagos y la SAGA (flow Prefect)
  flights|hotels|cars/  participantes (reserve / cancel idempotentes)
  common/            utilidades compartidas
frontend/            Next.js + Apollo Client (UI en español)
scripts/             regresión, simulador SAGA, conciliación, informes, PDF
docs/ evidence/      documentación y evidencias
```

`./start.sh reset` borra la base de datos y el historial de Prefect (vuelve a sembrar datos con fechas frescas).
