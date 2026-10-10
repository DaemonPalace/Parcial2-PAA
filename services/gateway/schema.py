"""GraphQL schema — implements docs/schema.graphql (checked by evidence/stage-07/AC-07.0)."""
import os
import re
from datetime import date, datetime
from enum import Enum
from typing import Optional, get_args

import httpx
import strawberry
from strawberry.dataloader import DataLoader
from strawberry.types import Info
from strawberry.types.nodes import FragmentSpread, InlineFragment

import catalog
import security

ORDERS_URL = os.environ.get("ORDERS_SERVICE_URL", "http://orders-billing-svc:8000")
PREFECT_API = os.environ.get("PREFECT_API_URL", "http://prefect-server:4200/api")
IATA = re.compile(r"^[A-Z]{3}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
CITIES = {"BOG": "Bogotá", "MDE": "Medellín", "CLO": "Cali", "CTG": "Cartagena",
          "SMR": "Santa Marta", "BAQ": "Barranquilla"}
MAX_STAY_NIGHTS = 7


# ───────────────────────── enums ─────────────────────────

@strawberry.enum
class Role(Enum):
    TRAVELER = "TRAVELER"
    ADMIN = "ADMIN"


@strawberry.enum
class OrderStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CONFIRMED = "CONFIRMED"
    COMPENSATING = "COMPENSATING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@strawberry.enum
class SagaStepName(Enum):
    PAYMENT = "PAYMENT"
    FLIGHT = "FLIGHT"
    HOTEL = "HOTEL"
    CAR = "CAR"


@strawberry.enum
class SagaAction(Enum):
    FORWARD = "FORWARD"
    COMPENSATE = "COMPENSATE"


@strawberry.enum
class StepStatus(Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@strawberry.enum
class FailMode(Enum):
    REJECT = "REJECT"
    TIMEOUT = "TIMEOUT"


@strawberry.enum
class SortOrder(Enum):
    PRICE_ASC = "PRICE_ASC"
    PRICE_DESC = "PRICE_DESC"


@strawberry.enum
class UserErrorCode(Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_REGISTRATION = "INVALID_REGISTRATION"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    OFFER_NOT_FOUND = "OFFER_NOT_FOUND"
    OFFER_UNAVAILABLE = "OFFER_UNAVAILABLE"


# ───────────────────────── catalog types ─────────────────────────

def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _from_node(cls, node: dict):
    """pg_graphql node (camelCase, BigInt/BigFloat as strings) -> Strawberry object.
    Fields the client didn't select (so weren't fetched) are simply None."""
    values = {_snake(k): v for k, v in node.items()}
    hints = cls.__annotations__
    for key, value in list(values.items()):
        types = get_args(hints.get(key)) or (hints.get(key),)
        if value is None:
            continue
        if datetime in types:
            values[key] = datetime.fromisoformat(value)
        elif date in types:
            values[key] = date.fromisoformat(value)
        elif float in types:
            values[key] = float(value)
    return cls(**{f: values.get(f) for f in hints})


@strawberry.type
class City:
    code: str
    name: str


@strawberry.type
class FlightOffer:
    id: strawberry.ID
    source: str
    airline: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: Optional[datetime]
    duration_minutes: Optional[int]
    stops: Optional[int]
    price_cop: int
    seats_available: int
    scraped_at: datetime


@strawberry.type
class HotelOffer:
    id: strawberry.ID
    source: str
    name: str
    city: str
    check_in: date
    check_out: date
    rating: Optional[float]
    price_total_cop: int
    rooms_available: int
    url: Optional[str]
    scraped_at: datetime


@strawberry.type
class CarOffer:
    id: strawberry.ID
    source: str
    vendor: str
    model: str
    category: Optional[str]
    city: str
    pickup_date: date
    dropoff_date: date
    price_total_cop: int
    units_available: int
    scraped_at: datetime


TYPE_OF = {"flights": FlightOffer, "hotels": HotelOffer, "cars": CarOffer}


@strawberry.type
class Package:
    flight: FlightOffer
    hotel: HotelOffer
    car: CarOffer
    total_cop: int


@strawberry.type
class PackageAvailability:
    """Everything below was fetched by the parent resolver in one pg_graphql round-trip;
    these resolvers only hand out the prefetched lists (limit/sort were applied in SQL)."""
    _rows: strawberry.Private[dict]

    @strawberry.field
    def flights(self, limit: Optional[int] = 10, sort: Optional[SortOrder] = SortOrder.PRICE_ASC) -> list[FlightOffer]:
        return self._rows.get("flights", [])

    @strawberry.field
    def hotels(self, limit: Optional[int] = 10, sort: Optional[SortOrder] = SortOrder.PRICE_ASC) -> list[HotelOffer]:
        return self._rows.get("hotels", [])

    @strawberry.field
    def cars(self, limit: Optional[int] = 10, sort: Optional[SortOrder] = SortOrder.PRICE_ASC) -> list[CarOffer]:
        return self._rows.get("cars", [])

    @strawberry.field(description="Cheapest available flight + hotel + car, null if any component is missing.")
    def cheapest_package(self) -> Optional[Package]:
        return self._rows.get("cheapest")


@strawberry.input
class PackageSearchInput:
    origin: str
    destination: str
    depart_date: date
    return_date: date


def _selections(selections) -> dict:
    """Flatten a Strawberry selection set (incl. fragments) to {fieldName: SelectedField}."""
    out = {}
    for sel in selections:
        if isinstance(sel, (FragmentSpread, InlineFragment)):
            out.update(_selections(sel.selections))
        elif not sel.name.startswith("__"):
            out[sel.name] = sel
    return out


# ───────────────────────── accounts / orders types ─────────────────────────

@strawberry.type
class User:
    id: strawberry.ID
    email: str
    role: Role
    created_at: datetime


@strawberry.type
class UserError:
    code: UserErrorCode
    message: str
    field: Optional[str] = None


@strawberry.type
class AuthPayload:
    user: Optional[User]
    user_errors: list[UserError]


@strawberry.type
class SagaStep:
    name: SagaStepName
    action: SagaAction
    status: StepStatus
    error: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]


@strawberry.type
class Order:
    id: strawberry.ID
    status: OrderStatus
    total_cop: int
    failure_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    steps: list[SagaStep]
    _offer_ids: strawberry.Private[dict]

    @strawberry.field
    async def flight(self, info: Info) -> Optional[FlightOffer]:
        return await info.context["loaders"]["flights"].load(self._offer_ids["flights"])

    @strawberry.field
    async def hotel(self, info: Info) -> Optional[HotelOffer]:
        return await info.context["loaders"]["hotels"].load(self._offer_ids["hotels"])

    @strawberry.field
    async def car(self, info: Info) -> Optional[CarOffer]:
        return await info.context["loaders"]["cars"].load(self._offer_ids["cars"])


def to_order(o: dict) -> Order:
    return Order(
        id=o["id"], status=OrderStatus(o["status"]), total_cop=o["total_cop"], failure_reason=o["failure_reason"],
        created_at=datetime.fromisoformat(o["created_at"]), updated_at=datetime.fromisoformat(o["updated_at"]),
        steps=[SagaStep(name=SagaStepName(s["name"]), action=SagaAction(s["action"]), status=StepStatus(s["status"]),
                        error=s["error"], started_at=datetime.fromisoformat(s["started_at"]),
                        ended_at=datetime.fromisoformat(s["ended_at"]) if s["ended_at"] else None)
               for s in o.get("steps", [])],
        _offer_ids={"flights": o["flight_offer_id"], "hotels": o["hotel_offer_id"], "cars": o["car_offer_id"]},
    )


def make_loaders(pool) -> dict:
    """Per request (never shared between users): one catalog round-trip per offer kind."""
    def loader(kind):
        async def load(ids):
            found = await catalog.offers_by_id(pool, kind, list(ids))
            return [_from_node(TYPE_OF[kind], found[i]) if i in found else None for i in ids]
        return DataLoader(load_fn=load)
    return {kind: loader(kind) for kind in TYPE_OF}


@strawberry.input
class ChaosInput:
    fail_at: SagaStepName
    mode: Optional[FailMode] = FailMode.REJECT
    flaky_compensation: Optional[bool] = False


@strawberry.input
class BookPackageInput:
    idempotency_key: strawberry.ID
    flight_offer_id: strawberry.ID
    hotel_offer_id: strawberry.ID
    car_offer_id: strawberry.ID
    chaos: Optional[ChaosInput] = strawberry.UNSET


@strawberry.type
class BookPackagePayload:
    order: Optional[Order]
    user_errors: list[UserError]


@strawberry.type
class IngestionRun:
    id: strawberry.ID
    state: str


# ───────────────────────── helpers ─────────────────────────

def _user(info: Info) -> dict | None:
    return info.context["request"].state.session["user"]


def _ip(info: Info) -> str:
    return info.context["request"].client.host


def _limited(info: Info, bucket: str, key: str) -> UserError | None:
    """Rate limit per GraphQL operation (design §7.3): 429 + Retry-After AND a typed error."""
    wait = security.hit(bucket, key)
    if not wait:
        return None
    resp = info.context["response"]
    resp.status_code = 429
    resp.headers["Retry-After"] = str(max(1, round(wait)))
    return UserError(code=UserErrorCode.RATE_LIMITED, message=f"Demasiados intentos. Reintenta en {max(1, round(wait))} s.")


def _to_user(u: dict) -> User:
    return User(id=str(u["id"]), email=u["email"], role=Role(u["role"]), created_at=u["created_at"])


def _rotate_session(info: Info, user_id) -> None:
    """Login: the pre-login session id is destroyed and a new one issued (anti session fixation)."""
    info.context["request"].state.rotate_to_user = user_id


# ───────────────────────── roots ─────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    def me(self, info: Info) -> Optional[User]:
        u = _user(info)
        return _to_user(u) if u else None

    @strawberry.field
    def cities(self) -> list[City]:
        return [City(code=c, name=n) for c, n in CITIES.items()]

    @strawberry.field
    async def package_availability(self, info: Info, input: PackageSearchInput) -> PackageAvailability:
        if not (IATA.match(input.origin) and IATA.match(input.destination)) or input.origin == input.destination:
            raise ValueError("origin/destination must be two different IATA codes")
        nights = (input.return_date - input.depart_date).days
        if not 1 <= nights <= MAX_STAY_NIGHTS:
            raise ValueError(f"returnDate must be 1–{MAX_STAY_NIGHTS} days after departDate")

        sel = _selections(info.selected_fields[0].selections)
        filters = catalog.search_filters(input.origin, input.destination, input.depart_date, input.return_date)
        parts = []
        for kind in TYPE_OF:
            if kind in sel:
                args = sel[kind].arguments
                fields = set(_selections(sel[kind].selections))
                limit = max(1, min(int(args.get("limit", 10)), 50))
                parts.append(catalog.collection(kind, kind, fields, filters[kind], limit,
                                                descending=str(args.get("sort", "")).endswith("PRICE_DESC")))
        if "cheapestPackage" in sel:
            sub = _selections(sel["cheapestPackage"].selections)
            for kind, single in (("flights", "flight"), ("hotels", "hotel"), ("cars", "car")):
                fields = set(_selections(sub[single].selections)) if single in sub else set()
                fields.add(catalog.KINDS[kind][1])  # price is needed for totalCop
                parts.append(catalog.collection(f"cheapest_{kind}", kind, fields, filters[kind], 1))

        data = await catalog.resolve(info.context["pool"], "{ " + " ".join(parts) + " }") if parts else {}
        rows = {kind: [_from_node(cls, n) for n in catalog.nodes(data, kind)] for kind, cls in TYPE_OF.items()}
        cheapest = [catalog.nodes(data, f"cheapest_{k}") for k in TYPE_OF]
        if all(cheapest):
            f, h, c = (_from_node(cls, n[0]) for cls, n in zip(TYPE_OF.values(), cheapest))
            rows["cheapest"] = Package(flight=f, hotel=h, car=c,
                                       total_cop=f.price_cop + h.price_total_cop + c.price_total_cop)
        return PackageAvailability(_rows=rows)

    @strawberry.field(description="Own order only (admins: any).")
    async def order(self, info: Info, id: strawberry.ID) -> Optional[Order]:
        user = _user(info)
        if not user:
            return None
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORDERS_URL}/orders/{id}")
        if resp.status_code != 200:
            return None
        o = resp.json()
        if o["user_id"] != str(user["id"]) and user["role"] != "ADMIN":
            return None  # same answer as "doesn't exist": no order-id probing (FR-39)
        return to_order(o)

    @strawberry.field
    async def my_orders(self, info: Info, first: Optional[int] = 20) -> list[Order]:
        user = _user(info)
        if not user:
            return []
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORDERS_URL}/orders", params={"user_id": str(user["id"]), "limit": min(first or 20, 100)})
        return [to_order(o) for o in resp.json()]


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def register(self, info: Info, email: str, password: str) -> AuthPayload:
        if err := _limited(info, "register_ip", _ip(info)):
            return AuthPayload(user=None, user_errors=[err])
        email = email.strip().lower()
        if not EMAIL.match(email):
            return AuthPayload(user=None, user_errors=[UserError(code=UserErrorCode.VALIDATION_ERROR,
                                                                 message="Correo inválido.", field="email")])
        if not 10 <= len(password) <= 128:
            return AuthPayload(user=None, user_errors=[UserError(code=UserErrorCode.VALIDATION_ERROR,
                                                                 message="La contraseña debe tener entre 10 y 128 caracteres.", field="password")])
        pw_hash = await security.hash_password(password)
        async with info.context["pool"].connection() as conn:
            cur = await conn.execute(
                "insert into accounts.users (email, password_hash) values (%s, %s) on conflict (email) do nothing "
                "returning id, email, role, created_at", (email, pw_hash))
            row = await cur.fetchone()
        if not row:  # generic: doesn't reveal that the email exists (FR-21)
            return AuthPayload(user=None, user_errors=[UserError(code=UserErrorCode.INVALID_REGISTRATION,
                                                                 message="No fue posible registrar la cuenta.")])
        user = {"id": row[0], "email": row[1], "role": row[2], "created_at": row[3]}
        _rotate_session(info, user["id"])  # registering also signs in, with a fresh session id
        return AuthPayload(user=_to_user(user), user_errors=[])

    @strawberry.mutation(description="Rotates the session id (session fixation mitigation).")
    async def login(self, info: Info, email: str, password: str) -> AuthPayload:
        email = email.strip().lower()
        if err := (_limited(info, "login_ip", _ip(info)) or _limited(info, "login_email", email)):
            return AuthPayload(user=None, user_errors=[err])
        async with info.context["pool"].connection() as conn:
            cur = await conn.execute(
                "select id, email, role, created_at, password_hash from accounts.users where email = %s", (email,))
            row = await cur.fetchone()
        if not await security.verify_password(row[4] if row else None, password):
            return AuthPayload(user=None, user_errors=[UserError(code=UserErrorCode.INVALID_CREDENTIALS,
                                                                 message="Correo o contraseña incorrectos.")])
        _rotate_session(info, row[0])
        return AuthPayload(user=_to_user({"id": row[0], "email": row[1], "role": row[2], "created_at": row[3]}),
                           user_errors=[])

    @strawberry.mutation
    async def logout(self, info: Info) -> bool:
        info.context["request"].state.logout = True
        return True

    @strawberry.mutation
    async def book_package(self, info: Info, input: BookPackageInput) -> BookPackagePayload:
        user = _user(info)
        if not user:
            return BookPackagePayload(order=None, user_errors=[UserError(code=UserErrorCode.UNAUTHENTICATED,
                                                                         message="Inicia sesión para reservar.")])
        if err := _limited(info, "book_user", str(user["id"])):
            return BookPackagePayload(order=None, user_errors=[err])
        body = {"idempotency_key": str(input.idempotency_key), "user_id": str(user["id"]),
                "flight_offer_id": int(input.flight_offer_id), "hotel_offer_id": int(input.hotel_offer_id),
                "car_offer_id": int(input.car_offer_id)}
        if input.chaos and user["role"] == "ADMIN":  # chaos is admin-only (Q-27); silently ignored otherwise
            body["chaos"] = {"failAt": input.chaos.fail_at.value, "mode": (input.chaos.mode or FailMode.REJECT).value,
                             "flakyCompensation": bool(input.chaos.flaky_compensation)}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ORDERS_URL}/orders", json=body)
        if resp.status_code in (404, 409, 422):
            detail = str(resp.json().get("detail"))
            code = UserErrorCode.OFFER_NOT_FOUND if resp.status_code == 404 else UserErrorCode.OFFER_UNAVAILABLE
            if resp.status_code == 422:
                code = UserErrorCode.VALIDATION_ERROR
            return BookPackagePayload(order=None, user_errors=[UserError(code=code, message=detail)])
        resp.raise_for_status()
        order = resp.json()
        if order["user_id"] != str(user["id"]):  # idempotency key reused by someone else
            return BookPackagePayload(order=None, user_errors=[UserError(code=UserErrorCode.FORBIDDEN,
                                                                         message="Clave de idempotencia inválida.")])
        return BookPackagePayload(order=to_order(order), user_errors=[])

    @strawberry.mutation(description="Admin-only: starts the ingestion deployment now instead of waiting for the schedule.")
    async def trigger_ingestion(self, info: Info) -> IngestionRun:
        user = _user(info)
        if not user or user["role"] != "ADMIN":
            raise PermissionError("FORBIDDEN: admin only")
        if security.hit("ingest_user", str(user["id"])):
            info.context["response"].status_code = 429
            raise PermissionError("RATE_LIMITED")
        async with httpx.AsyncClient(base_url=PREFECT_API, timeout=10) as client:
            dep = (await client.get("/deployments/name/ingest-travel-offers/scheduled")).raise_for_status().json()
            run = (await client.post(f"/deployments/{dep['id']}/create_flow_run", json={})).raise_for_status().json()
        return IngestionRun(id=run["id"], state=run["state"]["name"])

