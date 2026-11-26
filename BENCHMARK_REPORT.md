# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Ngọc Ninh — MSSV 2A202603774
**Ngày chạy:** 2026-11-26 (CP7, local)
**Môi trường:** Windows 11 + WSL2 Ubuntu 26.04, Python 3.12.16, mock LLM (không cần API key)

Mọi số bên dưới lấy từ file JSON trong `develop/reports/` (đường dẫn ghi cạnh mỗi bảng).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM bình thường có p95 ≈ 220 ms, ngưỡng 500 ms cho dư biên ~2x; đủ chặt để bắt được tail latency khi 10% request chậm |
| Error rate `/ask` | < 2 % | Mock có ~0,3–1,7 % lỗi 503 ở mức tải thường; 2 % là mức chịu được trước khi coi là sự cố |
| Accuracy trên golden dataset | ≥ 80 % (gate), 100 % (mục tiêu v2) | Ngưỡng của quality gate trong `run_eval.py` |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2) — `develop/reports/load_v2_c*.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4,46 | 189,3 | 219,7 | 1700,9 | 0,33 % | ✅ |
| 10 | 38,38 | 188,6 | 219,9 | 1674,3 | 0,67 % | ✅ |
| 50 | 107,99 | 195,9 | 262,6 | 1701,5 | 1,33 % | ✅ |
| 100 | 73,43 | 286,0 | 2052,3 | 2364,5 | 1,67 % | ❌ p95 > 500 ms |

**Nhận xét:** RPS không tăng tuyến tính. Từ concurrency 1 lên 50, RPS tăng gần 24 lần, rồi ở concurrency 100 lại giảm còn 73 và p95 vọt lên 2 giây. Mình chưa kiểm chứng nguyên nhân; giả thuyết là threadpool của FastAPI (mỗi endpoint `def` chạy trong một thread) bị bão hoà khi số request đồng thời vượt số thread. Muốn xác nhận cần đo thêm, ví dụ tăng kích thước threadpool rồi chạy lại.

### 2.2 Tail latency — `develop/reports/load_v2_slow_*.json` (concurrency 20, 300 request)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | RPS | SLO |
|---|---|---|---|---|---|
| 0 | 189,5 | 218,3 | 229,5 | 102,95 | ✅ |
| 0,03 (mặc định) | 244,9 | 225,4 | 1705,2 | 62,71 | ✅ |
| 0,1 | 351,3 | 1686,2 | 1716,9 | 48,39 | ❌ p95 > 500 ms |

**Nhận xét:** p95 và p99 nhạy nhất với request chậm. Ở `MOCK_SLOW_RATE=0,1`, avg chỉ tăng từ 190 lên 351 ms, nhưng p95 tăng gần 8 lần. Vì vậy SLO không nên đặt theo average: avg che giấu việc 1 trong 10 người dùng phải chờ gần 2 giây.

Lưu ý về quá trình đo: lần chạy đầu của sweep này bị lỗi ở bước khởi động lại agent (process cũ vẫn giữ cổng 8002, nên 2 mức 0 và 0,1 thực tế chạy với mặc định 0,03). Mình phát hiện nhờ log báo `address already in use`, đã tắt đúng process và chạy lại toàn bộ 3 mức. Chỉ số trong bảng trên là của lần chạy lại.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4,3 % (1/23) | 91,3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 56,6 | 109,0 | 116,0 |
| Tổng cost (USD) | 0,000397 | 0,000760 | 0,000811 |
| Cost / câu đúng (USD) | 0,00039735 | 0,00003619 | 0,00003526 |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS |

File: `eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` (JWT khác API key) | `token`, `hết hạn`, `chữ ký` | Thêm mục KB với từ khoá `jwt`, nội dung mô tả token có chữ ký và thời hạn |
| `scaling-03` (HPA scale theo gì) | `cpu`, `memory`, `custom metrics` | Thêm mục KB với từ khoá `hpa`, nội dung liệt kê CPU, memory, custom metrics |

Sau khi sửa, eval không có câu nào bị regression (`Câu bị regression: 0`), và quality gate với `--min-accuracy 1.0` trả exit code 0.

**Bài 4 (quality gate chặn merge):** chạy agent v1 so với baseline `eval_v2_fixed.json` cho exit code **1**, accuracy 4,3 %, 22 câu bị regression. Lệnh này dùng được trong CI: một bước GitHub Actions chạy `python eval/run_eval.py ... --baseline ...`, job sẽ đỏ và chặn merge khi exit code khác 0.

**Nhận xét trade-off v1 / v2:** v2 đúng hơn nhiều (4 % → 91 %) nhưng tốn gấp đôi token mỗi câu (56 → 109). Tính trên mỗi câu đúng, v2 rẻ hơn khoảng 11 lần (0,00040 → 0,000036 USD). Latency p95 của v2 cao hơn một chút vì thêm bước retrieval, nhưng ở bản local hai phiên bản đều dưới 250 ms ở mức tải thường.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability`, 2 agent (thí nghiệm) và 3 agent (benchmark scaling). Ảnh nằm trong `screenshots/`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png` (Golden Signals, req/s theo status code)
- [x] Một trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger: `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với 2 alert đang firing: `screenshots/prometheus-alert-firing.png` (`AgentHighErrorRate` và `AgentHighLatencyP95`)

