"""GraphQL API gateway — the only entry point for the frontend (FR-10).

Exposes POST/GET /graphql (+ /health). Every request gets a server-side session
(anonymous until login); login/register rotate it, logout destroys it.
"""
import logging
import os
from contextlib import asynccontextmanager

import strawberry
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool
from strawberry.extensions import MaxAliasesLimiter
from strawberry.fastapi import GraphQLRouter

import security
from common.web import make_app
from schema import Mutation, Query, make_loaders

log = logging.getLogger("gateway")
pool = AsyncConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=10, open=False)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false") == "true"  # plain-HTTP localhost demo


async def seed_admin() -> None:
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not (email and password):
        return
    pw_hash = await security.hash_password(password)
    async with pool.connection() as conn:
        await conn.execute(
            "insert into accounts.users (email, password_hash, role) values (%s, %s, 'ADMIN') on conflict (email) do nothing",
            (email.lower(), pw_hash))


@asynccontextmanager
async def lifespan(_app):
    await pool.open()
    await seed_admin()
    yield
    await pool.close()


app = make_app("gateway")
app.router.lifespan_context = lifespan

# The schema is acyclic (deepest query: 4 levels) and graphql-core caps introspection nesting, so
# depth can't be abused; alias batching can (N aliased searches = N DB round-trips), so cap it.
schema = strawberry.Schema(query=Query, mutation=Mutation, extensions=[MaxAliasesLimiter(max_alias_count=10)])


async def context(request: Request):
    return {"pool": pool, "loaders": make_loaders(pool)}


app.include_router(GraphQLRouter(schema, context_getter=context), prefix="/graphql")


@app.middleware("http")
async def sessions(request: Request, call_next):
    if not request.url.path.startswith("/graphql"):
        return await call_next(request)

    if wait := security.hit("graphql_ip", request.client.host):  # coarse per-IP ceiling
        return JSONResponse({"errors": [{"message": "RATE_LIMITED"}]}, status_code=429,
                            headers={"Retry-After": str(max(1, round(wait)))})

    token = request.cookies.get(security.COOKIE)
    session = await security.load_session(pool, token)
    new_token = None
    if not session:  # no cookie, expired, or an id we never issued: never adopt it
        new_token = await security.create_session(pool)
        session = await security.load_session(pool, new_token)
    request.state.session = session
    request.state.rotate_to_user = None
    request.state.logout = False

    response = await call_next(request)

    if request.state.rotate_to_user or request.state.logout:
        await security.destroy_session(pool, session["token_hash"])  # old id dies server-side
        new_token = await security.create_session(pool, request.state.rotate_to_user)
    if new_token:
        response.set_cookie(security.COOKIE, new_token, max_age=security.SESSION_TTL_SECONDS,
                            httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                             "Referrer-Policy": "no-referrer"})
    return response


# Added last = outermost: CORS answers preflights before sessions run.
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
