# Gate G2 — Stage 04 (Scraping + Dask + Prefect ingestion) — Gate report

**Date:** 2026-10-09 (runs logged in UTC, 2026-10-10 00:29–00:53Z) · **Commit:** stage-04 commit (this report is part of it) · **Status:** awaiting approval

## Built

- **Source spike** (T04.1): real sites tested from headless Chromium inside the worker image, giving Google Flights, Booking.com hotels and Booking.com Cars (`evidence/stage-04/AC-04.0_source-spike.md`). Mock sites weren't needed (Q-08 = real sites).
- **`ingestion/flows/scrapers.py`** (T04.2): one Selenium function per source. Browser setup and anti-detection come from `PA-Taller1`. Each function raises `ScrapeError` on empty or blocked pages so Prefect retries it.
- **`ingestion/flows/clean.py`** (T04.3): pure parsers and validators: COP parsing for both `.` and `,` separators, Spanish dates converted to Bogotá time, sanity bounds on prices, and dedupe that keeps the cheapest offer per natural key. **`ingestion/tests/test_clean.py`** has 8 tests built on real captured rows.
- **`ingestion/flows/ingest.py`** (T04.4–T04.7): Prefect 3 flow running on `DaskTaskRunner` (3 workers):
  1. `check_cluster`
  2. 28 parallel `scrape_*` tasks
  3. `clean_batch`
  4. bulk `upsert` (`ON CONFLICT` on the natural key; inventory never overwritten)
  5. a `ingestion-summary` table artifact

  Retry policies follow design §6.1. A source that stays down after retries doesn't fail the run; the rest still loads. Failure-injection parameters: `fail_attempts`, `break_source`. Served on `INGEST_CRON` (every 6 h).
- **`scripts/ingestion_report.py`**: rebuilds per-run summaries and per-worker counts from the Prefect API.
- Compose: the workers now get `DATABASE_URL` (as the `ingestion_svc` role), because the upserts run on them. `.env.example` has the `INGEST_*` plan variables.

## Acceptance criteria

| AC | Result | Evidence | How to reproduce |
|---|---|---|---|
| AC-04.0 *(added)* real sources chosen by spike | PASS | `AC-04.0_source-spike.md`, `AC-04.0_spike-*.png` | — |
| AC-04.1 run scrapes flights, hotels, cars and upserts; counts recorded | PASS: run 1 loaded 398 flights, 250 hotel stays, 223 car rentals from the live sites in 155 s | `AC-04.1_run-summary.txt`, `ingestion-runs-report.txt` | Prefect UI → Deployments → scheduled → Run, or `docker compose exec ingestion prefect deployment run 'ingest-travel-offers/scheduled' --watch` |
| AC-04.2 tasks distributed over ≥ 2 workers | PASS: all 3 workers used (e.g. 9/10/10 attempts) | `AC-04.2_worker-distribution.txt`, `AC-04.2_dask-dashboard-during-run.png` | http://localhost:8787 during a run |
| AC-04.3 transient failure → Retrying → Completed; permanent → Failed after retries, partial success | PASS: 20/20 flight and hotel tasks recovered, 3 of them after a real Booking.com error on attempt 2. 8/8 Booking Cars tasks Failed after 4 attempts. The flow still Completed and loaded flights and hotels | `AC-04.3_retries.txt`, `AC-04.3_prefect-retries-and-failures.png` | `... deployment run ... --param fail_attempts=1 --param break_source=booking_cars --watch` |
| AC-04.4 re-run creates no duplicates | PASS: 0 duplicate natural keys. Flights and cars re-runs insert 0 rows and only update prices. Inventory of scraped offers is untouched | `AC-04.4_dedupe.txt` | SQL in the file |
| AC-04.5 malformed records rejected and counted | PASS (8/8 tests). `rejected` is reported per category in every run | `AC-04.5_rejects.txt` | `docker compose run --rm --no-deps ingestion python -m unittest discover -s tests -v` |
| AC-04.6 catalog reads stay within baseline during ingestion | PASS, with a caveat (see risks): the median went from ≈ 47 ms to ≈ 59 ms and the worst case from 74 ms to 159 ms. No request failed or blocked | `AC-04.6_latency.txt` | samples in the file |
| AC-04.7 scheduled run fires without manual action | PASS: `auto_scheduled=True` run 'delectable-taipan' started 3 s after its cron slot and Completed | `AC-04.7_schedule.txt`, `AC-04.7_prefect-runs.png` | — |

## Deviations from spec
- **Booking.com Cars replaces the Kayak/Rentalcars candidates for cars,** based on the spike. `docs/design.md` §6 is updated.
- **The plan is 28 tasks, not the design draft's ~48.** That keeps a run to about 2.5 min for the demo. It can be changed through `INGEST_*` env.
- **AC-04.0 added.**

## Bug found and fixed during verification
- **Flight duration was empty.** `duration_minutes` was NULL for every scraped flight in runs 1–4 because Google puts U+00A0 non-breaking spaces between number and unit ("1 h 30 min"). Fixed by normalising whitespace in `clean.parse_flight`, plus a regression test. Run 5 ('impossible-asp') refreshed every row, and there are now 0 NULLs (`AC-04.1_run-summary.txt`).

## Open risks / known limits
- **Real sites can change or block at any time.** If they do, the affected tasks fail visibly in Prefect and seed data keeps the booking demo working (D-006). For the live demo I recommend running one ingestion about 10 minutes before presenting.
- **Searches outside the plan are served by seed offers only.** Scraped offers exist only for the planned routes, dates (+7 and +14 days) and 3-night stays.
- **Catalog latency rises somewhat during ingestion (AC-04.6).** Three Chromium instances share the same host CPU as Postgres. On separate machines this coupling wouldn't exist. I'm marking it PASS because nothing blocked or failed. If you want a strict "within baseline" threshold instead, this is the one AC to look at.
- **Hotels change between runs.** Booking.com lists a different mix of properties on each page load, so each run adds some new hotel rows. These are new properties, not duplicates.
- **Scraped inventory is simulated.** Scraped offers get 5 seats, rooms or units (ADR-07), because the sites don't publish counts.

## Approval
- [ ] Approved by user — date: ____
