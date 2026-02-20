from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncpg
import redis.asyncio as redis
import json
import os
import asyncio

COMPANY_NAME = os.getenv("COMPANY_NAME", "My Company")

app = FastAPI(
    title=f"{COMPANY_NAME} API",
    description=f"API for {COMPANY_NAME}",
    version="1.0.0",
)

# Database connections
db_pool = None
redis_client = None

CACHE_TTL = 60  # seconds


# Models
class UserCreate(BaseModel):
    name: str
    email: str


# Startup/Shutdown
async def _wait_for_postgres(max_attempts=30, delay=1):
    for attempt in range(max_attempts):
        try:
            return await asyncpg.create_pool(
                host=os.getenv("POSTGRES_HOST", "localhost"),
                database=os.getenv("POSTGRES_DB", "mydb"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            )
        except (ConnectionRefusedError, asyncpg.PostgresConnectionError, OSError):
            if attempt == max_attempts - 1:
                raise
            await asyncio.sleep(delay)


@app.on_event("startup")
async def startup():
    global db_pool, redis_client
    db_pool = await _wait_for_postgres()
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True,
    )


@app.on_event("shutdown")
async def shutdown():
    await db_pool.close()
    await redis_client.close()


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
    except Exception:
        raise HTTPException(status_code=503, detail="Database not ready")
    try:
        await redis_client.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis not ready")
    return {"status": "ready"}


# User endpoints
@app.post("/users")
async def create_user(user: UserCreate):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id, name, email",
            user.name,
            user.email,
        )
    # Invalidate the all-users cache since data changed
    await redis_client.delete("users:all")
    return dict(row)


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    cache_key = f"user:{user_id}"

    # Check cache first
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Fallback to DB
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, name, email FROM users WHERE id = $1", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    user = dict(row)
    await redis_client.set(cache_key, json.dumps(user), ex=CACHE_TTL)
    return user


@app.get("/users")
async def list_users():
    cache_key = "users:all"

    # Check cache first
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Fallback to DB
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, email FROM users ORDER BY id")

    users = [dict(row) for row in rows]
    await redis_client.set(cache_key, json.dumps(users), ex=CACHE_TTL)
    return users
