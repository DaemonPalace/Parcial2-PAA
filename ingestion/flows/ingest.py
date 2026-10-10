"""Travel-offer ingestion flow: Prefect orchestrates, Dask executes (docs/design.md §6).

Served on a cron schedule by the `ingestion` container. Every task below is
submitted with .submit(), so DaskTaskRunner runs it on one of the dask-worker-*
containers — scraping (one headless Chromium per task), cleaning and the bulk
upsert into Postgres all happen on the cluster, never in the API services.
"""
import os
from datetime import date, timedelta

import psycopg
from distributed import get_client, get_worker
from prefect import flow, get_run_logger, task
from prefect.artifacts import create_table_artifact
from prefect.runtime import task_run
from prefect.tasks import exponential_backoff
from prefect_dask import DaskTaskRunner

from flows import clean, scrapers

SCHEDULER = os.environ.get("DASK_SCHEDULER_ADDRESS", "tcp://dask-scheduler:8786")
EXPECTED_WORKERS = int(os.environ.get("DASK_EXPECTED_WORKERS", "3"))

CITY_NAMES = {"BOG": "Bogotá", "MDE": "Medellín", "CLO": "Cali", "CTG": "Cartagena",
              "SMR": "Santa Marta", "BAQ": "Barranquilla"}


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# ───────────────────────── tasks ─────────────────────────

@task(retries=3, retry_delay_seconds=5)
def check_cluster() -> int:
    """Runs on a Dask worker; fails (and is retried) until every worker has joined."""
    workers = len(get_client().nthreads())
    if workers < EXPECTED_WORKERS:
        raise RuntimeError(f"{workers}/{EXPECTED_WORKERS} Dask workers connected")
    return workers


def _chaos(source: str, fail_attempts: int, break_source: str) -> None:
    """Demo failure injection (T04.7): fail the first N attempts, or always fail one source."""
    get_run_logger().info("attempt %d on Dask %s", task_run.run_count, get_worker().name)
    if source == break_source:
        raise scrapers.ScrapeError(f"chaos: source {source} forced down")
    if task_run.run_count <= fail_attempts:
        raise scrapers.ScrapeError(f"chaos: transient failure on attempt {task_run.run_count}")


SCRAPE_RETRIES = dict(retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=10), retry_jitter_factor=0.5)


@task(task_run_name="scrape-flights-{origin}-{destination}-{day}", **SCRAPE_RETRIES)
def scrape_flights(origin: str, destination: str, day: date, fail_attempts: int = 0, break_source: str = "") -> list[dict]:
    _chaos("google_flights", fail_attempts, break_source)
    return scrapers.scrape_google_flights(origin, destination, day)


@task(task_run_name="scrape-hotels-{city}-{check_in}", **SCRAPE_RETRIES)
def scrape_hotels(city: str, check_in: date, check_out: date, fail_attempts: int = 0, break_source: str = "") -> list[dict]:
    _chaos("booking", fail_attempts, break_source)
    return scrapers.scrape_booking_hotels(CITY_NAMES[city], city, check_in, check_out)


@task(task_run_name="scrape-cars-{city}-{pickup}", **SCRAPE_RETRIES)
def scrape_cars(city: str, pickup: date, dropoff: date, fail_attempts: int = 0, break_source: str = "") -> list[dict]:
    _chaos("booking_cars", fail_attempts, break_source)
    return scrapers.scrape_booking_cars(city, pickup, dropoff)


@task
def clean_batch(kind: str, raw: list[dict]) -> tuple[list[dict], int]:
    return {"flights": clean.clean_flights, "hotels": clean.clean_hotels, "cars": clean.clean_cars}[kind](raw)


