# DEPLOYMENT — Part 6 agent trên Render

## URL public

- Base URL: `https://ai-agent-o7ta.onrender.com`
- Nền tảng: Render, Blueprint từ `06-lab-complete/render.yaml` (nhánh `lab/cp5`)
- Gói: web service `ai-agent` plan `free`, Redis `agent-redis` plan `free`

## Biến môi trường đã đặt trên Render (giá trị secret không ghi ở đây)

| Biến | Đặt như thế nào |
|---|---|
| `AGENT_API_KEY` | `generateValue: true` — Render tự sinh, lấy từ tab Environment |
| `REDIS_URL` | `fromService` — lấy từ Redis `agent-redis` (connectionString) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |

## Lệnh tự kiểm tra (CP6)

Đặt `BASE` là URL public và `AGENT_API_KEY` là key trên Render:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đo ngày 2026-11-26:

```text
/health                                   200
/ready                                    200
POST /ask không có key                    401
POST /ask với key đúng                    200
POST /ask 10 request liên tiếp (key đúng) 200 ×9, 429 ở request thứ 10 (Retry-After: 56)
```

## Ghi chú

- Lần deploy đầu bị Render yêu cầu thẻ vì thiếu `plan: free` trên web service. Đã sửa trong `render.yaml` (commit `9a97ed3`).
- Railway đã khóa workspace (Suspicious activity), nên không dùng Railway.
- Ảnh chụp dashboard Render được lưu trong `screenshots/` (cần chụp và thêm trước khi nộp).
