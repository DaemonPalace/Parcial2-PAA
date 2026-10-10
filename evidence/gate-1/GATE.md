# Gate G1 — Stages 00–03 — Gate report

**Date:** 2026-10-09 · **Commits:** `1e656a0` (00) · `51cae23` (01) · `87c2843` (02) · stage-03 commit (this report is part of it) · **Status:** approved 2026-10-09

## Built

**Stage 00: Decisions & repo bootstrap**
- `requirements.md` §9 answered (D-001…D-009), `.gitignore` (lockfiles tracked), `.env.example`, `README.md`, `context/`.

**Stage 01: Architecture & design spec**
- `docs/design.md`: component/deployment diagram, order state machine, 8 SAGA sequence diagrams (happy path, payment/flight/hotel/car failure, lost-confirmation timeout, flaky compensation, idempotent replay, crash recovery), ER model, schema/role matrix, internal REST contracts, ingestion design and retry tables, security design (session rotation, Argon2id params, rate-limit table), ADR-01…09, traceability.
- `docs/schema.graphql`: public GraphQL contract.

**Stage 02: Infrastructure skeleton**
- `docker-compose.yml`: 12 containers, every one has a healthcheck and starts in `service_healthy` order. Host ports are bound to `127.0.0.1` only: 8000 gateway, 4200 Prefect, 8787 Dask.
- One Dockerfile per service (`services/*/Dockerfile`, `ingestion/Dockerfile`). Images run as a non-root user, and dependencies are pinned in each `requirements.txt`.
- Dask: 1 scheduler and 3 workers (`--nthreads 1`, 2 GB each, Chromium + Selenium baked in). Scheduler, workers and the ingestion runner share one image (ADR-04).
- `ingestion`: Prefect 3 flow `ingest-travel-offers` with `DaskTaskRunner`, served on a cron schedule. For now it only runs `check_cluster`; Stage 04 adds the scraping.
- `start.sh`: `up | down | reset | logs`.

**Stage 03: Persistence & GraphQL-native data layer**
- `db/01_schema.sql`: 6 schemas and 6 login roles (one per owner). It also contains the tables and constraints from design §4, the `catalog` read-model views exposed via `pg_graphql`, and column-level grants so ingestion can never overwrite inventory.
- `db/02_seed.sql`: 2,700 flights, 3,780 hotel stays and 3,780 car rentals across 6 Colombian cities for the next 30 days (D-006).
- Each service's `/health` now logs in with its own DB role.

## Acceptance criteria

| AC | Result | Evidence | How to reproduce |
|---|---|---|---|
| AC-00.1 every §9 question answered | PASS | `requirements.md` §9 Answer column | `grep -c '^| Q-' requirements.md` |
| AC-00.2 decisions logged with date | PASS | `requirements.md` §11.1 D-001…D-009 | — |
| AC-00.3 lockfiles/`.env.example` tracked, `.env` ignored, clean tree after commit | PASS | `stage-00/AC-00.3_check-ignore.txt`, `stage-00/AC-00.3_git-status.txt` | `git check-ignore -v .env package-lock.json .env.example` |
| AC-01.1 all diagrams render, every UC covered | PASS (18/18) | `stage-01/AC-01.1_mermaid-render.txt`, `stage-01/diagrams/*.svg`, `stage-01/AC-01.3-4_coverage.md` | render loop in the evidence file (`minlag/mermaid-cli:11.17.1`) |
| AC-01.2 SDL parses, covers FR-10–13 | PASS | `stage-01/AC-01.2_sdl-validate.txt` | `graphql-core` `build_schema` + `validate` |
| AC-01.3 every failure point has reverse-order compensations | PASS | `stage-01/AC-01.3-4_coverage.md` | design §3.2–3.9 |
| AC-01.4 every FR/NFR traced | PASS | design §10 | — |
| AC-02.1 clean clone → `cp .env.example .env && docker compose up -d` → all healthy | PASS (12/12, 27 s) | `stage-02/AC-02.1-5_clean-clone.txt`, `stage-02/AC-02.1_compose-ps.txt` | commands in the evidence file |
| AC-02.2 Dask dashboard shows N workers | PASS (3) | `stage-02/AC-02.2_dask-workers.txt` | open http://localhost:8787 |
| AC-02.3 Prefect UI + API healthy | PASS | `stage-02/AC-02.3_prefect-health.txt` | open http://localhost:4200 |
| AC-02.4 only §6.2 ports published | PASS | `stage-02/AC-02.4_ports.txt` | `ss -ltn` |
| AC-02.5 `down -v && up -d` repeatable | PASS | `stage-02/AC-02.1-5_clean-clone.txt` (second cycle) | `./start.sh reset && ./start.sh` |
| AC-02.6 *(added)* Prefect flow runs on Dask | PASS | `stage-02/AC-02.6_prefect-dask-flow-run.txt` | `docker compose exec ingestion prefect deployment run 'ingest-travel-offers/scheduled' --watch` |
| AC-03.1 migrations auto-apply on empty DB | PASS | `stage-03/AC-03.1_migrate.txt` | `./start.sh reset && ./start.sh` |
| AC-03.2 native GraphQL query returns seed offers | PASS | `stage-03/AC-03.2_pg-graphql-query.txt` | `select graphql.resolve(...)` as `gateway_svc` |
| AC-03.3 role X can't touch schema Y | PASS (7 denials + 2 positive controls + GraphQL can't see `accounts`) | `stage-03/AC-03.3_role-isolation.txt` | commands in the file |
| AC-03.4 inventory can't go negative | PASS (3/3) | `stage-03/AC-03.4_check.txt` | — |

## Questions answered / defaults applied
- All of §9 is answered. Q-20 (commit style) was left blank, so the default (Conventional Commits) applies.

## Deviations from spec
- **The frontend container isn't in the stack yet.** It belongs to Stage 09, so through Stage 08 the stack is 12 containers, not 13.
- **AC-02.6 added.** It proves the Prefect→Dask path runs a real task, not just that the containers are up.
- **Step delay default is 1.5 s.** NFR-07 only requires the delay to be configurable; the 2–4 s from Taller-PatronSaga felt too slow for a 4-step saga with compensations.
- **pg_graphql introspection is off in this build.** The gateway never needs it, since it forwards its own known selections (ADR-02). Proof that `accounts` isn't exposed is done by probing the fields directly.

## Open risks / known limits
- **Role passwords show up in `docker compose logs postgres` while the database initialises.** Supabase's init runs with statement logging on. These are local demo values only, never real secrets.
- **Seed dates are relative to the DB's creation day (UTC).** After about 30 days, run `./start.sh reset` to get fresh dates.
- **The clean-clone test reused this machine's Docker layer cache.** A machine with an empty cache will take longer the first time, mainly for the Chromium layer.
- **Real-site scraping (Stage 04) is the biggest schedule risk.** If a site blocks the scraper, the seed data still makes the booking demo work (D-006).

## Approval
- [x] Approved by user — date: 2026-10-09
