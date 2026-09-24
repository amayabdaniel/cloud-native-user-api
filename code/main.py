#!/usr/bin/env python3
import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager

import asyncpg
import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

COMPANY_NAME = os.getenv("COMPANY_NAME", "My Company")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8001")
VLLM_MODEL = os.getenv("VLLM_MODEL", "HuggingFaceTB/SmolLM2-135M-Instruct")

# Vector 1 (AuthN/AuthZ): API key for PII endpoints. If unset, those endpoints
# refuse to serve — fail-secure. Health and /question stay open.
API_KEY = os.getenv("API_KEY")

# Vector 8 (Infra & config): OpenAPI docs disclose the endpoint shape. Ship
# closed by default; operators opt in with EXPOSE_DOCS=1.
_EXPOSE_DOCS = os.getenv("EXPOSE_DOCS", "0") == "1"

# Vector 3 (Transport & secrets): a "postgres/postgres" default is a working
# insecure default that ships to any deployer who forgets to override. The
# password must be set explicitly at startup, and it must not be a well-known
# weak value.
_WEAK_PASSWORDS = {"", "postgres", "password", "changeme", "change-me", "admin", "root"}

# Vector 4 (Input DoS): explicit bounds on inputs. The old shape relied on
# framework defaults — a bound nobody in the repo chose.
MAX_QUESTION_LEN = 4000        # covers even generous prompts
MAX_USER_NAME_LEN = 200
MAX_USER_EMAIL_LEN = 254       # RFC 5321
MAX_VLLM_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB; a 512-token response is ~4 KB, so 1000x headroom
DEFAULT_USER_PAGE_SIZE = 50
MAX_USER_PAGE_SIZE = 200

# Database connections — assigned inside the lifespan handler, exposed as
# module globals so endpoint handlers can reach them (kept intentionally
# consistent with the pre-migration shape).
db_pool = None
redis_client = None

CACHE_TTL = 60  # seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown replacement for the deprecated @app.on_event handlers.

    Same behavior as before: wait for Postgres, open the Redis client, hand
    control to the app, then close both on exit."""
    global db_pool, redis_client
    db_pool = await _wait_for_postgres()
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True,
    )
    try:
        yield
    finally:
        # Close in reverse order of open. Guard each close so a partial
        # startup (e.g., DB up but Redis constructor raised earlier) still
        # closes what did open.
        if db_pool is not None:
            await db_pool.close()
            db_pool = None
        if redis_client is not None:
            await redis_client.close()
            redis_client = None


app = FastAPI(
    title=f"{COMPANY_NAME} API",
    description="AI-powered question-answering service with user management",
    version="1.0.0",
    docs_url="/docs" if _EXPOSE_DOCS else None,
    redoc_url="/redoc" if _EXPOSE_DOCS else None,
    openapi_url="/openapi.json" if _EXPOSE_DOCS else None,
    lifespan=lifespan,
)


# Models
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_USER_NAME_LEN)
    email: str = Field(min_length=3, max_length=MAX_USER_EMAIL_LEN, pattern=r".+@.+\..+")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LEN)


class AnswerResponse(BaseModel):
    question: str
    answer: str
    model: str


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce API_KEY on protected endpoints.

    Fail-secure: if API_KEY is unset on the server, refuse (503) rather than
    permitting anonymous access. When set, uses hmac.compare_digest for a
    constant-time comparison — the same lesson from services/mcp/src/auth.py
    in the research-radar fleet.

    ORDERING WARNING: /readyz also returns 503 (Database not ready / Redis
    not ready). Both paths distinguish "server misconfigured" from "server
    up but backend down" via HTTP status alone. If a future refactor makes
    the readiness / DB path run BEFORE this auth dependency on the /users*
    endpoints, an unauthenticated caller could distinguish "DB down" from
    "DB up" via the 503 message — a small information leak and a live
    oracle. Keep auth strictly ahead of any DB/Redis touch on protected
    routes."""
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="server missing API_KEY configuration; protected endpoints disabled",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization[7:]
    if not hmac.compare_digest(presented, API_KEY):
        raise HTTPException(status_code=401, detail="invalid bearer token")


