# Gate G4 — Stages 07–09 (GraphQL gateway, Security, Frontend) — Gate report

**Date:** 2026-10-10 · **Commits:** `8a303f1` (07) · `6cb627b` (08) · stage-09 commit (this report is part of it) · **Status:** awaiting approval

## Built

**Stage 07: GraphQL API gateway** (`services/gateway/`, FastAPI + Strawberry)
- **Contract match:** implements `docs/schema.graphql` exactly. A graphql-core diff in both directions finds no differences.
- **Catalog through `pg_graphql` (ADR-02):** the selection set of `packageAvailability` becomes one pg_graphql document that asks only for the requested columns. A whole search, including the cheapest combination, is one DB round-trip.
- **No N+1:** `Order.flight/hotel/car` go through per-request DataLoaders, so N orders cost 3 catalog round-trips.
- **Booking:** `bookPackage` → orders-billing → Prefect SAGA. `order` and `myOrders` read the step log for live tracking.
- **Abuse limits:** max 10 aliases per operation. Only `/graphql` and `/health` are exposed; the FastAPI docs and OpenAPI routes are disabled in every service.

**Stage 08: Security by design** (`services/gateway/security.py`, `app.py`)
- **Passwords:** Argon2id (t=3, m=64 MiB, p=4). Unknown emails are verified against a dummy hash so login timing doesn't reveal whether an account exists. Registration errors are generic.
- **Sessions:** server-side, stored as `sha256(token)` in `accounts.sessions`, cookie `HttpOnly` + `SameSite=Lax`. The ID rotates at login and register and is destroyed at logout. IDs the server never issued are not adopted.
- **Rate limits per GraphQL operation:** login 5/min per IP and 10 per 15 min per email, register 3/min per IP, `bookPackage` (checkout + payment) 5/min per user, ingestion 2/min, plus 120/min per IP overall. When exceeded, the response is HTTP 429 with `Retry-After` and a `RATE_LIMITED` error in the payload.
- **Authorization:** users only see their own orders. Chaos flags and `triggerIngestion` are admin-only. CORS is restricted to the frontend origin, and security headers are set.
- **Supply chain:** `pip-audit` on 6 Python lockfiles and `npm audit` on the frontend. Report: `stage-08/AC-08.6_supply-chain-report.md`.

**Stage 09: Frontend** (`frontend/`, Next.js 16 + Tailwind + shadcn pieces + Apollo Client 4, Spanish UI)
- **Pages:**
  - `/`: search, package builder (preselects the cheapest combination) and checkout, plus an admin-only "Simular fallo" panel.
  - `/ingresar`: login and registration.
  - `/reservas`: my bookings.
  - `/reservas/[id]`: live SAGA tracker with the forward steps and the compensations in reverse order, including retried attempts.
  - `/admin`: manual ingestion trigger and links to Prefect and Dask.
- **Reused from Taller-PatronSaga:** Dockerfile (standalone, now non-root), tsconfig, UI primitives, and the state color tokens. The odd `cn` npm package import was replaced by `lib/utils`.
- **Fully local:** system fonts, so the build doesn't download anything from Google Fonts.

## Acceptance criteria

| AC | Result | Evidence |
|---|---|---|
| AC-07.0 *(added)* implementation = Stage 01 contract | PASS: graphql-core diff is empty both ways | `stage-07/AC-07.0_schema-matches-contract.txt` |
| AC-07.1 one request returns a full package search | PASS: flights, hotels, cars and cheapest package (759,950 COP) | `stage-07/AC-07_08_gateway-suite.txt` |
| AC-07.2 constant DB calls regardless of result size (no N+1) | PASS: 3 orders × 3 nested offers took 3 round-trips, not 9; a search is 1 | same |
| AC-07.3 fewer fields mean fewer selected columns | PASS: `flights { priceCop }` produces `node { id priceCop }`, with no hotel/car collections | same |
| AC-07.4 `bookPackage` → Prefect saga; `order` reflects transitions | PASS: PENDING → RUNNING → CONFIRMED, matching Prefect flow run `order-<id>` Completed | same |
| AC-07.5 non-`/graphql` → 404; abusive query rejected | PASS: `/docs`, `/openapi.json`, `/admin`, `/orders` return 404. Nested introspection is rejected, and a batch of 20 aliases is rejected before any DB call | same |
| AC-08.1 Argon2id with configured cost; no plaintext | PASS: `$argon2id$v=19$m=65536,t=3,p=4$…` | same |
| AC-08.2 session fixation | PASS: the pre-login ID ≠ the post-login ID, the old ID is dead, an attacker-chosen ID is never adopted, only sha256 is stored | same |
| AC-08.3 logout invalidates server-side | PASS | same |
| AC-08.4 429 + Retry-After on login / register / checkout | PASS: login `[200×5, 429, 429]` (blocked even with the right password), register `[200, 200, 429]`, bookPackage `[200×5, 429]` | same |
| AC-08.5 user A can't read user B's order | PASS. Also: traveler chaos is ignored, traveler `triggerIngestion` is FORBIDDEN, admin chaos produces a full compensation | same |
| AC-08.6 dependency audit, 0 unresolved high/critical | PASS after remediation: Python 0/0. npm found 1 critical and 5 high, fixed down to 0 | `stage-08/AC-08.6_supply-chain-report.md` |
| AC-09.1 browser talks only to `/graphql` | PASS: the only non-frontend URL requested is `http://localhost:8000/graphql` (Chromium network log) | `stage-09/AC-09.1-5_ui-e2e.txt` |
| AC-09.2 happy-path booking from the UI → CONFIRMED | PASS: a new traveler registers, searches, books and sees "¡Listo!" | same, plus `02/03-tracker-*.png` |
| AC-09.3 car failure from the UI shows compensations live → CANCELLED | PASS: Cancelar auto → hotel → vuelo → Reembolso | same, plus `04/05-tracker-*.png`, `search-car.png` |
| AC-09.4 errors shown meaningfully | PASS: wrong password shows "Correo o contraseña incorrectos." (exercised in the E2E). Rate-limit (429) and offer errors map to Spanish messages in code (`requestError`, `userErrors`) but the browser E2E doesn't trigger them; the 429 itself is proven at API level in AC-08.4 | same, plus `06-login-error.png` |
| AC-09.5 basic accessibility | PASS: every input is labeled, keyboard focus has a visible outline, `lang="es"`, live region on the tracker | same |

