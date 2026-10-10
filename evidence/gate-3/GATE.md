# Gate G3 — Stages 05–06 (Domain microservices + SAGA orchestration) — Gate report

**Date:** 2026-10-09 (runs logged in UTC, 2026-10-10 01:20–01:45Z) · **Commits:** `ca7355f` (05) · stage-06 commit (this report is part of it) · **Status:** approved 2026-10-10

## Built

**Stage 05: Domain microservices**
- `services/common/participant.py` provides one reserve/cancel contract shared by `flights-svc`, `hotels-svc` and `cars-svc` (each `app.py` is one line). It works as follows:
  - **Idempotency:** each order's reservation row (unique `order_id`) doubles as its idempotency record.
  - **Inventory:** decremented conditionally (`... > 0`) and protected by a `CHECK >= 0`.
  - **Tombstones:** a cancel that arrives before its reserve writes a `CANCELLED` tombstone, so a late reserve returns 410 and takes nothing.
  - **Price:** `GET /offers/{id}` returns the price and availability.
  - **Failure injection:** `REJECT` (422), `TIMEOUT` (commits, then answers after 8 s, longer than the orchestrator's 5 s client timeout), and flaky compensation (first cancel returns 503).
- `services/orders-billing/app.py`:
  - **Create order:** `POST /orders` prices the order from the owning services rather than trusting a client-sent total, and is idempotent on `idempotency_key`, including concurrent duplicates.
  - **Read orders:** `GET /orders/{id}` returns the order, its steps and the payment status; `GET /orders` lists them.
  - **Crash recovery at startup:** any unfinished order is compensated automatically.

**Stage 06: SAGA orchestration (Prefect)**
- `services/orders-billing/saga.py` defines the Prefect flow `book-package-saga` (one flow run per order, named `order-<id>`):
  - **Forward tasks:** `charge_payment` → `reserve_FLIGHT` → `reserve_HOTEL` → `reserve_CAR`.
  - **Compensations:** `cancel_*` tasks run for the failed step plus the completed steps in reverse order, then `refund_payment`. Each compensation task has 5 retries with 1/2/4/8/16 s backoff.
  - **Step log:** every attempt is written to `orders.saga_steps` for the frontend.
  - **Recovery flow:** `recover-unfinished-order`.
- `scripts/simulate_saga.py` runs every case against the live stack. `scripts/reconcile.sql` is the cross-schema consistency check (NFR-04). `scripts/test_participants.py` holds the Stage 05 checks.
- Adapted from `Taller-PatronSaga/services/saga-orchestrator/app/flow.py` (task-per-step pattern, `cache_policy=NONE`).

## Acceptance criteria

| AC | Result | Evidence | How to reproduce |
|---|---|---|---|
| AC-05.1 each operation works in isolation | PASS (3/3 services) | `stage-05/AC-05.1-5_participants.txt` | `docker compose exec -T orders-billing-svc python - < scripts/test_participants.py` |
| AC-05.2 replay → same result, no double effect | PASS | same | same |
| AC-05.3 compensation idempotent, safe with no forward step | PASS (double cancel; cancel-before-reserve tombstone → late reserve 410) | same | same |
| AC-05.4 two concurrent reserves on the last unit → exactly one wins | PASS (`[201, 409]`, inventory 0, never negative) | same | same |
| AC-05.5 failure modes give documented codes | PASS (REJECT 422, TIMEOUT commits then client times out, flaky 503→200) | same | same |
| AC-06.1 happy path | PASS: CONFIRMED, charged, 1 unit each | `stage-06/AC-06.1-8_simulate_saga.txt` | `docker compose exec -T orders-billing-svc python - < scripts/simulate_saga.py` |
| AC-06.2 payment fails | PASS: REJECTED, nothing to compensate, no charge | same | `... - payment_fails < ...` |
| AC-06.3 flight fails | PASS: FLIGHT → PAYMENT refund, CANCELLED | same | `... - flight_fails < ...` |
| AC-06.4 hotel fails | PASS: HOTEL → FLIGHT → PAYMENT | same | `... - hotel_fails < ...` |
| AC-06.5 car fails (brief's example) | PASS: CAR → HOTEL → FLIGHT → PAYMENT, inventory restored, refunded | same, plus `AC-06.5_prefect-car-fails.png` | `... - car_fails < ...` |
| AC-06.6 timeout / lost confirmation | PASS: the hotel **committed** (row has `offer_id`) and compensation released it | same, plus `AC-06.6_timeout-committed-then-released.txt` and `AC-06.6_prefect-hotel-timeout.png` | `... - hotel_timeout < ...` |
| AC-06.7 compensation fails transiently → recovered with no manual action | PASS: each cancel FAILED once then SUCCEEDED via Prefect retry | same, plus `AC-06.7_prefect-flaky-compensation.png` | `... - flaky_compensation < ...` |
| AC-06.8 same idempotency key | PASS: 3 concurrent requests and 1 late replay produce one order and one saga run | same | `... - idempotent_retry < ...` |
| AC-06.9 reconciliation | PASS: all 5 checks at 0 violations over 17 orders | `AC-06.9_reconciliation.txt` | `docker compose exec -T postgres psql -U supabase_admin -d postgres -f - < scripts/reconcile.sql` |
| AC-06.10 *(added)* orchestrator crash mid-saga (Q-24) | PASS: killed with SIGKILL while the hotel step was in flight (paid, flight held, hotel committed, i.e. the brief's orphan booking). On restart it was compensated, refunded and CANCELLED | `AC-06.10_crash-recovery.txt` | steps in the file |

## Bugs found and fixed during verification
1. **No saga ever started from `POST /orders`.** FastAPI's injected `Response.status_code` is `None` until it's set, not the decorator's `201`, so the `== 201` check never passed. It's fixed with an explicit `is_new` flag. While debugging, the service restart also exercised crash recovery on 7 really stuck orders; all ended CANCELLED, and reconciliation is clean.
2. **Crash-interrupted steps stayed `RUNNING` in the step log forever.** Recovery now closes them as `FAILED: interrupted: orchestrator crashed`. The first crash-test order (`26eb500e…`, before the fix) still shows the old `RUNNING` row as history.

## Deviations from spec
- **Pricing moved into orders-billing.** The design had the gateway send `total_cop`. Orders-billing now prices the order through each participant's new `GET /offers/{id}`, so the owning services are the price authority. `docs/design.md` §3.1 and §5.2 are updated.
- **The forward-step transient retry runs inside the task,** not as a Prefect task retry (design §3.10 updated). Compensation retries are Prefect retries, which is what the rubric's "automatic, no manual intervention" relies on.
- **`TIMEOUT` on PAYMENT behaves like `REJECT`,** because payment is a local step.
- **AC-06.10 added.**

## Open risks / known limits
- **Chaos state is per process.** The flaky-compensation memory resets on restart. That's fine for a single replica (marked with a `ponytail:` comment).
- **Crash recovery assumes one orders-billing replica.** With several replicas, a starting instance would compensate sagas another instance is still running. It would then need a lease or heartbeat column.
- **Orders-billing isn't reachable from the host,** so these tests run inside the network. From G4 on, the same cases run through the GraphQL gateway.
- **Payment is a mock (Q-16).**

## Approval
- [x] Approved by user — date: 2026-10-10
