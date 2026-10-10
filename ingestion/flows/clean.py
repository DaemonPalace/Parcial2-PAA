"""Parse + validate raw scraper rows into DB-ready offers (pure functions, no I/O).

Each clean_* returns (valid_rows, rejected_count). Invalid rows are counted,
never loaded (FR-07). Duplicates by natural key keep the cheapest price (FR-06).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
MONTHS_ES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], start=1)}

# Sanity bounds in COP: anything outside is a parsing error, not a price.
FLIGHT_PRICE = (50_000, 10_000_000)
STAY_PRICE = (20_000, 100_000_000)


def digits(text: str | None) -> int | None:
    """'COP 2.759.760' / 'COP 540,200' / '177805' -> int. COP has no decimals."""
    if not text:
        return None
    only = re.sub(r"\D", "", text)
    return int(only) if only else None


def _in(value: int | None, bounds: tuple[int, int]) -> bool:
    return value is not None and bounds[0] <= value <= bounds[1]


def _dedupe(rows: list[dict], key: tuple[str, ...], price: str) -> list[dict]:
    best: dict[tuple, dict] = {}
    for row in rows:
        k = tuple(row[f] for f in key)
        if k not in best or row[price] < best[k][price]:
            best[k] = row
    return list(best.values())


# ───────────────────────── flights ─────────────────────────

_PRICE = re.compile(r"A partir de (\d+) pesos colombianos")
_AIRLINE = re.compile(r"Vuelo (directo|con (\d+|una) escalas?) de ([^.]+?)\.")
_DEPART = re.compile(r"Sale de .+? el \w+, (\w+) (\d+) a las (\d{1,2}):(\d{2})")
_ARRIVE = re.compile(r"Llega a .+? el \w+, (\w+) (\d+) a las (\d{1,2}):(\d{2})")
_DURATION = re.compile(r"Duración total: (?:(\d+) h)?\s*(?:(\d+) min)?")


def _local_dt(search_day: date, month_name: str, day_num: str, hh: str, mm: str) -> datetime:
    month = MONTHS_ES[month_name.lower()]
    year = search_day.year + (1 if month < search_day.month else 0)  # Dec -> Jan rollover
    return datetime.combine(date(year, month, int(day_num)), time(int(hh), int(mm)), BOGOTA)


def parse_flight(raw: dict) -> dict | None:
    label = " ".join((raw.get("label") or "").split())  # Google uses U+00A0 / U+202F between number and unit
    price, airline, depart = _PRICE.search(label), _AIRLINE.search(label), _DEPART.search(label)
    if not (price and airline and depart):
        return None
    search_day = date.fromisoformat(raw["day"])
    arrive = _ARRIVE.search(label)
    duration = _DURATION.search(label)
    minutes = None
    if duration and (duration.group(1) or duration.group(2)):
        minutes = int(duration.group(1) or 0) * 60 + int(duration.group(2) or 0)
    stops = 0 if airline.group(1) == "directo" else (1 if airline.group(2) == "una" else int(airline.group(2)))
    return {
        "source": raw["source"],
        "airline": airline.group(3).strip(),
        "origin": raw["origin"],
        "destination": raw["destination"],
        "depart_at": _local_dt(search_day, *depart.groups()),
        "arrive_at": _local_dt(search_day, *arrive.groups()) if arrive else None,
        "duration_minutes": minutes,
        "stops": stops,
        "price_cop": int(price.group(1)),
    }


def clean_flights(raw_rows: list[dict]) -> tuple[list[dict], int]:
    parsed = [parse_flight(r) for r in raw_rows]
    valid = [p for p in parsed if p and _in(p["price_cop"], FLIGHT_PRICE)]
    key = ("source", "airline", "origin", "destination", "depart_at")
    return _dedupe(valid, key, "price_cop"), len(raw_rows) - len(valid)


# ───────────────────────── hotels ─────────────────────────

def parse_hotel(raw: dict) -> dict | None:
    name, price = (raw.get("name") or "").strip(), digits(raw.get("price"))
    if not name or not _in(price, STAY_PRICE):
        return None
    rating = re.search(r"(\d+[.,]\d)", raw.get("rating") or "")
    url = raw.get("url")
    return {
        "source": raw["source"],
        "name": name,
        "city": raw["city"],
        "check_in": date.fromisoformat(raw["check_in"]),
        "check_out": date.fromisoformat(raw["check_out"]),
        "rating": float(rating.group(1).replace(",", ".")) if rating else None,
        "price_total_cop": price,
        # drop tracking query params (aid, label, srpvid…): long and personal-ish
        "url": urlsplit(url)._replace(query="", fragment="").geturl() if url else None,
    }


def clean_hotels(raw_rows: list[dict]) -> tuple[list[dict], int]:
    valid = [p for p in map(parse_hotel, raw_rows) if p]
    key = ("source", "name", "city", "check_in", "check_out")
    return _dedupe(valid, key, "price_total_cop"), len(raw_rows) - len(valid)


# ───────────────────────── cars ─────────────────────────

def parse_car(raw: dict) -> dict | None:
    lines = [line.strip() for line in (raw.get("text") or "").splitlines() if line.strip()]
    price = re.search(r"COP\s*([\d.,]+)", raw.get("text") or "")
    price_cop = digits(price.group(1)) if price else None
    if not lines or not raw.get("vendor") or not _in(price_cop, STAY_PRICE):
        return None
    category = re.search(r"or similar (.+?) car", raw["text"])
    return {
        "source": raw["source"],
        "vendor": raw["vendor"].strip(),
        "model": lines[0],
        "category": category.group(1) if category else None,
        "city": raw["city"],
        "pickup_date": date.fromisoformat(raw["pickup_date"]),
        "dropoff_date": date.fromisoformat(raw["dropoff_date"]),
        "price_total_cop": price_cop,
    }


def clean_cars(raw_rows: list[dict]) -> tuple[list[dict], int]:
    valid = [p for p in map(parse_car, raw_rows) if p]
    key = ("source", "vendor", "model", "city", "pickup_date", "dropoff_date")
    return _dedupe(valid, key, "price_total_cop"), len(raw_rows) - len(valid)


