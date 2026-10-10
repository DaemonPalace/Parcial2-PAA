# WanderSync Travel Solutions

Plataforma de empaquetamiento turístico dinámico (vuelo + hotel + auto) — Parcial 2, Patrones Arquitectónicos Avanzados.

Autor: Santiago Prieto.

- Enunciado: [`context/`](context/)
- Especificación, flujo por etapas y decisiones: [`requirements.md`](requirements.md)
- Diseño (diagramas, SAGA, modelo de datos, contrato GraphQL): [`docs/design.md`](docs/design.md), [`docs/schema.graphql`](docs/schema.graphql)
- Evidencias de verificación por etapa: [`evidence/`](evidence/)

## Inicio rápido

```bash
cp .env.example .env
docker compose up -d        # o: ./start.sh
```

| Servicio | URL |
|---|---|
| Aplicación (frontend) | http://localhost:3000 |
| Gateway GraphQL (GraphiQL) | http://localhost:8000/graphql |
| Prefect UI (flujos de ingesta y SAGA) | http://localhost:4200 |
| Dask dashboard (workers, task stream) | http://localhost:8787 |

Cuenta administradora de demo (creada al iniciar el gateway, ver `.env.example`): `admin@wandersync.co` / `WanderSync-Admin-2026`. Solo el administrador ve el panel «Simular fallo» al reservar y la página «Operaciones» (ingesta manual). Los viajeros se registran desde «Ingresar».

`./start.sh reset` borra la base de datos y el historial de Prefect (vuelve a sembrar datos con fechas frescas).
