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
| Gateway GraphQL | http://localhost:8000/graphql |
| Prefect UI | http://localhost:4200 |
| Dask dashboard | http://localhost:8787 |

`./start.sh reset` borra la base de datos y el historial de Prefect (vuelve a sembrar datos con fechas frescas).