# Startup/Shutdown
async def _wait_for_postgres(max_attempts=30, delay=1):
    password = os.getenv("POSTGRES_PASSWORD")
    if password is None or password.lower() in _WEAK_PASSWORDS:
        raise RuntimeError(
            "POSTGRES_PASSWORD must be set to a non-default value at startup"
        )
    for attempt in range(max_attempts):
        try:
            return await asyncpg.create_pool(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                database=os.getenv("POSTGRES_DB", "mydb"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=password,
            )
        except (ConnectionRefusedError, asyncpg.PostgresConnectionError, OSError):
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(delay)


# Root endpoint
@app.get("/")
async def root():
    return {"company": COMPANY_NAME, "status": "running"}


# Health endpoints
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:  # noqa: BLE001 readiness probe: any failure => 503
        raise HTTPException(status_code=503, detail="Database not ready")
    try:
        await redis_client.ping()
    except Exception:  # noqa: BLE001 readiness probe: any failure => 503
        raise HTTPException(status_code=503, detail="Redis not ready")
    return {"status": "ready"}


async def _read_bounded_bytes(response: httpx.Response, cap: int) -> bytes:
    """Stream a response, stopping the moment total bytes exceed the cap.
    Prevents a compromised or misconfigured vLLM upstream from returning a
    gigabyte body that we allocate before checking."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=502,
                detail=f"LLM response exceeded {cap} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# AI Question-Answering endpoint
@app.post("/question", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    try:
        async with (
            httpx.AsyncClient(timeout=60.0) as client,
            client.stream(
                "POST",
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": [{"role": "user", "content": request.question}],
                    "max_tokens": 512,
                    "temperature": 0.7,
                },
            ) as response,
        ):
            response.raise_for_status()
            body = await _read_bounded_bytes(response, MAX_VLLM_RESPONSE_BYTES)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="LLM service unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM service timeout")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502, detail=f"LLM service error: {e.response.status_code}"
        )

    data = json.loads(body)
    answer = data["choices"][0]["message"]["content"]

    return AnswerResponse(
        question=request.question,
        answer=answer,
        model=VLLM_MODEL,
    )


# User endpoints — protected via require_api_key.
@app.post("/users", dependencies=[Depends(require_api_key)])
async def create_user(user: UserCreate):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id, name, email",
            user.name,
            user.email,
        )
    # Invalidate every paginated all-users cache key. `keys` isn't safe on a
    # huge redis, but our cache footprint here is bounded by user-page counts.
    for key in await redis_client.keys("users:list:*"):
        await redis_client.delete(key)
    return dict(row)


@app.get("/users/{user_id}", dependencies=[Depends(require_api_key)])
async def get_user(user_id: int):
    cache_key = f"user:{user_id}"

    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, name, email FROM users WHERE id = $1", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    user = dict(row)
    await redis_client.set(cache_key, json.dumps(user), ex=CACHE_TTL)
    return user


@app.get("/users", dependencies=[Depends(require_api_key)])
async def list_users(
    limit: int = Query(default=DEFAULT_USER_PAGE_SIZE, ge=1, le=MAX_USER_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
):
    """Paginated listing. Vector 6 — the pre-fix endpoint returned every user
    in one response and cached the whole set. A directory with millions of
    users would push megabytes through the API and Redis on every miss."""
    cache_key = f"users:list:{limit}:{offset}"

    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, email FROM users ORDER BY id LIMIT $1 OFFSET $2",
            limit,
            offset,
        )

    users = [dict(row) for row in rows]
    await redis_client.set(cache_key, json.dumps(users), ex=CACHE_TTL)
    return users
