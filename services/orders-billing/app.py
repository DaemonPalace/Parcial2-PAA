"""Orders & Billing: owns orders, payments and the booking SAGA (design §5.2)."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

import httpx
import psycopg
from fastapi import HTTPException, Response
from psycopg.rows import dict_row
from pydantic import BaseModel

from common.web import make_app
from saga import DSN, PARTICIPANTS, book_package_saga, recover_order

log = logging.getLogger("orders-billing")
_running: set[asyncio.Task] = set()  # keep references so sagas aren't garbage-collected


def _finished(t: asyncio.Task) -> None:
    _running.discard(t)
    if not t.cancelled() and t.exception():
        log.error("saga task crashed", exc_info=t.exception())


def start(coro) -> None:
    t = asyncio.create_task(coro)
    _running.add(t)
    t.add_done_callback(_finished)


class ChaosIn(BaseModel):
    failAt: Literal["PAYMENT", "FLIGHT", "HOTEL", "CAR"]
    mode: Literal["REJECT", "TIMEOUT"] = "REJECT"
    flakyCompensation: bool = False


class OrderIn(BaseModel):
    idempotency_key: UUID
    user_id: UUID
    flight_offer_id: int
    hotel_offer_id: int
    car_offer_id: int
    chaos: ChaosIn | None = None


@asynccontextmanager
async def lifespan(_app):
    # Crash recovery (Q-24): nothing else runs sagas, so any unfinished order is orphaned.
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute("select id::text from orders where status in ('PENDING', 'RUNNING', 'COMPENSATING')")
        stuck = [r[0] for r in await cur.fetchall()]
    for order_id in stuck:
        log.warning("recovering unfinished order %s", order_id)
        start(recover_order(order_id))
    yield


app = make_app("orders-billing")
app.router.lifespan_context = lifespan

ORDER_SQL = """
    select id, idempotency_key, user_id, flight_offer_id, hotel_offer_id, car_offer_id, total_cop,
           status, failure_reason, chaos, created_at, updated_at
    from orders where {where}"""
STEPS_SQL = "select name, action, status, error, started_at, ended_at from saga_steps where order_id = %s order by id"


async def fetch_order(conn, order_id) -> dict | None:
    cur = conn.cursor(row_factory=dict_row)
    order = await (await cur.execute(ORDER_SQL.format(where="id = %s"), (order_id,))).fetchone()
    if order:
        order["steps"] = await (await cur.execute(STEPS_SQL, (order_id,))).fetchall()
        payment = await (await cur.execute("select status from payments where order_id = %s", (order_id,))).fetchone()
        order["payment_status"] = payment["status"] if payment else None
    return order


async def price_offers(body: OrderIn) -> int:
    """The owning services are the price authority — never trust a client total."""
    total = 0
    async with httpx.AsyncClient(timeout=5) as client:
        for name, offer_id in (("FLIGHT", body.flight_offer_id), ("HOTEL", body.hotel_offer_id), ("CAR", body.car_offer_id)):
            resp = await client.get(f"{PARTICIPANTS[name]}/offers/{offer_id}")
            if resp.status_code == 404:
                raise HTTPException(404, f"OFFER_NOT_FOUND:{name}")
            resp.raise_for_status()
            offer = resp.json()
            if offer["available"] < 1:
                raise HTTPException(409, f"OFFER_UNAVAILABLE:{name}")
            total += offer["price_cop"]
    return total


@app.post("/orders", status_code=201)
async def create_order(body: OrderIn, response: Response):
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute("select id from orders where idempotency_key = %s", (body.idempotency_key,))
        if existing := await cur.fetchone():
            response.status_code = 200  # replay: same order, no new saga, no new charge
            return await fetch_order(conn, existing[0])

    total = await price_offers(body)
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = await conn.execute(
            """insert into orders (idempotency_key, user_id, flight_offer_id, hotel_offer_id, car_offer_id, total_cop, chaos)
               values (%s, %s, %s, %s, %s, %s, %s) on conflict (idempotency_key) do nothing returning id""",
            (body.idempotency_key, body.user_id, body.flight_offer_id, body.hotel_offer_id, body.car_offer_id,
             total, json.dumps(body.chaos.model_dump()) if body.chaos else None),
        )
        created = await cur.fetchone()
        is_new = created is not None
        if not is_new:  # lost a race with a concurrent request carrying the same key
            response.status_code = 200
            cur = await conn.execute("select id from orders where idempotency_key = %s", (body.idempotency_key,))
            created = await cur.fetchone()
        await conn.commit()
        order = await fetch_order(conn, created[0])

    if is_new:
        start(book_package_saga(str(order["id"])))
    return order


@app.get("/orders/{order_id}")
async def get_order(order_id: UUID):
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        order = await fetch_order(conn, order_id)
    if not order:
        raise HTTPException(404, "ORDER_NOT_FOUND")
    return order


@app.get("/orders")
async def list_orders(user_id: UUID | None = None, limit: int = 20):
    where, params = ("user_id = %s", (user_id,)) if user_id else ("true", ())
    async with await psycopg.AsyncConnection.connect(DSN) as conn:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(ORDER_SQL.format(where=where) + " order by created_at desc limit %s", (*params, min(limit, 100)))
        return await cur.fetchall()