Reproduce: `python3 scripts/test_gateway.py` (Stages 07–08, about 3.5 min including a 61 s rate-limit window), and `docker run --rm --network host --shm-size=1g -v "$PWD:/w:z" -w /w --entrypoint python wandersync-ingestion scripts/ui_e2e.py evidence/stage-09 <admin-email> <admin-password>` (Stage 09).

## Bugs / findings fixed during verification
1. **Contract drift:** the implementation made required catalog fields nullable and defaulted arguments non-null. Caught by AC-07.0 and aligned.
2. **The depth limiter did nothing:** Strawberry's depth limiter skips introspection, and the schema is acyclic. It was replaced by an alias limit, which closes the real batching vector (one request with N aliased searches means N DB queries).
3. **Critical CVE inherited by reuse:** `next@16.3.5` from Taller-PatronSaga (RCE in `next/og`). Upgraded to 16.3.8. The unused eslint chain, which carried a high `braces` advisory with no fix, was removed.
4. **No visible keyboard focus on links:** my first a11y check passed falsely (it accepted a transparent shadow). A global `:focus-visible` outline was added and the check was made strict.

## Design pass (design-taste-frontend skill, targeted fixes, requested 2026-10-10)
Only the skill's general rules were applied. It doesn't cover multi-step product UI, so its layout rules for heroes, bentos and eyebrows weren't used. Changes:
- **Dashes:** every visible em/en dash removed: admin link labels, date ranges (now `17/10/2026 - 20/10/2026`), and the `—` empty placeholders in the package summary (now "Sin elegir").
- **Dark mode:** a full dark token set follows `prefers-color-scheme`, with `color-scheme` set so native date pickers and selects match.
- **Contrast:** all 15 text/background token pairs pass WCAG AA in both modes. The light "Confirmada" and "Compensando" badges, inherited from Taller-PatronSaga, were at 4.41 and 4.35 and are now 5.62 and 5.72.
- **Loading states:** spinners replaced with skeleton results while searching and with verb labels on buttons ("Buscando…", "Reservando…", "Verificando…"). The only spinner kept marks real progress on a running SAGA step.
- **Press feedback:** buttons scale slightly when pressed (`active:scale-[0.98]`), disabled when the user prefers reduced motion.
- **Separators:** at most one middle dot per line. The flight row now shows its times on one line and stops plus duration on the next.
- **Font:** Geist from the `geist` npm package. The font files ship inside the bundle, so nothing is downloaded at build or run time. `npm audit` still reports 0 vulnerabilities.
- **Polish:** a gap between long names and prices, and the "Motivo" line now shows a friendly Spanish reason.
- Evidence: `stage-09/07-dark-search.png`, `stage-09/08-dark-tracker.png`. The E2E gained a dark-mode check, and all checks pass.

## Deviations from spec
- **Stage 07 and 08 code ship together.** The gateway code for both stages landed in the stage-07 commit, because the session middleware and resolvers are one module set. The stage-08 commit holds the verification and the audit.
- **Depth limit replaced by an alias limit** (design §5.1 updated).
- **The frontend container joins the stack (13 containers).** The gateway URL is baked into the browser bundle at build time (`NEXT_PUBLIC_GRAPHQL_URL`).
- **AC-07.0 added.**

## Open risks / known limits
- **Rate limits are in memory** in the single gateway (ADR-03). They reset when the gateway restarts.
- **Cookies are sent without `Secure`** because the demo is plain-HTTP localhost. Behind TLS, set `COOKIE_SECURE=true`.
- **Expired sessions are never cleaned up.** Rows stay in the table but are no longer valid. A periodic `delete … where expires_at < now()` would fix that if it matters.
- **Search covers 1–7 nights.** Live-scraped offers exist only for the ingestion plan (+7 and +14 days, 3 nights); other dates use seed offers, labeled "Catálogo base" in the UI.

## Approval
- [ ] Approved by user — date: ____
