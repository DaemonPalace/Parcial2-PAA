"""Stage 07 + 08 acceptance checks against the live gateway (stdlib only, run from the host).

  python3 scripts/test_gateway.py

Needs docker compose (reads gateway logs to count pg_graphql round-trips, and
reads accounts.users / sessions to show what is actually stored).
"""
import functools
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

URL = "http://localhost:8000/graphql"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(line.strip().split("=", 1) for line in open(os.path.join(ROOT, ".env")) if "=" in line and not line.startswith("#"))
DEPART = date.today() + timedelta(days=7)
RETURN = DEPART + timedelta(days=3)
print = functools.partial(print, flush=True)
failures = 0


def check(label, cond, detail=""):
    global failures
    failures += not cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {label} {detail}")


def sh(cmd):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True).stdout


def sql(q):
    return sh(f'docker compose exec -T postgres psql -U supabase_admin -d postgres -At -c "{q}"').strip()


class Client:
    """A browser stand-in: keeps exactly one session cookie, like a real cookie jar."""

    def __init__(self, cookie=None):
        self.cookie = cookie

    def gql(self, query, variables=None, raw_path=None):
        req = urllib.request.Request(raw_path or URL, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Cookie": f"ws_session={self.cookie}"} if self.cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, headers, body = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, e.headers, e.read()
        for h in headers.get_all("Set-Cookie") or []:
            if h.startswith("ws_session="):
                self.cookie = h.split(";")[0].split("=", 1)[1]
                self.last_set_cookie = h
        try:
            return status, headers, json.loads(body)
        except ValueError:
            return status, headers, body.decode()


def gateway_log_since(t0):
    return sh(f"docker compose logs gateway --no-log-prefix --since {t0}")


SEARCH = """query($i: PackageSearchInput!) { packageAvailability(input: $i) {
  flights(limit: 3) { id airline departAt priceCop source }
  hotels(limit: 3) { id name priceTotalCop rating source }
  cars(limit: 3) { id vendor model priceTotalCop source }
  cheapestPackage { totalCop flight { id airline priceCop } hotel { id name priceTotalCop } car { id model priceTotalCop } } } }"""
SEARCH_VARS = {"i": {"origin": "BOG", "destination": "CTG", "departDate": DEPART.isoformat(), "returnDate": RETURN.isoformat()}}
LOGIN = "mutation($e: String!, $p: String!) { login(email: $e, password: $p) { user { id email role } userErrors { code message } } }"
REGISTER = "mutation($e: String!, $p: String!) { register(email: $e, password: $p) { user { id email role } userErrors { code message field } } }"
ME = "{ me { id email role } }"
BOOK = """mutation($i: BookPackageInput!) { bookPackage(input: $i) {
  order { id status totalCop } userErrors { code message } } }"""
ORDER = "query($id: ID!) { order(id: $id) { id status failureReason steps { name action status } } }"


def book(client, offers, chaos=None, key=None):
    i = {"idempotencyKey": key or str(uuid.uuid4()), "flightOfferId": offers[0], "hotelOfferId": offers[1], "carOfferId": offers[2]}
    if chaos:
        i["chaos"] = chaos
    return client.gql(BOOK, {"i": i})


def wait_order(client, order_id, timeout=90):
    seen, deadline = [], time.time() + timeout
    while time.time() < deadline:
        o = client.gql(ORDER, {"id": order_id})[2]["data"]["order"]
        if not seen or seen[-1] != o["status"]:
            seen.append(o["status"])
        if o["status"] in ("CONFIRMED", "CANCELLED", "REJECTED"):
            return o, seen
        time.sleep(1)
    return o, seen


# ───────────────────────── Stage 07 ─────────────────────────
print("\n## AC-07.1 one request returns a whole package search (flights + hotels + cars + cheapest combination)")
anon = Client()
t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
status, _, res = anon.gql(SEARCH, SEARCH_VARS)
pa = res["data"]["packageAvailability"]
check("flights, hotels, cars and cheapestPackage returned", all(pa[k] for k in ("flights", "hotels", "cars")) and pa["cheapestPackage"],
      f"(BOG→CTG {DEPART}→{RETURN}: {len(pa['flights'])} flights, {len(pa['hotels'])} hotels, {len(pa['cars'])} cars, "
      f"cheapest total {pa['cheapestPackage']['totalCop']:,} COP)")
print("    " + json.dumps(pa, ensure_ascii=False)[:900] + " …")
time.sleep(1)
trips = gateway_log_since(t0).count("pg_graphql round-trip")
check("whole search = exactly 1 DB round-trip", trips == 1, f"({trips})")

print("\n## AC-07.3 fewer requested fields -> fewer selected columns (no over-fetching)")
small = """query($i: PackageSearchInput!) { packageAvailability(input: $i) { flights(limit: 3) { priceCop } } }"""
t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
anon.gql(small, SEARCH_VARS)
time.sleep(1)
doc = [line for line in gateway_log_since(t0).splitlines() if "pg_graphql round-trip" in line]
print("    client asked: flights { priceCop }")
print("    gateway sent: " + (doc[-1].split("round-trip: ", 1)[1] if doc else "?"))
check("pg_graphql document selects only id + priceCop, no hotels/cars collections",
      bool(doc) and "node { id priceCop }" in doc[-1] and "hotelOffersCollection" not in doc[-1])

# users for the rest
pw = "Viajero-Seguro-2026"
alice, bob, admin = Client(), Client(), Client()
alice_email, bob_email = f"alice-{uuid.uuid4().hex[:6]}@test.co", f"bob-{uuid.uuid4().hex[:6]}@test.co"
alice.gql(REGISTER, {"e": alice_email, "p": pw})
bob.gql(REGISTER, {"e": bob_email, "p": pw})
admin.gql(LOGIN, {"e": ENV["ADMIN_EMAIL"], "p": ENV["ADMIN_PASSWORD"]})
offers = (pa["cheapestPackage"]["flight"]["id"], pa["cheapestPackage"]["hotel"]["id"], pa["cheapestPackage"]["car"]["id"])

print("\n## AC-07.4 bookPackage starts the Prefect SAGA; `order` follows its state transitions")
status, _, res = book(alice, offers)
order = res["data"]["bookPackage"]["order"]
check("bookPackage -> order PENDING immediately", order and order["status"] == "PENDING", f"({order})")
final, seen = wait_order(alice, order["id"])
check("order query shows the transitions, ends CONFIRMED", final["status"] == "CONFIRMED", f"(seen {' -> '.join(seen)})")
flow = sh(f"curl -s -X POST localhost:4200/api/flow_runs/filter -H 'Content-Type: application/json' "
          f"-d '{{\"flow_runs\":{{\"name\":{{\"any_\":[\"order-{order['id']}\"]}}}}}}'")
runs = json.loads(flow or "[]")
check("matching Prefect flow run exists", len(runs) == 1 and runs[0]["state_name"] == "Completed",
      f"(flow run '{runs[0]['name'] if runs else '-'}' {runs[0]['state_name'] if runs else ''})")

print("\n## AC-07.2 no N+1: nested offers for many orders = one round-trip per offer kind")
cheap = pa  # reuse search results for distinct offers
for k in range(2):
    book(alice, (cheap["flights"][k + 1]["id"], cheap["hotels"][k + 1]["id"], cheap["cars"][k + 1]["id"]))
time.sleep(1)
nested = "{ myOrders { id status flight { airline priceCop } hotel { name } car { model } } }"
t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1))
mine = alice.gql(nested)[2]["data"]["myOrders"]
time.sleep(1)
trips = gateway_log_since(t0).count("pg_graphql round-trip")
check(f"{len(mine)} orders x 3 nested offers resolved with {trips} catalog round-trips (not {len(mine) * 3})",
      len(mine) >= 3 and trips == 3)