# Inventory columns are deliberately absent: set by the column default on insert,
# never overwritten by a re-scrape (ADR-07; the DB role can't update them anyway).
UPSERT_SQL = {
    "flights": """
        insert into flights.flight_offers
            (source, airline, origin, destination, depart_at, arrive_at, duration_minutes, stops, price_cop)
        values (%(source)s, %(airline)s, %(origin)s, %(destination)s, %(depart_at)s, %(arrive_at)s,
                %(duration_minutes)s, %(stops)s, %(price_cop)s)
        on conflict (source, airline, origin, destination, depart_at) do update set
            price_cop = excluded.price_cop, arrive_at = excluded.arrive_at,
            duration_minutes = excluded.duration_minutes, stops = excluded.stops, scraped_at = now()
        returning (xmax = 0) as inserted""",
    "hotels": """
        insert into hotels.hotel_offers (source, name, city, check_in, check_out, rating, price_total_cop, url)
        values (%(source)s, %(name)s, %(city)s, %(check_in)s, %(check_out)s, %(rating)s, %(price_total_cop)s, %(url)s)
        on conflict (source, name, city, check_in, check_out) do update set
            price_total_cop = excluded.price_total_cop, rating = excluded.rating, url = excluded.url, scraped_at = now()
        returning (xmax = 0) as inserted""",
    "cars": """
        insert into cars.car_offers (source, vendor, model, category, city, pickup_date, dropoff_date, price_total_cop)
        values (%(source)s, %(vendor)s, %(model)s, %(category)s, %(city)s, %(pickup_date)s, %(dropoff_date)s, %(price_total_cop)s)
        on conflict (source, vendor, model, city, pickup_date, dropoff_date) do update set
            price_total_cop = excluded.price_total_cop, category = excluded.category, scraped_at = now()
        returning (xmax = 0) as inserted""",
}


@task(retries=2, retry_delay_seconds=5)
def upsert(kind: str, rows: list[dict]) -> dict:
    """One transaction per category; returns how many rows were new vs refreshed."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.executemany(UPSERT_SQL[kind], rows, returning=True)
        flags = []
        while True:
            flags.append(cur.fetchone()[0])
            if not cur.nextset():
                break
    inserted = sum(flags)
    return {"inserted": inserted, "updated": len(flags) - inserted}


# ───────────────────────── flow ─────────────────────────

@flow(name="ingest-travel-offers", task_runner=DaskTaskRunner(address=SCHEDULER))
def ingest(fail_attempts: int = 0, break_source: str = "") -> dict:
    """fail_attempts / break_source: demo failure injection (see _chaos)."""
    log = get_run_logger()
    workers = check_cluster.submit().result()
    log.info("Dask cluster ready: %d workers", workers)

    today = date.today()
    days = [today + timedelta(days=int(d)) for d in _env_list("INGEST_DAYS_AHEAD", "7,14")]
    nights = int(os.environ.get("INGEST_STAY_NIGHTS", "3"))
    routes = [r.split("-") for r in _env_list("INGEST_ROUTES", "BOG-CTG,CTG-BOG,BOG-MDE,MDE-BOG,BOG-SMR,SMR-BOG")]
    cities = sorted({dest for _, dest in routes})
    chaos = dict(fail_attempts=fail_attempts, break_source=break_source)

    # Fan out: every scrape is an independent Dask task.
    scraped = {
        "flights": [scrape_flights.submit(o, d, day, **chaos) for o, d in routes for day in days],
        "hotels": [scrape_hotels.submit(c, day, day + timedelta(days=nights), **chaos) for c in cities for day in days],
        "cars": [scrape_cars.submit(c, day, day + timedelta(days=nights), **chaos) for c in cities for day in days],
    }

    summary = []
    for kind, futures in scraped.items():
        raw, failed = [], 0
        for future in futures:
            try:  # partial success: a source that stays down after its retries doesn't sink the run
                raw.extend(future.result())
            except Exception as exc:  # noqa: BLE001 — task already Failed in Prefect; just count it
                failed += 1
                log.warning("%s task failed after retries: %s", kind, exc)
        rows, rejected = clean_batch.submit(kind, raw).result()
        written = upsert.submit(kind, rows).result()
        summary.append({"kind": kind, "scrape_tasks": len(futures), "failed_tasks": failed,
                        "raw_rows": len(raw), "rejected": rejected, "valid": len(rows), **written})

    create_table_artifact(key="ingestion-summary", table=summary, description="Rows per category for this run")
    for row in summary:
        log.info("summary %s", row)
    return {"workers": workers, "summary": summary}


if __name__ == "__main__":
    ingest.serve(name="scheduled", cron=os.environ.get("INGEST_CRON", "0 */6 * * *"))
