"""FastAPI app factory shared by every service: one place for /health and logging."""
import logging
import os

import psycopg
from fastapi import FastAPI, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def make_app(name: str) -> FastAPI:
    app = FastAPI(title=name, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health(response: Response):
        # Healthy = this service's own DB role can log in and query.
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as conn:
                conn.execute("select 1")
        except psycopg.Error as exc:
            response.status_code = 503
            return {"service": name, "status": "db_unavailable", "error": type(exc).__name__}
        return {"service": name, "status": "ok"}

    return app
