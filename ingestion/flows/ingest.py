"""Travel-offer ingestion flow: Prefect orchestrates, Dask executes (docs/design.md §6).

Served on a cron schedule by the `ingestion` container; every task submitted with
.submit() runs as a Dask task on the dask-worker-* containers.
"""
import os

from distributed import get_client
from prefect import flow, get_run_logger, task
from prefect_dask import DaskTaskRunner

SCHEDULER = os.environ.get("DASK_SCHEDULER_ADDRESS", "tcp://dask-scheduler:8786")
EXPECTED_WORKERS = int(os.environ.get("DASK_EXPECTED_WORKERS", "3"))


@task(retries=3, retry_delay_seconds=5)
def check_cluster() -> int:
    """Runs on a Dask worker; fails (and is retried) until every worker has joined."""
    workers = len(get_client().nthreads())
    if workers < EXPECTED_WORKERS:
        raise RuntimeError(f"{workers}/{EXPECTED_WORKERS} Dask workers connected")
    return workers


@flow(name="ingest-travel-offers", task_runner=DaskTaskRunner(address=SCHEDULER))
def ingest() -> dict:
    workers = check_cluster.submit().result()
    get_run_logger().info("Dask cluster ready: %d workers", workers)
    return {"workers": workers}


if __name__ == "__main__":
    ingest.serve(name="scheduled", cron=os.environ.get("INGEST_CRON", "0 */6 * * *"))