print("\n## AC-07.5 only /graphql is exposed; abusive nesting is rejected")
for path in ("/docs", "/openapi.json", "/admin", "/orders"):
    code = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000" + path],
                          capture_output=True, text=True).stdout
    check(f"GET {path} -> 404", code == "404", f"({code})")
status, _, res = anon.gql("query Deep { __schema { types { fields { type { fields { type { fields { type { name } } } } } } } } }")
check("deeply nested introspection (cycle through fields/types) -> rejected", "Maximum introspection depth exceeded" in json.dumps(res),
      f"({res.get('errors', [{}])[0].get('message', '')})")
batch = "query Batch { " + " ".join(f'a{n}: packageAvailability(input: {{origin: "BOG", destination: "CTG", '
                                    f'departDate: "{DEPART}", returnDate: "{RETURN}"}}) {{ flights {{ id }} }}' for n in range(20)) + " }"
time.sleep(2)  # docker logs --since has 1 s granularity: keep earlier checks' round-trips out of the window
t0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
status, _, res = anon.gql(batch)
time.sleep(1)
check("alias batching (20 aliased searches in one request) -> rejected before touching the DB",
      "errors" in res and "aliases" in json.dumps(res).lower() and gateway_log_since(t0).count("pg_graphql round-trip") == 0,
      f"({res.get('errors', [{}])[0].get('message', '')})")

