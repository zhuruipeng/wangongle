from typing import Any

import redis

from ..settings import RedisSettings

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
""".strip()


def create_redis_client(settings: RedisSettings) -> redis.Redis:
    return redis.Redis.from_url(settings.url, decode_responses=True)


def check_rate_limit(client: Any, key: str, limit: int, window_seconds: int) -> bool:
    count = int(client.eval(RATE_LIMIT_SCRIPT, 1, key, window_seconds))
    return count <= limit
