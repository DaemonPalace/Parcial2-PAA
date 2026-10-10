# One image for dask-scheduler, dask-worker-* and the ingestion runner (ADR-04):
# Dask requires identical library versions on client, scheduler and workers,
# and workers must be able to import the flow's task functions.
FROM python:3.12-slim

# Chromium + chromedriver from Debian, already version-matched
# (same approach as PA-Taller1/scripts/Dockerfile).
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flows/ flows/
COPY tests/ tests/
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

USER app
CMD ["python", "flows/ingest.py"]
