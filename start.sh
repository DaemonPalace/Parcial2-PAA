#!/usr/bin/env bash
# Convenience wrapper. `docker compose up -d` alone is enough to run the stack.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

case "${1:-up}" in
  up)
    [ -f .env ] || cp .env.example .env
    docker compose up -d --build --wait
    cat <<URLS
WanderSync is up.
  GraphQL gateway   http://localhost:8000/graphql
  Prefect UI        http://localhost:4200
  Dask dashboard    http://localhost:8787
URLS
    ;;
  down)  docker compose down ;;
  reset) docker compose down -v ;;   # also deletes DB + Prefect volumes
  logs)  docker compose logs -f "${@:2}" ;;
  *) echo "usage: ./start.sh [up|down|reset|logs [service]]" >&2; exit 1 ;;
esac
