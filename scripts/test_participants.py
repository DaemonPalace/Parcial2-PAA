"""Stage 05 checks against the live flights/hotels/cars services (stdlib only).

Run inside the compose network:
  docker compose exec -T orders-billing-svc python - < scripts/test_participants.py
Every reservation it makes is cancelled again, so inventory ends where it started.
"""
import json
import socket
import threading
import urllib.error
import urllib.request
import uuid

SERVICES = {"flights": ("http://flights-svc:8000", 101), "hotels": ("http://hotels-svc:8000", 101),
            "cars": ("http://cars-svc:8000", 101)}
failures = 0


def call(method, url, body=None, timeout=15):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "null")


def check(label, cond, detail=""):
    global failures
    failures += not cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")


for name, (base, offer) in SERVICES.items():
    avail = lambda: call("GET", f"{base}/offers/{offer}")[1]["available"]
    reserve = lambda oid, chaos=None, timeout=15: call("POST", f"{base}/reservations",
                                                      {"order_id": oid, "offer_id": offer, "chaos": chaos}, timeout)
    cancel = lambda oid, flaky=False: call("POST", f"{base}/reservations/{oid}/cancel", {"flaky": flaky})
    start = avail()
    print(f"\n### {name}-svc  offer {offer}  available at start = {start}")

    print("AC-05.1 reserve / cancel in isolation")
    o1 = str(uuid.uuid4())
    s, b = reserve(o1)
    check("reserve -> 201", s == 201, f"({s} {b})")
    check("inventory -1", avail() == start - 1, f"(now {avail()})")
    s, b = cancel(o1)
    check("cancel -> released", s == 200 and b["result"] == "released", f"({s} {b})")
    check("inventory restored", avail() == start)

    print("AC-05.2 idempotent replay")
    o2 = str(uuid.uuid4())
    reserve(o2)
    s, b = reserve(o2)
    check("same order_id again -> 200 replay, no second unit", s == 200 and b["replay"] and avail() == start - 1, f"({s} {b})")
    cancel(o2)

    print("AC-05.3 compensation idempotent and safe without a forward step")
    s, b = cancel(o2)
    check("second cancel -> already_cancelled, inventory unchanged", b["result"] == "already_cancelled" and avail() == start, f"({b})")
    o3 = str(uuid.uuid4())
    s, b = cancel(o3)
    check("cancel before any reserve -> tombstone", b["result"] == "tombstone", f"({b})")
    s, b = reserve(o3)
    check("late reserve after tombstone -> 410, nothing taken", s == 410 and avail() == start, f"({s} {b})")

    print("AC-05.4 two concurrent reserves on the last unit")
    fillers = [str(uuid.uuid4()) for _ in range(start - 1)]
    for o in fillers:
        reserve(o)
    check(f"{len(fillers)} fillers leave exactly 1 unit", avail() == 1)
    racers, results = [str(uuid.uuid4()), str(uuid.uuid4())], []
    threads = [threading.Thread(target=lambda o=o: results.append(reserve(o)[0])) for o in racers]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("exactly one 201 and one 409 SOLD_OUT", sorted(results) == [201, 409], f"({results})")
    check("inventory 0, never negative", avail() == 0)
    for o in fillers + racers:
        cancel(o)
    check("all released -> back to start", avail() == start)

    print("AC-05.5 failure injection modes")
    o5 = str(uuid.uuid4())
    s, b = reserve(o5, {"fail": "REJECT"})
    check("chaos REJECT -> 422, no side effect", s == 422 and avail() == start, f"({s} {b})")
    o6 = str(uuid.uuid4())
    try:
        s = reserve(o6, {"fail": "TIMEOUT"}, timeout=5)[0]
    except (socket.timeout, TimeoutError, urllib.error.URLError):
        s = "client timeout"
    check("chaos TIMEOUT -> client times out at 5 s ...", s == "client timeout", f"({s})")
    check("... but the reservation committed (the orphan risk)", avail() == start - 1)
    s, b = cancel(o6)
    check("compensation finds it and releases the unit", b["result"] == "released" and avail() == start, f"({b})")
    o7 = str(uuid.uuid4())
    reserve(o7)
    s1, _ = cancel(o7, flaky=True)
    s2, b2 = cancel(o7, flaky=True)
    check("flaky compensation: 503 first, 200 on retry", (s1, s2) == (503, 200) and b2["result"] == "released", f"({s1}, {s2})")
    check("inventory back to start", avail() == start)

print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
