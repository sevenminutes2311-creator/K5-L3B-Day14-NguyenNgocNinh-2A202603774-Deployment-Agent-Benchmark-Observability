"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Client được tạo lúc import nhưng KHÔNG ping → app vẫn khởi động khi Redis chưa sẵn sàng.
  • redis_healthy() dùng cho GET /ready: không kết nối được → False.
"""
import redis

from app.config import settings

_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
)


def get_client() -> redis.Redis:
    return _client


def redis_healthy() -> bool:
    try:
        return bool(_client.ping())
    except Exception:
        return False