# ───────────────────────── Stage 08 ─────────────────────────
print("\n## AC-08.1 passwords stored as Argon2id with the configured cost; never plaintext")
row = sql(f"select email, left(password_hash, 40) from accounts.users where email = '{alice_email}'")
check("hash is $argon2id$v=19$m=65536,t=3,p=4$…", "$argon2id$v=19$m=65536,t=3,p=4$" in row, f"({row}…)")
check("plaintext password appears nowhere in accounts.users", sql(f"select count(*) from accounts.users where password_hash like '%{pw}%'") == "0")
print("\n## AC-08.1b register: policy + no user enumeration")
c = Client()
r = c.gql(REGISTER, {"e": alice_email, "p": pw})[2]["data"]["register"]
check("re-register an existing email -> generic INVALID_REGISTRATION (doesn't say 'exists')",
      r["userErrors"][0]["code"] == "INVALID_REGISTRATION" and "exist" not in r["userErrors"][0]["message"].lower(), f"({r['userErrors'][0]})")

print("\n## AC-08.2 session fixation: the pre-login session id is replaced at login and dies server-side")
victim = Client()
victim.gql(ME)
pre = victim.cookie
print(f"    pre-login cookie : ws_session={pre[:12]}…  ({victim.last_set_cookie.split(';', 1)[1].strip()})")
victim.gql(LOGIN, {"e": bob_email, "p": pw})
post = victim.cookie
print(f"    post-login cookie: ws_session={post[:12]}…")
check("login issues a NEW session id", post != pre)
fixed = Client(cookie=pre)  # attacker who planted / stole the pre-login id
me = fixed.gql(ME)[2]["data"]["me"]
check("old pre-login id is no longer valid (me = null, fresh anonymous id issued)", me is None and fixed.cookie != pre)
check("new id is authenticated", Client(cookie=post).gql(ME)[2]["data"]["me"]["email"] == bob_email)
planted = Client(cookie="attacker-chosen-session-id")
planted.gql(ME)
check("attacker-chosen id is never adopted (server issues its own)", planted.cookie != "attacker-chosen-session-id")
check("cookie flags HttpOnly + SameSite=Lax", "HttpOnly" in victim.last_set_cookie and "SameSite=lax" in victim.last_set_cookie,
      f"({victim.last_set_cookie.split(';', 1)[1].strip()})")
check("DB stores only sha256(token), never the cookie value",
      sql(f"select count(*) from accounts.sessions where token_hash = '{post}'") == "0"
      and len(sql("select token_hash from accounts.sessions limit 1")) == 64)

print("\n## AC-08.3 logout invalidates the session server-side")
before = Client(cookie=post)
before.gql("mutation { logout }")
check("the logged-out id no longer authenticates", Client(cookie=post).gql(ME)[2]["data"]["me"] is None)

