"""Runs every booking SAGA case against the live orders-billing service (stdlib only).

  docker compose exec -T orders-billing-svc python - < scripts/simulate_saga.py            # all cases
  docker compose exec -T orders-billing-svc python - car_fails < scripts/simulate_saga.py  # one case

Each case uses its own offers, checks the final state, the compensation order and
that inventory ends where it should. Prefect shows one flow run per order.
"""
import json
import functools
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

ORDERS = "http://orders-billing-svc:8000"
SVC = {"FLIGHT": "http://flights-svc:8000", "HOTEL": "http://hotels-svc:8000", "CAR": "http://cars-svc:8000"}
USER = "00000000-0000-0000-0000-00000000a11e"

# case: (chaos, expected status, expected successful compensations in order)
CASES = {
    "happy_path":       (None, "CONFIRMED", []),
    "payment_fails":    ({"failAt": "PAYMENT"}, "REJECTED", []),
    "flight_fails":     ({"failAt": "FLIGHT"}, "CANCELLED", ["FLIGHT", "PAYMENT"]),
    "hotel_fails":      ({"failAt": "HOTEL"}, "CANCELLED", ["HOTEL", "FLIGHT", "PAYMENT"]),
    "car_fails":        ({"failAt": "CAR"}, "CANCELLED", ["CAR", "HOTEL", "FLIGHT", "PAYMENT"]),
    "hotel_timeout":    ({"failAt": "HOTEL", "mode": "TIMEOUT"}, "CANCELLED", ["HOTEL", "FLIGHT", "PAYMENT"]),
    "flaky_compensation": ({"failAt": "CAR", "flakyCompensation": True}, "CANCELLED", ["CAR", "HOTEL", "FLIGHT", "PAYMENT"]),
}
failures = 0
print = functools.partial(print, flush=True)  # stream progress through docker exec


def call(method, url, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(label, cond, detail=""):
    global failures
    failures += not cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")


def available(offers):
    return {k: call("GET", f"{SVC[k]}/offers/{v}")[1]["available"] for k, v in offers.items()}


def wait_terminal(order_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        order = call("GET", f"{ORDERS}/orders/{order_id}")[1]
        if order["status"] in ("CONFIRMED", "CANCELLED", "REJECTED"):
            return order
        time.sleep(1)
    return order


def run_case(n, name):
    chaos, expected, expected_comp = CASES[name]
    offers = {"FLIGHT": 300 + n, "HOTEL": 300 + n, "CAR": 300 + n}
    before = available(offers)
    print(f"\n### {name}   chaos={chaos}")
    status, order = call("POST", f"{ORDERS}/orders", {
        "idempotency_key": str(uuid.uuid4()), "user_id": USER, "chaos": chaos,
        "flight_offer_id": offers["FLIGHT"], "hotel_offer_id": offers["HOTEL"], "car_offer_id": offers["CAR"]})
    check("POST /orders -> 201 PENDING", status == 201 and order["status"] == "PENDING",
          f"(order {order.get('id')}, total {order.get('total_cop'):,} COP)")
    order = wait_terminal(order["id"])
    for s in order["steps"]:
        print(f"      {s['action']:10} {s['name']:7} {s['status']:9} {(s['error'] or '')[:90]}")
    comp = [s["name"] for s in order["steps"] if s["action"] == "COMPENSATE" and s["status"] == "SUCCEEDED"]
    check(f"final status {expected}", order["status"] == expected, f"(got {order['status']}; reason: {order['failure_reason']})")
    check("compensations in reverse order", comp == expected_comp, f"({' -> '.join(comp) or 'none'})")
    after = available(offers)
    want = {k: before[k] - (1 if expected == "CONFIRMED" else 0) for k in before}
    check("inventory consistent", after == want, f"(before {before} after {after})")
    pay = {"CONFIRMED": "CHARGED", "CANCELLED": "REFUNDED", "REJECTED": None}[expected]
    check(f"payment {pay}", order["payment_status"] == pay, f"(got {order['payment_status']})")
    if name == "flaky_compensation":
        failed_first = [s["name"] for s in order["steps"] if s["action"] == "COMPENSATE" and s["status"] == "FAILED"]
        check("each cancel failed once, Prefect retried it", failed_first == ["CAR", "HOTEL", "FLIGHT"], f"({failed_first})")


def idempotent_retry():
    print("\n### idempotent_retry   same idempotency_key sent 3x concurrently, then once more")
    offers = {"FLIGHT": 320, "HOTEL": 320, "CAR": 320}
    before = available(offers)
    body = {"idempotency_key": str(uuid.uuid4()), "user_id": USER,
            "flight_offer_id": 320, "hotel_offer_id": 320, "car_offer_id": 320}
    results = []
    threads = [threading.Thread(target=lambda: results.append(call("POST", f"{ORDERS}/orders", body))) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ids = {r[1]["id"] for r in results}
    check("3 concurrent requests -> one order", len(ids) == 1, f"(codes {sorted(r[0] for r in results)})")
    order = wait_terminal(ids.pop())
    status, again = call("POST", f"{ORDERS}/orders", body)
    check("replay after completion -> 200, same order, same final state",
          status == 200 and again["id"] == order["id"] and again["status"] == "CONFIRMED", f"({status} {again['status']})")
    forward = [s["name"] for s in order["steps"] if s["action"] == "FORWARD"]
    check("saga ran exactly once (one step each)", forward == ["PAYMENT", "FLIGHT", "HOTEL", "CAR"], f"({forward})")
    check("exactly one unit taken per offer", available(offers) == {k: v - 1 for k, v in before.items()})


selected = sys.argv[1:] or [*CASES, "idempotent_retry"]
for i, case in enumerate(selected):
    idempotent_retry() if case == "idempotent_retry" else run_case(list(CASES).index(case), case)
print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
