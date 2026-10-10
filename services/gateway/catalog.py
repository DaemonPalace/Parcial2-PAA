"""Catalog reads through Postgres' native GraphQL (pg_graphql), design ADR-02.

The gateway turns the client's selection set into ONE pg_graphql document that
asks only for the requested columns, so a whole package search costs a single
DB round-trip and never selects columns the client didn't ask for (FR-11, FR-12).

The gateway's DB role has search_path = catalog, so pg_graphql only sees the
read-model views — never accounts.* (evidence/stage-03/AC-03.3).
"""
import json
import logging
from datetime import date, timedelta

log = logging.getLogger("gateway.catalog")

# GraphQL kind -> (pg_graphql collection, price field, availability field, every scalar field)
KINDS = {
    "flights": ("flightOffersCollection", "priceCop", "seatsAvailable",
                {"id", "source", "airline", "origin", "destination", "departAt", "arriveAt",
                 "durationMinutes", "stops", "priceCop", "seatsAvailable", "scrapedAt"}),
    "hotels": ("hotelOffersCollection", "priceTotalCop", "roomsAvailable",
               {"id", "source", "name", "city", "checkIn", "checkOut", "rating", "priceTotalCop",
                "roomsAvailable", "url", "scrapedAt"}),
    "cars": ("carOffersCollection", "priceTotalCop", "unitsAvailable",
             {"id", "source", "vendor", "model", "category", "city", "pickupDate", "dropoffDate",
              "priceTotalCop", "unitsAvailable", "scrapedAt"}),
}


def search_filters(origin: str, destination: str, depart: date, ret: date) -> dict[str, str]:
    """Inputs are validated before this (IATA regex, real dates), so literals are safe."""
    day = depart.isoformat()
    nxt = (depart + timedelta(days=1)).isoformat()
    s = json.dumps
    return {
        # Flight day boundaries in Bogotá time (all cities are in America/Bogota, UTC-5, no DST).
        "flights": f'{{origin: {{eq: {s(origin)}}}, destination: {{eq: {s(destination)}}}, '
                   f'departAt: {{gte: {s(day + "T00:00:00-05:00")}, lt: {s(nxt + "T00:00:00-05:00")}}}, '
                   f'seatsAvailable: {{gt: 0}}}}',
        "hotels": f'{{city: {{eq: {s(destination)}}}, checkIn: {{eq: {s(day)}}}, checkOut: {{eq: {s(ret.isoformat())}}}, '
                  f'roomsAvailable: {{gt: 0}}}}',
        "cars": f'{{city: {{eq: {s(destination)}}}, pickupDate: {{eq: {s(day)}}}, dropoffDate: {{eq: {s(ret.isoformat())}}}, '
                f'unitsAvailable: {{gt: 0}}}}',
    }


def collection(alias: str, kind: str, fields: set[str], filt: str, first: int, descending: bool = False) -> str:
    coll, price, _, allowed = KINDS[kind]
    cols = " ".join(sorted((fields & allowed) | {"id"}))
    order = "DescNullsLast" if descending else "AscNullsLast"
    return f"{alias}: {coll}(first: {first}, filter: {filt}, orderBy: [{{{price}: {order}}}]) {{ edges {{ node {{ {cols} }} }} }}"


async def resolve(pool, document: str) -> dict:
    async with pool.connection() as conn:
        cur = await conn.execute("select graphql.resolve(%s)", (document,))
        result = (await cur.fetchone())[0]
    if result.get("errors"):
        raise RuntimeError(f"pg_graphql: {result['errors']}")
    log.info("pg_graphql round-trip: %s", document)  # evidence for AC-07.2 / AC-07.3
    return result["data"]


def nodes(data: dict, alias: str) -> list[dict]:
    return [edge["node"] for edge in (data.get(alias) or {}).get("edges", [])]


async def offers_by_id(pool, kind: str, ids: list[int]) -> dict[int, dict]:
    """DataLoader backend: one round-trip for every offer of one kind in the request."""
    filt = f"{{id: {{in: {json.dumps([str(int(i)) for i in ids])}}}}}"  # pg_graphql BigInt = string
    data = await resolve(pool, "{ " + collection("rows", kind, KINDS[kind][3], filt, len(ids)) + " }")
    return {int(n["id"]): n for n in nodes(data, "rows")}
