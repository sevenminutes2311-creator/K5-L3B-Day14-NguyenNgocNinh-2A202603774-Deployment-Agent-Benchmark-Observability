"""
Cost guard (tiêu chí 8): chặn khi vượt budget, cộng dồn chi phí vào Redis.

  • check_budget(user)  — gọi TRƯỚC khi gọi LLM; đã tiêu >= DAILY_BUDGET_USD → HTTP 402
  • record_cost(...)    — gọi SAU khi gọi LLM; cộng chi phí (tính theo token) vào Redis
  • Key theo ngày UTC (budget:<user>:<YYYY-MM-DD>), tự hết hạn sau 2 ngày
"""
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_client

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
KEY_TTL_SECONDS = 2 * 24 * 3600


def _budget_key(user_id: str) -> str:
    return f"budget:{user_id}:{time.strftime('%Y-%m-%d', time.gmtime())}"


def check_budget(user_id: str) -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → HTTP 402."""
    try:
        spent = float(get_client().get(_budget_key(user_id)) or 0)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis)") from exc
    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "used_usd": round(spent, 8),
                "budget_usd": settings.daily_budget_usd,
                "resets_at": "midnight UTC",
            },
        )


def record_cost(user_id: str, input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    key = _budget_key(user_id)
    try:
        pipe = get_client().pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, KEY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis)") from exc
    return cost
