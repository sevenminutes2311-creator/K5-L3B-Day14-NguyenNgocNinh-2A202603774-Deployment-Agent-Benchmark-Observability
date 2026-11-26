"""Kiểm tra cost_guard_redis.py với Redis thật: chạy `REDIS_URL=redis://localhost:6390/0 python test_cost_guard_redis.py`."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cost_guard_redis as cg

cg._r.flushdb()
nov = datetime(2026, 11, 26, tzinfo=timezone.utc)
dec = datetime(2026, 12, 1, tzinfo=timezone.utc)

# 1) Tiêu dần $3 mỗi lần, budget $10 → lần 4 (tổng 12) bị chặn
for i in range(1, 6):
    ok = cg.check_budget("alice", 3.0, now=nov)
    print(f"alice request {i}: cost $3.00 -> {'ALLOW' if ok else 'BLOCK (402)'}  spent=${cg.get_spent('alice', now=nov):.2f}")

# 2) Vẫn còn $1 → request $1 được qua, $0.01 sau đó bị chặn
print("alice $1.00 ->", cg.check_budget("alice", 1.0, now=nov), " spent =", cg.get_spent("alice", now=nov))
print("alice $0.01 ->", cg.check_budget("alice", 0.01, now=nov))

# 3) User khác có budget riêng
print("bob   $3.00 ->", cg.check_budget("bob", 3.0, now=nov))

# 4) Sang tháng mới → key mới, budget reset
print("alice (2026-12) $3.00 ->", cg.check_budget("alice", 3.0, now=dec), " key:", cg._month_key("alice", dec))
print("TTL of Nov key (s):", cg._r.ttl(cg._month_key("alice", nov)))

# 5) Race condition: 200 request $0.10 cùng lúc (tổng $20) cho user mới, budget $10
with ThreadPoolExecutor(max_workers=50) as ex:
    results = list(ex.map(lambda _: cg.check_budget("carol", 0.10, now=nov), range(200)))
print(f"carol concurrent: allowed={sum(results)} blocked={200 - sum(results)} spent=${cg.get_spent('carol', now=nov):.2f} (must be <= 10.00)")
