"""Ingestion evidence from the Prefect API (survives container restarts, unlike docker logs).

Run inside the ingestion container:
  docker compose exec -T ingestion python - < scripts/ingestion_report.py
"""
import asyncio
import json
import re
from collections import Counter

from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import (
    ArtifactFilter, ArtifactFilterFlowRunId, DeploymentFilter, DeploymentFilterName,
    FlowRunFilter, FlowRunFilterId, LogFilter, LogFilterFlowRunId,
)
from prefect.client.schemas.sorting import FlowRunSort


async def main():
    async with get_client() as c:
        runs = await c.read_flow_runs(
            deployment_filter=DeploymentFilter(name=DeploymentFilterName(any_=["scheduled"])),
            sort=FlowRunSort.START_TIME_ASC, limit=50)
        for r in runs:
            if r.start_time is None:
                continue
            secs = (r.end_time - r.start_time).total_seconds() if r.end_time else None
            print(f"\n## {r.name}  state={r.state_name}  start={r.start_time:%Y-%m-%d %H:%M:%S}Z  "
                  f"duration={secs and round(secs)}s  auto_scheduled={r.auto_scheduled}  params={r.parameters}")
            arts = await c.read_artifacts(artifact_filter=ArtifactFilter(flow_run_id=ArtifactFilterFlowRunId(any_=[r.id])))
            for a in arts:
                for row in json.loads(a.data) if isinstance(a.data, str) else a.data:
                    print("   ", row)
            logs, offset = [], 0
            while page := await c.read_logs(log_filter=LogFilter(flow_run_id=LogFilterFlowRunId(any_=[r.id])),
                                            limit=200, offset=offset):
                logs += page
                offset += len(page)
            per_worker = Counter(m.group(1) for l in logs if (m := re.search(r"on Dask (worker-\d)", l.message)))
            if per_worker:
                print("    scrape attempts per Dask worker:", dict(sorted(per_worker.items())))


asyncio.run(main())
