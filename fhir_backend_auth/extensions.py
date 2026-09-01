"""Shared application extensions."""

from redis.asyncio import Redis

redis_client: Redis | None = None


async def init_redis(redis_url: str) -> Redis:
    global redis_client
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    return redis_client


async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None


def get_redis() -> Redis:
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized")
    return redis_client
