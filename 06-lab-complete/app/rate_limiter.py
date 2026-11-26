"""
Rate limiting (tiêu chí 7): sliding window 60 giây, state trong Redis.

  • Mỗi user tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây
  • Vượt → HTTP 429 kèm Retry-After
  • State trong Redis nên mọi worker/instance dùng chung và còn sau khi restart agent

Thuật toán (một Lua script, Redis chạy nguyên tử):
  ZREMRANGEBYSCORE  bỏ timestamp ngoài cửa sổ
  ZCARD             đếm request còn lại
  ZADD + EXPIRE     ghi request mới nếu chưa vượt
"""
import math
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_client

WINDOW_SECONDS = 60

_SLIDING_WINDOW = get_client().register_script("""
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local oldest_score = now
  if #oldest > 0 then oldest_score = tonumber(oldest[2]) end
  return {0, tostring(oldest_score)}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return {1, tostring(count + 1)}
""")


def check_rate_limit(user_id: str) -> dict:
    """Raise 429 nếu vượt giới hạn, 503 nếu Redis không dùng được. Trả về thông tin còn lại."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    try:
        allowed, value = _SLIDING_WINDOW(
            keys=[f"ratelimit:{user_id}"],
            args=[now, WINDOW_SECONDS, limit, f"{now}:{uuid.uuid4().hex}"],
        )
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis)") from exc

    if int(allowed) == 0:
        retry_after = max(1, math.ceil(float(value) + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": WINDOW_SECONDS,
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    return {"limit": limit, "remaining": max(0, limit - int(value))}
