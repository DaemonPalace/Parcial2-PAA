"""Security by design (docs/design.md §7): Argon2id, rotating server-side sessions, rate limits."""
import asyncio
import hashlib
import secrets
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

COOKIE = "ws_session"
SESSION_TTL_SECONDS = 2 * 3600

# RFC 9106 "low-memory" profile: t=3, m=64 MiB, p=4 (FR-20).
hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
# Verified for unknown emails so a login takes the same time whether or not the account exists.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(hasher.hash, password)  # ~0.1 s CPU: keep it off the event loop


async def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return await asyncio.to_thread(hasher.verify, stored_hash or DUMMY_HASH, password) and stored_hash is not None
    except VerificationError:
        return False


def _digest(token: str) -> str:
    """Only sha256(token) is stored: a DB leak doesn't leak usable session ids."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(pool, user_id=None) -> str:
    token = secrets.token_urlsafe(32)
    async with pool.connection() as conn:
        await conn.execute(
            "insert into accounts.sessions (token_hash, user_id, expires_at) "
            "values (%s, %s, now() + make_interval(secs => %s))",
            (_digest(token), user_id, SESSION_TTL_SECONDS))
    return token


async def load_session(pool, token: str | None) -> dict | None:
    """Unknown or expired ids are never adopted (strict mode): the caller issues a fresh one."""
    if not token:
        return None
    async with pool.connection() as conn:
        cur = await conn.execute(
            """select s.token_hash, u.id, u.email, u.role, u.created_at
               from accounts.sessions s left join accounts.users u on u.id = s.user_id
               where s.token_hash = %s and s.expires_at > now()""", (_digest(token),))
        row = await cur.fetchone()
    if not row:
        return None
    user = {"id": row[1], "email": row[2], "role": row[3], "created_at": row[4]} if row[1] else None
    return {"token_hash": row[0], "user": user}


async def destroy_session(pool, token_hash: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("delete from accounts.sessions where token_hash = %s", (token_hash,))


class RateLimiter:
    """Sliding-window counters in memory (D-004, ADR-03).
    ponytail: per-process; resets on restart and isn't shared across replicas — move the
    counters to Postgres/Redis if the gateway is ever scaled out."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float) -> float:
        """Records a hit; returns 0 if allowed, else seconds until the next slot frees up."""
        now = time.monotonic()
        q = self.hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return round(q[0] + window - now, 1) or 0.1
        q.append(now)
        return 0.0


limiter = RateLimiter()

# design §7.3: operation -> (limit, window seconds)
LIMITS = {
    "login_ip": (5, 60),
    "login_email": (10, 900),
    "register_ip": (3, 60),
    "book_user": (5, 60),
    "ingest_user": (2, 60),
    "graphql_ip": (120, 60),
}


def hit(bucket: str, key: str) -> float:
    limit, window = LIMITS[bucket]
    return limiter.check(f"{bucket}:{key}", limit, window)
