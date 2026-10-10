#!/usr/bin/env bash
# Full regression against a running stack: every stage's acceptance checks, in order.
#   ./scripts/e2e_all.sh <output-dir>
# Takes ~12 min (real-site scraping + SAGA delays + one 61 s rate-limit window).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OUT="${1:?usage: e2e_all.sh <output-dir>}"
mkdir -p "$OUT"
chmod 777 "$OUT"   # the Selenium container writes screenshots as its own user
ADMIN_EMAIL=$(grep ^ADMIN_EMAIL= .env | cut -d= -f2)
ADMIN_PASSWORD=$(grep ^ADMIN_PASSWORD= .env | cut -d= -f2)
status=0

run() {  # run <name> <command...>: tees output, records PASS/FAIL from the last line / exit code
  local name=$1; shift
  echo "=== $name"
  "$@" > "$OUT/$name.txt" 2>&1
  local rc=$?
  if [ $rc -ne 0 ] || grep -qE "\[FAIL\]|CHECK\(S\) FAILED" "$OUT/$name.txt"; then echo "    FAIL (see $OUT/$name.txt)"; status=1; else echo "    PASS"; fi
  tail -1 "$OUT/$name.txt" | sed 's/^/    /'
}

run 01-containers-healthy bash -c '
  docker compose ps --format "{{.Service}} {{.Status}}"
  total=$(docker compose ps --format "{{.Service}}" | wc -l); healthy=$(docker compose ps --format "{{.Status}}" | grep -c "(healthy)")
  echo "$healthy/$total containers healthy"; [ "$healthy" -eq "$total" ] && [ "$total" -eq 13 ]'
run 02-ingestion-real-sites bash -c '
  docker compose exec -T ingestion prefect deployment run "ingest-travel-offers/scheduled" --watch | tail -3
  docker compose exec -T ingestion python - < scripts/ingestion_report.py | tail -5'
run 03-ingestion-parser-tests docker compose exec -T ingestion python -m unittest discover -s tests
run 04-participants docker compose exec -T orders-billing-svc python - < scripts/test_participants.py
run 05-saga-cases docker compose exec -T orders-billing-svc python - < scripts/simulate_saga.py
run 06-reconciliation bash -c '
  out=$(docker compose exec -T postgres psql -U supabase_admin -d postgres -f - < scripts/reconcile.sql); echo "$out"
  ! echo "$out" | grep -E "\|\s+[1-9][0-9]*$"'
run 07-gateway-security python3 -I scripts/test_gateway.py
sleep 61  # leave the login rate-limit window the gateway suite just used
OUT_ABS=$(cd "$OUT" && pwd)
run 08-browser-e2e docker run --rm --network host --shm-size=1g -v "$PWD:/w:z" -v "$OUT_ABS:/out:z" -w /w --entrypoint python \
    wandersync-ingestion scripts/ui_e2e.py /out "$ADMIN_EMAIL" "$ADMIN_PASSWORD"
run 09-reconciliation-final bash -c '
  out=$(docker compose exec -T postgres psql -U supabase_admin -d postgres -f - < scripts/reconcile.sql); echo "$out"
  ! echo "$out" | grep -E "\|\s+[1-9][0-9]*$"'

echo; [ $status -eq 0 ] && echo "REGRESSION: ALL PASSED" || echo "REGRESSION: FAILURES (see $OUT)"
exit $status
