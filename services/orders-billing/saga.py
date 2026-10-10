"""Booking SAGA, orchestrated by Prefect (docs/design.md §3, ADR-01).

Forward:      PAYMENT → FLIGHT → HOTEL → CAR → CONFIRMED
Compensation: failed step + completed steps in reverse order, then refund → CANCELLED
Every step and compensation is a Prefect task (visible in the Prefect UI) and is
written to orders.saga_steps (visible to the frontend).

Adapted from Taller-PatronSaga/services/saga-orchestrator/app/flow.py.
"""
import asyncio
import contextlib
import json
import os

import httpx
import psycopg
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NONE as NO_CACHE

DSN = os.environ["DATABASE_URL"]
STEP_DELAY = float(os.environ.get("SAGA_STEP_DELAY_SECONDS", "1.5"))
CLIENT_TIMEOUT = float(os.environ.get("SAGA_CLIENT_TIMEOUT_SECONDS", "5"))
PARTICIPANTS = {
    "FLIGHT": os.environ.get("FLIGHTS_SERVICE_URL", "http://flights-svc:8000"),
    "HOTEL": os.environ.get("HOTELS_SERVICE_URL", "http://hotels-svc:8000"),
    "CAR": os.environ.get("CARS_SERVICE_URL", "http://cars-svc:8000"),
}
OFFER_COLUMN = {"FLIGHT": "flight_offer_id", "HOTEL": "hotel_offer_id", "CAR": "car_offer_id"}
COMPENSATION_RETRIES = dict(retries=5, retry_delay_seconds=[1, 2, 4, 8, 16])


class StepRejected(Exception):
    """Business rejection (or transient error that survived its retry): compensate."""


class StepTimeout(Exception):
    """No answer in time — outcome unknown, so it is compensated too (ADR-05)."""


# ───────────────────────── persistence helpers ─────────────────────────

async def db_exec(sql: str, params=()):
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchone() if cur.description else None


async def set_status(order_id: str, status: str, reason: str | None = None) -> None:
    await db_exec(
        "update orders set status = %s, failure_reason = coalesce(%s, failure_reason), updated_at = now() where id = %s",
        (status, reason, order_id),
    )


@contextlib.asynccontextmanager
async def step_trail(order_id: str, name: str, action: str):
    (step_id,) = await db_exec(
        "insert into saga_steps (order_id, name, action, status) values (%s, %s, %s, 'RUNNING') returning id",
        (order_id, name, action),
    )
    try:
        yield
    except BaseException as exc:
        await db_exec("update saga_steps set status = 'FAILED', error = %s, ended_at = now() where id = %s",
                      (f"{type(exc).__name__}: {exc}"[:500], step_id))
        raise
    await db_exec("update saga_steps set status = 'SUCCEEDED', ended_at = now() where id = %s", (step_id,))


# ───────────────────────── forward tasks ─────────────────────────

@task(name="charge_payment", cache_policy=NO_CACHE)
async def charge_payment(order: dict) -> None:
    async with step_trail(order["id"], "PAYMENT", "FORWARD"):
        await asyncio.sleep(STEP_DELAY)
        if order["chaos"].get("failAt") == "PAYMENT":
            raise StepRejected("payment declined (chaos)")
        # payments.order_id is the primary key: a replayed charge is a no-op.
        await db_exec(
            "insert into payments (order_id, amount_cop, status) values (%s, %s, 'CHARGED') on conflict do nothing",
            (order["id"], order["total_cop"]),
        )


@task(task_run_name="reserve_{name}", cache_policy=NO_CACHE)
async def reserve(order: dict, name: str) -> dict:
    chaos = order["chaos"]
    body = {"order_id": order["id"], "offer_id": order[OFFER_COLUMN[name]]}
    if chaos.get("failAt") == name:
        body["chaos"] = {"fail": chaos.get("mode", "REJECT")}
    async with step_trail(order["id"], name, "FORWARD"):
        await asyncio.sleep(STEP_DELAY)
        for attempt in (1, 2):  # one retry, transport errors / 5xx only (design §3.10)
            try:
                async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
                    resp = await client.post(f"{PARTICIPANTS[name]}/reservations", json=body)
            except httpx.TimeoutException:
                raise StepTimeout(f"{name} reservation: no confirmation after {CLIENT_TIMEOUT:g}s")
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise StepRejected(f"{name} unreachable: {exc}")
                continue
            if resp.status_code >= 500 and attempt == 1:
                continue
            if resp.status_code in (200, 201):
                return resp.json()
            raise StepRejected(f"{name} reservation {resp.status_code}: {resp.text[:200]}")