print("\n## AC-08.5 authorization: users only see their own orders; chaos + ingestion are admin-only")
alice_order = mine[0]["id"]
bob = Client()
bob.gql(LOGIN, {"e": bob_email, "p": pw})
check("bob asks for alice's order -> null", bob.gql(ORDER, {"id": alice_order})[2]["data"]["order"] is None)
check("bob's myOrders doesn't include it", all(o["id"] != alice_order for o in bob.gql(nested)[2]["data"]["myOrders"]))
check("anonymous bookPackage -> UNAUTHENTICATED", book(Client(), offers)[2]["data"]["bookPackage"]["userErrors"][0]["code"] == "UNAUTHENTICATED")
res = book(bob, (cheap["flights"][2]["id"], cheap["hotels"][2]["id"], cheap["cars"][2]["id"]), chaos={"failAt": "CAR"})[2]
bob_final, _ = wait_order(bob, res["data"]["bookPackage"]["order"]["id"])
check("traveler's chaos flag is ignored (order still CONFIRMED)", bob_final["status"] == "CONFIRMED")
res = bob.gql("mutation { triggerIngestion { id state } }")[2]
check("traveler triggerIngestion -> FORBIDDEN", "FORBIDDEN" in json.dumps(res.get("errors")))
res = book(admin, (cheap["flights"][0]["id"], cheap["hotels"][0]["id"], cheap["cars"][0]["id"]), chaos={"failAt": "CAR"})[2]
adm_final, seen = wait_order(admin, res["data"]["bookPackage"]["order"]["id"])
comp = [s["name"] for s in adm_final["steps"] if s["action"] == "COMPENSATE"]
check("admin chaos car failure via GraphQL -> CANCELLED with CAR→HOTEL→FLIGHT→PAYMENT", adm_final["status"] == "CANCELLED"
      and comp == ["CAR", "HOTEL", "FLIGHT", "PAYMENT"], f"(seen {' -> '.join(seen)})")
res = admin.gql("mutation { triggerIngestion { id state } }")[2]
check("admin triggerIngestion -> Prefect flow run created", res.get("data") and res["data"]["triggerIngestion"]["state"] == "Scheduled",
      f"({res.get('data')})")

print("\n## AC-08.4 rate limits on login, register and checkout (bookPackage = payment path)")
print("    (waiting 61 s so earlier logins/registrations in this run don't count toward the windows)")
time.sleep(61)
r = Client().gql(REGISTER, {"e": f"x{uuid.uuid4().hex[:5]}@test.co", "p": "short"})[2]["data"]["register"]
check("password under 10 chars -> VALIDATION_ERROR on field password", r["userErrors"][0]["field"] == "password")
burst = Client()
codes = [burst.gql(LOGIN, {"e": bob_email, "p": "wrong-password-123"})[0] for _ in range(6)]
s, h, res = burst.gql(LOGIN, {"e": bob_email, "p": pw})
check("login: 5/min per IP, the next attempts get 429 + Retry-After (even with the right password)",
      codes[:5] == [200] * 5 and codes[5] == 429 and s == 429 and h.get("Retry-After"),
      f"(codes {codes + [s]}, Retry-After {h.get('Retry-After')}, error {res['data']['login']['userErrors'][0]['code']})")
regs = [Client().gql(REGISTER, {"e": f"r{uuid.uuid4().hex[:6]}@test.co", "p": pw})[0] for _ in range(3)]
check("register: 3/min per IP (1 used by the policy check above) -> 3rd of this burst is 429", regs == [200, 200, 429], f"(codes {regs})")
bk = [book(admin, (cheap["flights"][0]["id"], cheap["hotels"][0]["id"], cheap["cars"][0]["id"]))[0] for _ in range(6)]
check("bookPackage: 5/min per user -> 6th attempt 429", bk[:5] == [200] * 5 and bk[5] == 429, f"(codes {bk})")

print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