### 4.2 Thí nghiệm "phá hệ thống"

Cấu hình: 2 agent, Locust 30 user (ramp 5/s). Mỗi thí nghiệm đợi alert về trạng thái clear trước khi bắt đầu. Thời gian đo từ lúc đổi cấu hình đến lúc alert chuyển sang `firing`. Dữ liệu: `reports/exp_results.txt`.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | 71 s | Error rate (đỏ), trace lỗi trong Jaeger |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | 131 s | p95/p99 tăng vọt, avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 136 s | Cost burn rate (USD/giờ) |
| D | `docker pause` 1 instance | `AgentInstanceDown` | 45 s | Số instance up giảm |
| E | `AGENT_VERSION=v1` | không có | không alert trong 180 s | Retrieval hit ratio, tokens/s (không có alert hạ tầng) |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**
Lỗi chất lượng (v1 trả lời chung chung) không làm metric hạ tầng đổi, nên các alert latency/error đều xanh. Cần eval định kỳ trên một tập câu hỏi cố định (giống `run_eval.py`) chạy trên cả bản đang deploy, và so sánh accuracy với baseline. Có thể thêm một chỉ số chất lượng như tỉ lệ câu có retrieval hit, và đặt alert khi nó giảm đột ngột.

**Phát hiện về Nginx khi scale:** lần benchmark đầu, sau khi scale từ 3 xuống 1 instance, Nginx vẫn gửi request tới IP của container đã bị xóa, báo `connect() failed (111: Connection refused)`. Cấu hình `resolve` chỉ hỏi lại DNS mỗi 10 giây. Restart Nginx sau mỗi lần đổi số instance đã khắc phục (xem 5).

**Phát hiện về Dockerfile:** `production/Dockerfile` của bài cài packages bằng `pip --user` ở stage builder (vào `/root/.local`), nhưng user `agent` có `HOME=/app` nên Python không tìm thấy `uvicorn` và container restart liên tục. Đã sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local` trước khi chạy stack.

### 4.3 Debug bằng trace

Trace chậm nhất trong Jaeger (`POST /ask`, mock LLM):

- `trace_id`: `a2dbaffff2907f4ba0f55580551ced6c`
- Tổng thời gian: 1,7 s
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (~1,7 s, ~100%)
- `agent.retrieve_context`: 16,8 ms, không đáng kể
- Kết luận: chậm do LLM (mock với `MOCK_SLOW_RATE` 3%), không phải do code retrieval của agent.

Trace lỗi: `1ef2e2a9985523b0c08b345c81d4f7de`, status 503 từ `chat mock-llm-small` (lỗi upstream mô phỏng, `MOCK_ERROR_RATE`).

Dòng log tương ứng có thể tìm bằng `docker compose logs agent | grep <trace_id>`; log JSON của agent có trường `trace_id` (xem `production/app/telemetry.py`).

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_N`. Số liệu từ `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (dòng `POST /ask`).

| Số instance | Request | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|---|
| 1 | 7079 | 59,4 | 190 | 230 | 1700 | 63 (0,89 %) |
| 3 | 7101 | 59,6 | 190 | 230 | 1700 | 66 (0,93 %) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance không cải thiện RPS, p95 hay p99. Tức là nút thắt không nằm ở số agent. Các lỗi 503 (~0,9 %) khớp với `MOCK_ERROR_RATE=0,01` của mock LLM, không phải do quá tải.

Giả thuyết cần kiểm chứng (chưa đo): (1) Locust là một process Python trên một container, có thể đã là giới hạn tạo tải (~60 RPS); (2) mock LLM có latency cố định nên mỗi request chiếm thời gian như nhau, nếu thêm instance mà tải phía client không đổi thì RPS không đổi. Để xác nhận cần xem CPU của container Locust và agent (`docker stats`) khi chạy, hoặc chạy Locust với nhiều worker.

**Lưu ý về thao tác:** lần chạy đầu bị lỗi `Permission denied` khi ghi CSV (thư mục `benchmark-results` thuộc root, Locust chạy user khác). Đã `chmod 777` và chạy lại. Lần chạy đầu tiên sau khi scale cũng có `Connection refused` từ Nginx (xem 4.2), lần chạy lại đã restart Nginx trước khi tải.


---

## 6. Kết luận

1. Trung bình (avg) che giấu tail latency. Ở `MOCK_SLOW_RATE=0,1`, avg tăng 1,8 lần nhưng p95 tăng gần 8 lần.
2. Eval theo keyword cho phép phát hiện regression chất lượng trước khi deploy; quality gate với exit code có thể chặn merge trong CI.
3. Chất lượng tăng thường đi kèm chi phí và latency tăng. Chỉ số "cost / câu đúng" công bằng hơn "cost / câu" khi so sánh hai phiên bản.

Thêm metric cần có khi lên production thật: đo latency ở tầng load balancer (vì lỗi 504 của Nginx không đi qua metric của agent), và một eval chạy định kỳ trên dữ liệu thật để phát hiện chất lượng giảm.
