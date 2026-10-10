"""FastAPI app factory shared by every service: one place for /health and logging."""
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def make_app(name: str) -> FastAPI:
    app = FastAPI(title=name)

    @app.get("/health")
    def health():
        return {"service": name, "status": "ok"}

    return app