# ───────────────────────── compensation tasks ─────────────────────────

@task(task_run_name="cancel_{name}", cache_policy=NO_CACHE, **COMPENSATION_RETRIES)
async def cancel(order: dict, name: str) -> dict:
    async with step_trail(order["id"], name, "COMPENSATE"):
        await asyncio.sleep(STEP_DELAY)
        async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT) as client:
            resp = await client.post(
                f"{PARTICIPANTS[name]}/reservations/{order['id']}/cancel",
                json={"flaky": bool(order["chaos"].get("flakyCompensation"))},
            )
        resp.raise_for_status()  # any error → Prefect retry with backoff
        return resp.json()


@task(name="refund_payment", cache_policy=NO_CACHE, **COMPENSATION_RETRIES)
async def refund_payment(order: dict) -> None:
    async with step_trail(order["id"], "PAYMENT", "COMPENSATE"):
        await asyncio.sleep(STEP_DELAY)
        await db_exec(
            "update payments set status = 'REFUNDED', refunded_at = now() where order_id = %s and status = 'CHARGED'",
            (order["id"],),
        )


async def compensate(order: dict, steps: list[str]) -> None:
    await set_status(order["id"], "COMPENSATING")
    for name in steps:
        await cancel(order, name)
    await refund_payment(order)
    await set_status(order["id"], "CANCELLED")


# ───────────────────────── flows ─────────────────────────

async def load_order(order_id: str) -> dict:
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute(
            "select id::text, total_cop, flight_offer_id, hotel_offer_id, car_offer_id, coalesce(chaos, '{}') "
            "from orders where id = %s", (order_id,))
        row = await cur.fetchone()
    keys = ("id", "total_cop", "flight_offer_id", "hotel_offer_id", "car_offer_id", "chaos")
    order = dict(zip(keys, row))
    if isinstance(order["chaos"], str):
        order["chaos"] = json.loads(order["chaos"])
    return order


@flow(name="book-package-saga", flow_run_name="order-{order_id}")
async def book_package_saga(order_id: str) -> str:
    log = get_run_logger()
    order = await load_order(order_id)
    await set_status(order_id, "RUNNING")

    try:
        await charge_payment(order)
    except StepRejected as exc:
        await set_status(order_id, "REJECTED", f"PAYMENT: {exc}")
        log.info("payment rejected — nothing to compensate")
        return "REJECTED"

    done: list[str] = []
    for name in ("FLIGHT", "HOTEL", "CAR"):
        try:
            await reserve(order, name)
            done.append(name)
        except (StepRejected, StepTimeout) as exc:
            await set_status(order_id, "COMPENSATING", f"{name}: {exc}")
            # The failed step is compensated too: a timeout may have committed (ADR-05).
            to_undo = [name, *reversed(done)]
            log.warning("%s failed (%s) — compensating %s, then refund", name, exc, to_undo)
            await compensate(order, to_undo)
            return "CANCELLED"

    await set_status(order_id, "CONFIRMED")
    return "CONFIRMED"


@flow(name="recover-unfinished-order", flow_run_name="recover-{order_id}")
async def recover_order(order_id: str) -> str:
    """Crash recovery (design §3.9): every compensation is idempotent and
    tombstone-safe, so compensating everything is correct whatever had finished."""
    order = await load_order(order_id)
    await db_exec("update orders set failure_reason = coalesce(failure_reason, 'recovered_after_crash') where id = %s",
                  (order_id,))
    await db_exec("update saga_steps set status = 'FAILED', error = 'interrupted: orchestrator crashed', ended_at = now() "
                  "where order_id = %s and status = 'RUNNING'", (order_id,))
    await compensate(order, ["CAR", "HOTEL", "FLIGHT"])
    return "CANCELLED"
