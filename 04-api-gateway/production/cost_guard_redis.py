"""
Exercise 4.4 — Cost guard lưu trong Redis (thay cho bản in-memory trong cost_guard.py).

Yêu cầu:
  - Mỗi user có budget $10/tháng
  - Track spending trong Redis
  - Reset đầu tháng

Khác với lời giải mẫu (GET rồi mới INCRBYFLOAT): hai lệnh rời nhau nên khi nhiều
request / nhiều instance chạy cùng lúc, cả hai cùng đọc "còn budget" rồi cùng cộng
→ vượt budget. Ở đây việc kiểm tra + cộng chạy trong MỘT Lua script, Redis thực thi
nguyên tử, nên không bao giờ cộng quá budget.
"""
import os
from datetime import datetime, timezone

import redis

MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))
KEY_TTL_SECONDS = 32 * 24 * 3600  # > 1 tháng, key tháng cũ tự hết hạn

_r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

# KEYS[1] = budget key, ARGV[1] = cost, ARGV[2] = budget, ARGV[3] = ttl
# Trả về {1, tổng mới} nếu được phép, {0, tổng hiện tại} nếu vượt.
_CHECK_AND_ADD = _r.register_script(
    """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local cost = tonumber(ARGV[1])
    if current + cost > tonumber(ARGV[2]) then
        return {0, tostring(current)}
    end
    local new_total = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
    redis.call('EXPIRE', KEYS[1], ARGV[3])
    return {1, new_total}
    """
)


def _month_key(user_id: str, now: datetime | None = None) -> str:
    # Key theo tháng UTC → sang tháng mới là key mới, coi như reset về 0
    now = now or datetime.now(timezone.utc)
    return f"budget:{user_id}:{now.strftime('%Y-%m')}"


def check_budget(user_id: str, estimated_cost: float, now: datetime | None = None) -> bool:
    """Return True nếu còn budget (và đã ghi nhận chi phí), False nếu vượt."""
    if estimated_cost < 0:
        raise ValueError("estimated_cost must be >= 0")
    allowed, _total = _CHECK_AND_ADD(
        keys=[_month_key(user_id, now)],
        args=[estimated_cost, MONTHLY_BUDGET_USD, KEY_TTL_SECONDS],
    )
    return bool(allowed)


def get_spent(user_id: str, now: datetime | None = None) -> float:
    return float(_r.get(_month_key(user_id, now)) or 0)
