"""SAGA participant: reserve / cancel one unit of an offer (docs/design.md §3.6, §5.2).

Shared by flights-svc, hotels-svc and cars-svc — same contract, different tables.
Each service connects with its own DB role whose search_path is its own schema,
so the table names below are unqualified.

Guarantees:
- reserve and cancel are idempotent per order_id (unique reservation row).
- cancel before (or instead of) reserve writes a CANCELLED tombstone, and a later
  reserve for that order does nothing (410) — a late "lost confirmation" can't
  leave an orphan booking.
- inventory never goes negative: conditional decrement + CHECK constraint.
"""
import os
import time
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import HTTPException, Response
from pydantic import BaseModel

from common.web import make_app

# ponytail: per-process memory, demo-only chaos state; fine for one replica.
_flaked: set[UUID] = set()


class Chaos(BaseModel):
    fail: Literal["REJECT", "TIMEOUT"] | None = None


class ReserveIn(BaseModel):
    order_id: UUID
    offer_id: int
    chaos: Chaos | None = None


class CancelIn(BaseModel):
    flaky: bool = False


def build_app(name: str, offers: str, reservations: str, inventory: str, price: str):
    app = make_app(name)
    dsn = os.environ["DATABASE_URL"]
    timeout_delay = float(os.environ.get("CHAOS_TIMEOUT_DELAY_SECONDS", "8"))

    @app.get("/offers/{offer_id}")
    def get_offer(offer_id: int):
        """Price authority for orders-billing, and inventory probe for evidence."""
        with psycopg.connect(dsn) as conn:
            row = conn.execute(f"select {price}, {inventory} from {offers} where id = %s", (offer_id,)).fetchone()
        if not row:
            raise HTTPException(404, "OFFER_NOT_FOUND")
        return {"id": offer_id, "price_cop": row[0], "available": row[1]}

    @app.post("/reservations", status_code=201)
    def reserve(body: ReserveIn, response: Response):
        fail = body.chaos.fail if body.chaos else None
        if fail == "REJECT":
            raise HTTPException(422, "REJECTED")

        # One transaction: commits when the block exits, rolls back on any exception.
        with psycopg.connect(dsn) as conn:
            try:
                won = conn.execute(
                    f"insert into {reservations} (order_id, offer_id, status) values (%s, %s, 'RESERVED') "
                    "on conflict (order_id) do nothing returning id",
                    (body.order_id, body.offer_id),
                ).fetchone()
            except psycopg.errors.ForeignKeyViolation:
                raise HTTPException(404, "OFFER_NOT_FOUND")
            if not won:
                (status,) = conn.execute(
                    f"select status from {reservations} where order_id = %s", (body.order_id,)
                ).fetchone()
                if status == "CANCELLED":
                    raise HTTPException(410, "ALREADY_CANCELLED")
                response.status_code = 200
                return {"order_id": str(body.order_id), "status": "RESERVED", "replay": True}
            took = conn.execute(
                f"update {offers} set {inventory} = {inventory} - 1 where id = %s and {inventory} > 0 returning id",
                (body.offer_id,),
            ).fetchone()
            if not took:
                raise HTTPException(409, "SOLD_OUT")  # rolls back the reservation row too

        if fail == "TIMEOUT":
            # Committed, but the confirmation arrives after the orchestrator's client
            # timeout: the brief's "lost confirmation" orphan-booking scenario.
            time.sleep(timeout_delay)
        return {"order_id": str(body.order_id), "status": "RESERVED", "replay": False}

    @app.post("/reservations/{order_id}/cancel")
    def cancel(order_id: UUID, body: CancelIn | None = None):
        if body and body.flaky and order_id not in _flaked:
            _flaked.add(order_id)
            raise HTTPException(503, "CHAOS_FLAKY_COMPENSATION")

        with psycopg.connect(dsn) as conn:
            tombstone = conn.execute(
                f"insert into {reservations} (order_id, offer_id, status) values (%s, null, 'CANCELLED') "
                "on conflict (order_id) do nothing returning id",
                (order_id,),
            ).fetchone()
            if tombstone:
                return {"order_id": str(order_id), "result": "tombstone"}
            released = conn.execute(
                f"update {reservations} set status = 'CANCELLED', updated_at = now() "
                "where order_id = %s and status = 'RESERVED' returning offer_id",
                (order_id,),
            ).fetchone()
            if not released:
                return {"order_id": str(order_id), "result": "already_cancelled"}
            conn.execute(f"update {offers} set {inventory} = {inventory} + 1 where id = %s", released)
        return {"order_id": str(order_id), "result": "released"}

    return app
