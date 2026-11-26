# Day 14 Lab - Mission Answers

> Môi trường chạy: Windows 11 + WSL2 Ubuntu 26.04, Python 3.12.16 (venv), Docker Desktop 29.9.3.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Đọc `01-localhost-vs-production/develop/app.py`:

1. **Hardcode secret trong code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key và mật khẩu DB; muốn đổi key phải sửa code và deploy lại.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thật, key nằm nguyên trong log (đã thấy trong log server ở Exercise 1.2), ai đọc được log là lấy được key.
3. **Dùng `print()` thay cho logging** (dòng 33, 38): không có level, không có timestamp, không phải JSON, nên log aggregator (Datadog, Loki…) không lọc/tìm được; lại in nguyên câu hỏi và câu trả lời của người dùng.
4. **Config cứng, không đọc từ env** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` cố định, không đổi được giữa dev / staging / production.
5. **Không có health check** (không có `/health`, `/ready`): gọi `GET /health` trả 404. Platform (Railway, Render, Kubernetes) không biết agent còn sống hay đã treo để restart, load balancer không biết lúc nào nên gửi traffic.
6. **Port cố định 8000** (dòng 52): Railway/Render inject `PORT` qua env var, app không đọc nên sẽ không nhận được traffic.
7. **Bind `host="localhost"`** (dòng 51): trong container chỉ nhận kết nối từ chính container, từ bên ngoài (port mapping, load balancer) không gọi vào được. Phải bind `0.0.0.0`.
8. **`reload=True` khi chạy** (dòng 53): bật file watcher + process reloader (log có `Started reloader process ... using WatchFiles`), tốn tài nguyên và không dùng cho production.
9. **Không xử lý shutdown**: không có lifespan / handler SIGTERM, không đóng kết nối hay chờ request đang chạy.
10. **Không validate input**: `question` lấy từ query string, không giới hạn độ dài; gửi JSON body như client thông thường thì nhận 422 (xem 1.2).

### Exercise 1.2: Chạy basic version

Bản develop nhận `question` qua **query string**:

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Gửi JSON body như trong `CODE_LAB.md` thì bị 422, và không có health check:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Log server (trích) — secret bị in thẳng ra log:

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [917] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
```

**Nhận xét:** chạy được, nhưng chưa production-ready: lộ secret trong log, không có health check, chỉ nghe trên `localhost:8000`.

### Exercise 1.3: Comparison table

Bản production (`01-localhost-vs-production/production/`) chạy được:

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.2,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:25:57.500368+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}

# gửi SIGTERM vào process -> uvicorn "Shutting down ... Application shutdown complete", exit code: 0
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hardcode trong code (`OPENAI_API_KEY`, `DEBUG`, `MAX_TOKENS`) | `config.py` đọc env var (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`…), có `.env.example`; `validate()` raise lỗi nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Cùng một image chạy được ở dev/staging/prod chỉ bằng cách đổi env; secret không nằm trong git; thiếu config quan trọng thì fail fast lúc khởi động thay vì lỗi lúc đang phục vụ |
| Secrets | Key + mật khẩu DB trong code, còn in ra log | Lấy từ env, log chỉ ghi `question_length`, không ghi secret hay nội dung câu hỏi | Log thường được nhiều người/hệ thống đọc; lộ key = mất tiền, lộ dữ liệu người dùng |
| Health check | Không có (`/health` → 404) | `/health` (liveness, có uptime/version) và `/ready` (readiness, 503 khi chưa sẵn sàng), thêm `/metrics` | Platform dùng `/health` để restart container treo; load balancer dùng `/ready` để không gửi traffic vào instance đang khởi động/tắt |
| Logging | `print()` text tự do | Logging theo level, mỗi dòng là JSON (`{"time":..,"level":..,"msg":..}`) | Log aggregator parse/lọc/đếm được theo field; có level để tắt DEBUG trên prod |
| Shutdown | Đột ngột, không có hook | `lifespan` đặt `is_ready=False` rồi dọn dẹp; có handler SIGTERM; test thực tế: SIGTERM → exit code 0 | Khi deploy/scale, platform gửi SIGTERM; tắt êm thì request đang chạy vẫn trả xong, không mất dữ liệu, không trả lỗi cho người dùng |
| Host / Port | `localhost:8000` cứng | `HOST` mặc định `0.0.0.0`, `PORT` từ env | Container phải nghe `0.0.0.0` mới nhận được traffic từ ngoài; cloud cấp port động qua `PORT` |
| Reload | `reload=True` luôn bật | Chỉ reload khi `DEBUG=true` | Reloader tốn CPU, có thể restart giữa chừng; chỉ dùng khi dev |
| Input | Query string, không validate | JSON body, thiếu `question` → 422 với thông báo rõ ràng | Client gửi sai nhận lỗi rõ ràng thay vì lỗi khó hiểu hoặc 500 |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi được API từ trình duyệt |

**Điểm mình quan sát thêm khi chạy bản production:**

- Các dòng log JSON của app (`"event": "startup"`, `"agent_request"`…) **không hiện ra** trong output. Lý do: `config.py` gọi `logging.warning(...)` lúc import (dòng 45), trước `logging.basicConfig(...)` trong `app.py`; lúc đó Python tự cấu hình root logger với format mặc định và level `WARNING`, nên `basicConfig` sau đó không có tác dụng (log thực tế in `WARNING:root:OPENAI_API_KEY not set — using mock LLM`, không phải JSON). Sửa bằng `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`. Bài học: structured logging phải được cấu hình sớm nhất và kiểm tra bằng cách nhìn log thật.
- `app.py` không gọi `load_dotenv()`, nên `cp .env.example .env` không thay đổi gì khi chạy `python app.py`; biến môi trường phải được export từ shell hoặc do platform/Docker inject.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` (dòng 8) — bản Python **đầy đủ** dựa trên Debian (có gcc, header, nhiều tool), nên rất nặng. Đây là nguyên nhân chính khiến image develop lớn.
2. **Working directory:** `/app` (dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` sau đó chạy tương đối với `/app`; `app.py` nằm ở `/app/app.py`, mock LLM ở `/app/utils/mock_llm.py`.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer; layer nào thay đổi thì nó và **mọi layer sau** bị build lại. `requirements.txt` hiếm khi đổi, còn `app.py` đổi liên tục. Copy requirements + `pip install` trước thì khi chỉ sửa code, layer `pip install` (53.3 MB, lâu nhất) vẫn dùng cache, rebuild chỉ mất vài giây. Nếu `COPY . .` trước thì mỗi lần sửa một dòng code là cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD ["python", "app.py"]` là lệnh **mặc định**, bị thay thế hoàn toàn nếu truyền lệnh khi chạy (`docker run my-agent:develop bash` sẽ chạy `bash` thay vì app). `ENTRYPOINT` là lệnh **cố định** luôn chạy; tham số của `docker run` (hoặc `CMD`) được nối thêm vào sau nó, muốn đổi phải dùng `--entrypoint`. Hay dùng kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["main:app", "--port", "8000"]`.

### Exercise 2.2: Build và run

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .    # chạy từ gốc repo, 3m20s lần đầu
$ docker run -d --name cp2-dev -p 8000:8000 my-agent:develop

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.3,"container":true}

$ docker logs cp2-dev
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:35716 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK

$ docker exec cp2-dev whoami
root
```

Bản develop nhận `question` qua query string (gửi JSON body sẽ 422). Container chạy bằng **root** — một điểm yếu bảo mật mà bản production đã sửa.

### Exercise 2.3: Multi-stage build và so sánh kích thước

`02-docker/production/Dockerfile`:

- **Stage 1 `builder`** (`python:3.11-slim`): cài `gcc`, `libpq-dev` (build tools), rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này chỉ để **build**, không được deploy.
- **Stage 2 `runtime`** (`python:3.11-slim` mới, sạch): tạo user `appuser`, chỉ `COPY --from=builder /root/.local` (40.8 MB thư viện đã cài) + `main.py` + `utils/mock_llm.py`, `chown`, `USER appuser`, thêm `HEALTHCHECK`, chạy `uvicorn ... --workers 2`.
- **Vì sao nhỏ hơn:** (1) base `slim` thay cho bản full; (2) gcc, header, apt cache, pip cache nằm lại ở stage builder, image cuối không có; (3) chỉ copy đúng file cần chạy. Kèm theo: chạy non-root (`docker run --rm my-agent:advanced whoami` → `appuser`), có healthcheck.

Số đo thực tế (`docker images my-agent`, `docker image inspect --format '{{.Size}}'`):

```text
my-agent:advanced  240MB    (239,815,006 bytes)
my-agent:develop   1.67GB   (1,667,796,384 bytes)
```

- **Develop:** 1,667.8 MB (1.67 GB)
- **Production:** 239.8 MB
- **Chênh lệch:** production nhỏ hơn **85.6%** (≈ 1/7 kích thước develop; tiết kiệm ~1,428 MB)

Phần lớn chênh lệch đến từ base image: layer thư viện của hai bản gần bằng nhau (53.3 MB vs 40.8 MB), phần còn lại của develop là hệ điều hành + toolchain của `python:3.11` full.

### Exercise 2.4: Docker Compose stack

Chạy (cần `touch .env.local` trước, đặt `-p` để không trùng project với Part 5/7):

```text
$ cd 02-docker/production && touch .env.local
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up (health: starting)     8000/tcp
nginx     nginx:alpine            Up                        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up (healthy)              6333-6334/tcp
redis     redis:7-alpine          Up (healthy)              6379/tcp
```

**Sơ đồ kiến trúc:**

```text
                    host :80 / :443
                          │
   Client (curl) ────────►│
                          ▼
              ┌───────────────────────┐
              │  nginx (nginx:alpine) │  reverse proxy + load balancer
              │  rate limit 10r/s,    │  security headers
              │  burst 20 → 429       │
              └───────────┬───────────┘
                          │ http://agent:8000  (upstream agent_backend)
 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─  network "internal" (bridge)
                          ▼
              ┌───────────────────────┐
              │  agent (FastAPI,      │  build từ 02-docker/production/Dockerfile
              │  uvicorn 2 workers)   │  target runtime, port 8000 KHÔNG publish ra host
              └─────┬───────────┬─────┘
   REDIS_URL=       │           │  QDRANT_URL=
   redis://redis:6379/0         │  http://qdrant:6333
                    ▼           ▼
          ┌──────────────┐  ┌──────────────────┐
          │ redis:7      │  │ qdrant v1.9.0    │
          │ cache/session│  │ vector DB (RAG)  │
          │ vol redis_data│ │ vol qdrant_data  │
          └──────────────┘  └──────────────────┘
```

- **Services được start:** 4 — `agent`, `redis`, `qdrant`, `nginx`. Thứ tự do `depends_on`: redis và qdrant phải **healthy** trước thì agent mới start, nginx start sau agent.
- **Giao tiếp:** tất cả nằm trong network bridge `internal`, gọi nhau bằng **tên service** (DNS nội bộ của Docker: `agent:8000`, `redis:6379`, `qdrant:6333`; IP thực tế 172.18.0.2–5). Chỉ nginx publish cổng ra host (80/443); agent, redis, qdrant không truy cập được từ ngoài — `curl http://localhost:8000/health` trả `000` (không kết nối được).
- Lưu ý: `main.py` của bản này nhận `REDIS_URL` / `QDRANT_URL` nhưng chưa dùng tới; hai service đó là khung cho các phần sau.

Test qua Nginx:

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":1.2,"version":"2.0.0","timestamp":"2026-11-26T07:34:59.006818"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Response có header `Server: nginx` và các security header do nginx thêm → request đúng là đi qua proxy.

Thử thêm rate limit của Nginx: bắn 40 request `/ask` song song → **21 × 200, 19 × 429** (khớp cấu hình `rate=10r/s burst=20 nodelay`: 1 + 20 burst được qua, phần còn lại bị chặn ngay tại nginx, không tới agent).

Quan sát log agent: dòng log "JSON" thực ra **không hợp lệ** — `{"msg":"{"event": "request", "q_len": 2}"}` (chuỗi JSON lồng trong format string mà không escape dấu `"`). Ở Part 6 cần log mỗi dòng là một JSON object hợp lệ, nên phải dùng formatter tự `json.dumps` cả bản ghi.

Debug container: `docker compose -p k5-day14-docker logs agent`, `docker exec -it <container> sh`. Dọn stack: `docker compose -p k5-day14-docker down -v`.

## Part 3: Cloud Deployment

Đã deploy agent Part 6 lên Render (Blueprint từ `06-lab-complete/render.yaml`), URL và kết quả kiểm tra ở `DEPLOYMENT.md`. Railway đã thử trước nhưng workspace bị khóa do "Suspicious activity" nên chuyển sang Render.

### Exercise 3.1 / 3.2: Railway và Render

| Mục | `railway.toml` | `render.yaml` |
|---|---|---|
| Cách build | `builder = "DOCKERFILE"` | `runtime: docker`, `dockerfilePath` + `dockerContext` |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Secret | Đặt bằng `railway variables set`, không nằm trong file | `generateValue: true` cho `AGENT_API_KEY`, Render tự sinh |
| Redis | Phải tạo thủ công trên Railway, rồi đặt `REDIS_URL` | Khai báo trong cùng file (`type: redis`), `REDIS_URL` lấy bằng `fromService` |
| Gói miễn phí | Không khai báo trong file | `plan: free` phải ghi rõ, nếu không Render mặc định gói trả phí và đòi thẻ |
| Thư mục chứa app | Đường dẫn mặc định ở gốc repo | Phải chỉ `dockerContext` vì repo chứa agent trong `06-lab-complete/` |

**Khác nhau và vì sao:** `railway.toml` chỉ mô tả build và deploy, còn tài nguyên (Redis, biến môi trường) cấu hình trên dashboard. `render.yaml` là Blueprint khai báo cả web service lẫn Redis trong một file, nên có thể tái tạo toàn bộ hạ tầng từ repo. Lỗi gặp phải: thiếu `plan: free` làm Render đòi thẻ, và thiếu `dockerContext` làm build không tìm thấy Dockerfile.

### Exercise 3.3: Pipeline Cloud Run (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` chạy 4 bước khi push lên `main`: (1) test bằng pytest; (2) build Docker image và gắn tag theo commit SHA cùng `latest`; (3) push image lên registry; (4) deploy lên Cloud Run ở `asia-southeast1` với `min-instances=1` (tránh cold start), `max-instances=10`, và lấy `OPENAI_API_KEY` từ Secret Manager. `service.yaml` là định nghĩa IaC của cùng service: bật `containerConcurrency: 80`, `startupProbe` gọi `/ready` và `livenessProbe` gọi `/health`, secret lấy qua `secretKeyRef`. Bài này không deploy lên GCP nên chỉ mô tả từ file.

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Key được check ở đâu?** Trong dependency `verify_api_key()` (dòng 39–54). `APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) đọc header, rồi endpoint `/ask` gắn `Depends(verify_api_key)` (dòng 70), nên FastAPI chạy hàm kiểm tra **trước** khi vào handler. `/` và `/health` không gắn dependency nên vẫn public (platform cần gọi `/health` không có key).
- **Sai key thì sao?** Thiếu header → **401** `Missing API key`; có header nhưng sai → **403** `Invalid API key.` (dòng 49–53). Request bị chặn, không gọi LLM. Lưu ý: Part 6 yêu cầu **cả thiếu lẫn sai đều trả 401**, nên không thể chép nguyên logic này.
- **Rotate key thế nào?** Key đọc từ env `AGENT_API_KEY` (dòng 35), không nằm trong code: đặt giá trị mới trên platform rồi restart/redeploy, không phải sửa code. Muốn rotate không downtime thì cho phép **2 key cùng lúc** (vd `AGENT_API_KEYS=old,new`), báo client chuyển sang key mới, rồi gỡ key cũ. Điểm yếu cần sửa: nếu quên đặt env thì app dùng mặc định `demo-key-change-in-production` (dòng 35), và dòng 91 in key ra console khi khởi động.

Test (chạy `AGENT_API_KEY=secret-key-123 python app.py`):

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

**JWT flow (`auth.py`):**

1. Client gửi `POST /auth/token` với username/password → `authenticate_user()` so với `DEMO_USERS` (sai → 401).
2. `create_token()` tạo payload `{sub, role, iat, exp=+60 phút}` và **ký** bằng HMAC-SHA256 với `JWT_SECRET` (dòng 35–43).
3. Client gửi kèm mỗi request: `Authorization: Bearer <token>`.
4. `verify_token()` (dòng 46–67) kiểm tra chữ ký + hạn: thiếu token → 401, hết hạn → 401, chữ ký/định dạng sai → 403. Hợp lệ thì trả `{username, role}` cho handler — **không cần tra DB** mỗi request (stateless, scale nhiều instance dễ).

Payload JWT chỉ được **ký**, không mã hoá: ai cầm token cũng đọc được nội dung (mình decode base64 phần giữa ra `{'sub': 'student', 'role': 'user', 'iat': 1795678625, 'exp': 1795682225}`), nhưng không sửa được `role` thành `admin` vì sẽ sai chữ ký. Vì vậy không bỏ dữ liệu nhạy cảm vào payload, và `JWT_SECRET` phải đặt bằng env (mặc định trong code `super-secret-change-in-production-please` chỉ để demo).

Test (token đã che):

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -s -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"<TOKEN_REDACTED>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED>..."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer invalid.token.here" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block

{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]}
```

Phân quyền theo role: token `student` gọi `/admin/stats` → **403**; token `teacher` (role `admin`) → 200.

**Bug mình phát hiện:** response `/ask` trả `"budget_remaining_usd": 1.9e-05`, nhưng `/me/usage` cùng lúc đó trả `"budget_remaining_usd": 0.999802`. Nguyên nhân: `app.py` dòng 160 gán `usage.total_cost_usd` (số **đã tiêu**) vào field tên "remaining". Đúng phải là `cost_guard.daily_budget_usd - usage.total_cost_usd`.

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Algorithm:** **Sliding window log** (file gọi là "sliding window counter"): mỗi user có một `deque` lưu timestamp các request; mỗi lần check thì bỏ timestamp cũ hơn 60 s (dòng 39–40), nếu còn ≥ `max_requests` thì từ chối. Không phải token bucket. Ưu điểm: chính xác, không bị "dồn 2× limit ở ranh giới phút" như fixed window; nhược điểm: tốn bộ nhớ O(số request trong window) mỗi user.
- **Limit:** user thường `10 req/60 s` (`rate_limiter_user`, dòng 86); admin `100 req/60 s` (`rate_limiter_admin`, dòng 87).
- **Bypass cho admin:** `app.py` dòng 141 chọn limiter theo `role` trong JWT — `admin` dùng limiter 100/phút. Đây là nâng hạn mức chứ không bỏ hẳn; muốn bỏ hẳn thì `if role == "admin": skip check` (nhưng vẫn nên có giới hạn để chống token admin bị lộ). Role lấy từ JWT đã ký nên user không tự nâng quyền được.
- **Khi vượt:** trả **429** kèm `Retry-After` và `X-RateLimit-*` (dòng 48–62).

Vòng lặp 20 lần với token `student` (token này đã dùng 1 request ở 4.2, nên còn 9):

```text
Test  1 -> {"question":"Test 1",...,"usage":{"requests_remaining":8,...}}   [HTTP 200]
...
Test  8 -> {"question":"Test 8",...,"usage":{"requests_remaining":1,...}}   [HTTP 200]
Test  9 -> {"question":"Test 9",...,"usage":{"requests_remaining":0,...}}   [HTTP 200]
Test 10 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}  [HTTP 429]
...
Test 20 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}  [HTTP 429]

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Test 21"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795678687
retry-after: 59

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Token `teacher` (admin) gọi 15 lần liên tiếp: cả 15 đều `200` (limit 100/phút).

**Hạn chế:** state nằm trong RAM của process → restart là mất, và chạy nhiều worker/instance thì mỗi cái đếm riêng (3 instance = thực tế 30 req/phút). Part 6 yêu cầu lưu trong Redis.

### Exercise 4.4: Cost guard

**Bản có sẵn (`cost_guard.py`):** trước khi gọi LLM, `check_budget()` chặn nếu tổng chi phí hôm nay của user ≥ `$1/ngày` → **402 Payment Required**, hoặc tổng toàn hệ thống ≥ `$10/ngày` → 503; sau khi gọi, `record_usage()` cộng token × giá (GPT-4o-mini: $0.15/1M input, $0.60/1M output); cảnh báo log khi dùng ≥ 80%. Thực tế 10 request của student chỉ tốn `$0.000198` (`/me/usage`), nên với budget $1 phải ~50.000 request mới thấy 402 — rate limit chặn trước rất lâu. Cũng như rate limiter, state trong RAM.

**Bản mình implement — Redis, $10/tháng/user:** [`04-api-gateway/production/cost_guard_redis.py`](04-api-gateway/production/cost_guard_redis.py)

```python
def _month_key(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    return f"budget:{user_id}:{now.strftime('%Y-%m')}"     # key theo tháng → tháng mới = reset

# Lua script: kiểm tra + cộng trong MỘT bước nguyên tử trên Redis
_CHECK_AND_ADD = _r.register_script("""
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    if current + tonumber(ARGV[1]) > tonumber(ARGV[2]) then
        return {0, tostring(current)}                      -- vượt budget: không cộng
    end
    local new_total = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
    redis.call('EXPIRE', KEYS[1], ARGV[3])                 -- 32 ngày, key cũ tự xoá
    return {1, new_total}
""")

def check_budget(user_id: str, estimated_cost: float, now=None) -> bool:
    allowed, _ = _CHECK_AND_ADD(keys=[_month_key(user_id, now)],
                                args=[estimated_cost, MONTHLY_BUDGET_USD, KEY_TTL_SECONDS])
    return bool(allowed)
```

Quyết định thiết kế:

- **Reset đầu tháng** bằng tên key `budget:<user>:<YYYY-MM>` (theo UTC) thay vì job cron xoá dữ liệu: sang tháng mới tự động dùng key mới = 0. `EXPIRE` 32 ngày để key tháng cũ tự dọn.
- **Nguyên tử:** lời giải mẫu `GET` rồi mới `INCRBYFLOAT` là hai lệnh rời nhau — khi nhiều request/instance chạy cùng lúc, có thể cùng đọc "còn tiền" rồi cùng cộng, làm tổng vượt budget. Gói trong Lua script thì Redis chạy cả đoạn như một lệnh, không request nào chen vào giữa.
- **Vượt thì không cộng:** request bị chặn không làm tăng số đã tiêu. Budget đọc từ env `MONTHLY_BUDGET_USD`, Redis từ `REDIS_URL`.
- Trong API: `check_budget()` trả `False` → handler `raise HTTPException(402, ...)`.

Test với Redis thật (`test_cost_guard_redis.py`, container `redis:7-alpine`):

```text
$ REDIS_URL=redis://localhost:6390/0 python test_cost_guard_redis.py
alice request 1: cost $3.00 -> ALLOW  spent=$3.00
alice request 2: cost $3.00 -> ALLOW  spent=$6.00
alice request 3: cost $3.00 -> ALLOW  spent=$9.00
alice request 4: cost $3.00 -> BLOCK (402)  spent=$9.00
alice request 5: cost $3.00 -> BLOCK (402)  spent=$9.00
alice $1.00 -> True  spent = 10.0
alice $0.01 -> False
bob   $3.00 -> True
alice (2026-12) $3.00 -> True  key: budget:alice:2026-12
TTL of Nov key (s): 2764800
carol concurrent: allowed=100 blocked=100 spent=$10.00 (must be <= 10.00)

$ redis-cli --scan --pattern 'budget:*'
budget:alice:2026-11
budget:alice:2026-12
budget:bob:2026-11
budget:carol:2026-11
```

Kết quả: chặn đúng ở ngưỡng $10 (được tiêu vừa đủ $10.00, thêm $0.01 là chặn); mỗi user budget riêng; sang tháng 12 dùng key mới (reset); 200 request $0.10 bắn song song (50 thread) → đúng 100 được qua, tổng $10.00, không vượt.

**Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ **tốc độ** (chống spam/DoS, chia đều tài nguyên — 10 req/phút), cost guard bảo vệ **tiền** (tổng chi phí theo ngày/tháng). Chỉ có rate limit thì một user vẫn có thể gọi đều 10 req/phút × 24h = 14.400 request/ngày, hoặc gửi ít request nhưng prompt rất dài/đắt; chỉ có cost guard thì một client có thể đốt hết budget cả tháng trong vài phút và làm nghẽn service cho người khác.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop/app.py`)

Hai endpoint đã có trong bản develop:

```python
@app.get("/health")              # LIVENESS — process còn sống không?
def health():
    # trả uptime, version, environment + check RAM (psutil): "ok" / "degraded"
    return {"status": overall_status, "uptime_seconds": uptime, ..., "checks": checks}

@app.get("/ready")               # READINESS — có nên nhận traffic không?
def ready():
    if not _is_ready:            # False khi đang khởi động hoặc đang shutdown
        raise HTTPException(status_code=503, detail="Agent not ready. Check back in a few seconds.")
    return {"ready": True, "in_flight_requests": _in_flight_requests}
```

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:44:57.628609+00:00","checks":{"memory":{"status":"ok","used_percent":12.3}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

(`in_flight_requests` = 1 vì middleware đếm luôn chính request `/ready` đang chạy.)

**Liveness (`/health`) khác readiness (`/ready`):**

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | Process còn sống, còn trả lời được không? | Có nên gửi traffic vào instance này không? |
| Khi fail, platform làm gì | **Restart** container | **Ngừng route traffic** vào instance (không restart) |
| Nên kiểm tra | Chỉ bản thân process — **không** phụ thuộc Redis/DB | Các dependency cần để phục vụ: Redis, DB, model đã load |
| Trả 503 khi | Gần như không bao giờ (process treo thì tự timeout) | Đang khởi động, đang shutdown, mất Redis/DB |

Vì sao `/health` không được phụ thuộc Redis: nếu Redis chết mà `/health` trả lỗi, platform sẽ restart **tất cả** agent liên tục — restart không sửa được Redis, chỉ làm sập thêm. Đúng ra `/ready` trả 503 để load balancer tạm ngừng gửi request, còn `/health` vẫn 200 để container không bị giết; Redis hồi phục thì `/ready` tự về 200. Đây chính là yêu cầu của Part 6.

**Phát hiện khi đo:** `/ask` là `async def` nhưng bên trong gọi `ask()` dùng `time.sleep(3)` (đồng bộ) → **chặn event loop**:

```text
$ time curl -X POST "http://localhost:8000/ask?question=Hello"        -> 3.03 s
--- 3 request /ask gửi song song ---
req1 done at 6.10s   req2 done at 9.10s   req3 done at 9.11s          wall time: 9.15 s
--- gọi /health trong lúc một /ask đang chạy ---
health took 2.71s (HTTP 200)
```

3 request song song bị xử lý **tuần tự** (9 s thay vì 3 s), và `/health` phải chờ 2.7 s. Nếu platform đặt timeout liveness ngắn (vd 1–2 s), agent đang bận sẽ bị coi là "chết" và bị restart oan. Sửa: khai báo `def ask_agent(...)` (FastAPI chạy trong threadpool) hoặc `await asyncio.to_thread(ask, question)`, hoặc dùng client LLM async.

### Exercise 5.2: Graceful shutdown

Cơ chế trong bản develop:

1. **Ngừng nhận request mới:** uvicorn bắt SIGTERM, đóng socket listen (`INFO: Shutting down`).
2. **Hoàn thành request đang chạy:** uvicorn chờ các connection đang xử lý xong (tối đa `timeout_graceful_shutdown=30` s).
3. **Đóng kết nối / dọn dẹp:** sau đó chạy phần shutdown của `lifespan`: `_is_ready = False` (để `/ready` trả 503), chờ `_in_flight_requests` về 0 (tối đa 30 s), log `Shutdown complete`. Đây là chỗ đóng Redis/DB connection.
4. **Thoát** với exit code 0.

Handler tự viết `handle_sigterm` (dòng 175–187) chỉ để log; uvicorn ghi đè handler này khi chạy, và gọi lại nó **sau khi** đã shutdown xong (dòng log cuối cùng).

Test — gửi request "Long task" (mock LLM mất 3 s), 0.5 s sau gửi SIGTERM:

```text
server PID=2275
14:45:14.459 sending SIGTERM
14:45:17.136 server exit code: 0
in-flight request result:
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}  [HTTP 200, 3.00s]
new request after shutdown:
  HTTP 000            # không còn ai nghe ở cổng 8000

--- server log ---
INFO:     Shutting down
INFO:     127.0.0.1:36388 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 14:45:17,059 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:45:17,059 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2275]
2026-11-26 14:45:17,060 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết quả:** request đang chạy **vẫn hoàn thành với HTTP 200** dù SIGTERM đến giữa chừng; process chờ xong (~2.7 s sau SIGTERM) rồi mới thoát, **exit code 0**. Nếu tắt đột ngột (SIGKILL / `kill -9`) thì client sẽ nhận lỗi connection reset.

Lưu ý thực tế: trong Docker, `docker stop` gửi SIGTERM rồi chờ 10 s mới SIGKILL; uvicorn phải là **PID 1** (dùng `CMD ["uvicorn", ...]` dạng exec, không bọc qua `sh -c`) thì mới nhận được SIGTERM.

### Exercise 5.3: Stateless design (`05-scaling-reliability/production/app.py`)

Bản production đã refactor: mọi state hội thoại nằm trong Redis, không nằm trong biến Python:

```python
# ❌ Anti-pattern: conversation_history = {}  → mỗi instance một bản riêng, restart là mất

# ✅ State trong Redis, key theo session, có TTL
def save_session(session_id, data, ttl_seconds=3600):
    _redis.setex(f"session:{session_id}", ttl_seconds, json.dumps(data))

def load_session(session_id):
    data = _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}

def append_to_history(session_id, role, content):
    session = load_session(session_id)
    history = session.get("history", [])
    history.append({"role": role, "content": content, "timestamp": ...})
    session["history"] = history[-20:]          # giữ tối đa 20 message
    save_session(session_id, session)
```

- Client giữ `session_id` và gửi lại mỗi lượt; instance nào nhận request cũng `load_session()` từ Redis, nên không cần "sticky session" ở load balancer.
- TTL 1 giờ: session bỏ dở tự hết hạn, Redis không phình mãi.
- Vì sao bắt buộc khi scale: mỗi instance là một process riêng với RAM riêng. Lưu trong dict thì lượt 1 vào instance A, lượt 2 vào instance B → B không thấy lịch sử; instance bị restart/scale down là mất sạch.

Điểm yếu còn lại trong code mẫu:

- `append_to_history` đọc–sửa–ghi cả JSON (GET rồi SETEX): hai request cùng session đến hai instance cùng lúc có thể ghi đè mất message của nhau. Dùng `RPUSH` + `LTRIM` + `EXPIRE` trên một Redis list (nguyên tử) sẽ an toàn hơn.
- Nếu không kết nối được Redis lúc khởi động, app **lặng lẽ chuyển sang dict trong RAM** (`USE_REDIS = False`) — tức là quay lại đúng anti-pattern, và không bao giờ thử kết nối lại. Part 6 không cho phép điều này: mất Redis thì `/ready` phải trả 503.

### Exercise 5.4: Load balancing (`05-scaling-reliability/production/`)

Lệnh chạy: `docker compose -p k5-day14-scaling up -d --build --scale agent=3`, cổng **8080**, endpoint `POST /chat`.

```text
k5-day14-scaling-agent-1   Up (health: starting)
k5-day14-scaling-agent-2   Up (health: starting)
k5-day14-scaling-agent-3   Up (health: starting)
k5-day14-scaling-nginx-1   Up   0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up (healthy)
```

10 request qua Nginx, đọc `served_by` và header `X-Served-By`:

```text
Request 1   served_by=instance-d4332e  X-Served-By=172.18.0.5:8000
Request 2   served_by=instance-3b151c  X-Served-By=172.18.0.4:8000
Request 3   served_by=instance-1cf1c9  X-Served-By=172.18.0.3:8000
Request 4   served_by=instance-d4332e  X-Served-By=172.18.0.5:8000
Request 5   served_by=instance-3b151c  X-Served-By=172.18.0.4:8000
Request 6   served_by=instance-1cf1c9  X-Served-By=172.18.0.3:8000
Request 7   served_by=instance-d4332e  X-Served-By=172.18.0.5:8000
Request 8   served_by=instance-3b151c  X-Served-By=172.18.0.4:8000
Request 9   served_by=instance-1cf1c9  X-Served-By=172.18.0.3:8000
Request 10  served_by=instance-d4332e  X-Served-By=172.18.0.5:8000
```

Cả 10 đều HTTP 200. Nginx xoay vòng (round-robin) đều qua 3 instance (4-3-3). Đếm dòng `POST /chat` trong log của từng container: agent-1: 3, agent-2: 3, agent-3: 4 (con số này gồm cả các request của bước test khác, không chỉ 10 request này).

### Exercise 5.5: Test stateless

**Bước 1: `python test_stateless.py`** (5 câu hỏi trong cùng một session):

```text
Session ID: 219af898-cb70-4b28-9792-457040e3436a
Request 1: [instance-3b151c]   Request 2: [instance-1cf1c9]   Request 3: [instance-d4332e]
Request 4: [instance-3b151c]   Request 5: [instance-1cf1c9]
Instances used: {'instance-3b151c', 'instance-1cf1c9', 'instance-d4332e'}
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

5 request được xử lý bởi 3 instance khác nhau nhưng lịch sử đủ 10 message (5 user + 5 assistant), vì mọi instance đọc cùng một session trong Redis.

**Bước 2: tắt một instance giữa chừng.** Mình chạy `docker kill` lên `agent-1`, rồi gửi tiếp 6 câu vào cùng session:

```text
After kill 6   HTTP 200 turn=7   served_by=instance-3b151c
After kill 7   ERROR timed out
After kill 8   HTTP 200 turn=8   served_by=instance-d4332e
After kill 9   HTTP 200 turn=9   served_by=instance-3b151c
After kill 10  ERROR timed out
After kill 11  HTTP 200 turn=10  served_by=instance-d4332e
history count: 18
redis: session:<SID> ttl = 3600 s
```

- 4/6 request thành công, và session **không mất**: turn tăng liên tục 7 → 8 → 9 → 10, history còn 18 message.
- 2 request (kill 7 và kill 10) bị **timeout** ở phía client (giới hạn 10 s của script mình). Nguyên nhân có thể là Nginx vẫn gửi request tới IP của container vừa bị kill trước khi đánh dấu nó là hỏng, nên phải chờ connect timeout rồi mới thử instance khác. Đây là **giả thuyết chưa kiểm chứng**: mình chưa xem `error.log` của Nginx để xác nhận. Điểm cần ghi nhận là session không bị mất, nhưng vẫn có request lỗi trong lúc chuyển đổi.
- Container `agent-1` ở trạng thái `Exited (137)`. Cấu hình `restart: unless-stopped` sẽ tự khởi động lại nó trong các lần chạy tiếp theo.

**Bước 3: đối chứng khi Redis mất.** Mình dừng Redis rồi khởi động lại agent. Log báo chúng chuyển sang lưu trong RAM:

```text
mem 1  turn=2  served_by=instance-29a4fd  storage=in-memory
mem 2  turn=3  served_by=instance-29a4fd  storage=in-memory
mem 3  turn=4  served_by=instance-29a4fd  storage=in-memory
mem 4  turn=2  served_by=instance-0daae7  storage=in-memory   ← instance khác, không thấy lịch sử
mem 5  turn=5  served_by=instance-29a4fd  storage=in-memory
mem 6  turn=3  served_by=instance-0daae7  storage=in-memory
```

Đây là bằng chứng rõ nhất của anti-pattern: cùng một session, instance khác nhau cho ra số turn khác nhau (`turn=2` ở instance `0daae7` trong khi instance `29a4fd` đã lên tới 5). Mỗi instance giữ một bản lịch sử riêng trong RAM. Trường hợp này **phải** trả 503 ở `/ready` để load balancer ngừng gửi traffic, nhưng bản production hiện tại vẫn trả 200 (xem nhận xét ở Exercise 5.3).

**Dọn dẹp:** `docker compose -p k5-day14-scaling down -v` đã chạy, stack đã tắt.

**Kết luận Part 5:** state nằm trong Redis nên scale ngang chạy đúng (10/10 request thành công, session liên tục qua 3 instance và qua việc tắt một instance). Điểm yếu cần sửa: 2 request timeout khi có instance chết, và bản production vẫn fallback sang RAM khi mất Redis thay vì trả 503.

## Part 6: Final Project — output `check_production_ready.py`

Code nằm trong `06-lab-complete/` (`app/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`).

Các quyết định thiết kế chính:

- **Rate limit (`app/rate_limiter.py`)**: sliding window 60 s trên Redis sorted set, gói trong một Lua script (ZREMRANGEBYSCORE → ZCARD → ZADD) nên nguyên tử giữa các worker/instance. Vượt → 429 + `Retry-After`.
- **Cost guard (`app/cost_guard.py`)**: `check_budget()` trước khi gọi LLM (402), `record_cost()` sau khi gọi (INCRBYFLOAT theo ngày UTC, TTL 2 ngày).
- **Định danh**: user id = hash SHA-256 (16 ký tự) của API key; không lưu hay log key thật.
- **Fail closed**: khi Redis mất, `/ask` trả 503 thay vì bỏ qua rate limit/budget; `/ready` trả 503; `/health` vẫn 200.
- **Log JSON (`app/logging_setup.py`)**: mỗi dòng là một JSON object (`json.dumps`), có middleware log `method/path/status/ms`, không log nội dung câu hỏi.
- **Lỗi không lộ stack trace**: exception handler trả `{"detail": "Internal server error"}`, chi tiết chỉ nằm trong log.
- **Không chặn event loop**: `/ask` là `def` (chạy trong threadpool).
- **Dockerfile**: builder tạo venv, runtime `python:3.11-slim` chạy user `app`, `HEALTHCHECK` gọi `/health`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers 2"]` để uvicorn là PID 1 và nhận SIGTERM.

Kết quả chạy đầy đủ (`python check_production_ready.py`, venv Python 3.12 trên Ubuntu WSL):

```text

🔎 Kiểm tra /root/day14/06-lab-complete
  ⏳ Kiểm tra tĩnh: file, Dockerfile, compose, config, code...
  ⏳ Chuẩn bị Redis cho bài test stateless...
  ⏳ Khởi động agent: uvicorn app.main:app --workers 2 (Redis: container redis:7-alpine tạm thời)
  ⏳ Restart agent để kiểm tra stateless...
  ⏳ Kiểm tra readiness khi Redis mất kết nối...
  ⏳ Kiểm tra cost guard (budget ≈ 0)...
  ⏳ Kiểm tra graceful shutdown (SIGTERM)...
  ⏳ Build Docker image prod-check:d2f53254 (Docker 29.9.3) — lần đầu có thể mất vài phút...

================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 3s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 2

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 12 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.8s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Lưu ý: dòng `EXIT=True` trong log là do lệnh wrapper, không phải exit code thật của script. Kết quả PASS được in bởi chính script; mình chưa xác nhận lại exit code bằng một lần chạy riêng.

_(Deploy lên Railway/Render và `DEPLOYMENT.md` làm ở CP6.)_

---

## AI log

| # | Phần | Hỏi gì | Nhận gì | Tự sửa / tự kiểm tra thế nào |
|---|------|--------|---------|------------------------------|
| 1 | Setup | Nhờ Claude Code (Opus 5.5) cài WSL Ubuntu, bật Docker WSL integration, tạo venv Python 3.12 | Môi trường chạy được, `os.name == posix`, `docker run hello-world` OK | Tự chạy lại `docker run --rm hello-world` và `python -c "import os; print(os.name)"` |
| 2 | Part 1 | Nhờ Claude Code chạy bản develop/production, ghi lại output curl và gợi ý anti-pattern, bảng so sánh | Output curl thật, danh sách anti-pattern kèm số dòng, bảng so sánh, phát hiện log JSON không hiện | _(điền: mình đã tự đọc lại `app.py` hai bản, đối chiếu số dòng, chạy lại lệnh curl …)_ |
| 3 | Part 2 | Nhờ Claude Code build 2 image, chạy container + stack Compose, đo kích thước, gợi ý câu trả lời 2.1 và sơ đồ 2.4 | Output build/curl thật, kích thước 1.67 GB vs 240 MB (−85.6%), sơ đồ, test rate limit Nginx 21×200 / 19×429 | _(điền: tự chạy lại `docker images my-agent`, tự tính lại %, đọc lại Dockerfile …)_ |
| 4 | Part 4 | Nhờ Claude Code chạy test 401/403/200/429, giải thích JWT flow và thuật toán rate limit, viết `cost_guard_redis.py` (Lua script nguyên tử) + script test | Output curl thật (token đã che), phát hiện bug `budget_remaining_usd`, cost guard Redis pass test kể cả 200 request song song | _(điền: tự đọc lại Lua script, tự chạy lại `test_cost_guard_redis.py`, thử đổi `MONTHLY_BUDGET_USD` …)_ |
| 5 | Part 5 | Nhờ AI chạy health/ready, graceful shutdown, stack 3 instance và test stateless | Output thật; nhận xét `/ask` chặn event loop, bản production fallback sang RAM | Đối chiếu kết quả `test_stateless.py` và log container. Giả thuyết về timeout khi kill instance chưa kiểm chứng |
| 6 | Part 6 | Nhờ AI viết `app/` (config, auth, rate limit, cost guard, log JSON), Dockerfile, compose, `render.yaml` | Code và cấu hình; `check_production_ready.py` PASS 12/12 | Chạy static rồi đầy đủ. Sửa `render.yaml`: thêm `plan: free`, `dockerContext`. _(bạn cần tự đọc lại code)_ |
| 7 | CP6 | Nhờ AI kiểm tra deploy Render và viết `DEPLOYMENT.md` | URL và kết quả 4 lệnh curl | Bạn tự chạy 4 lệnh và chụp ảnh. Đổi `AGENT_API_KEY` vì key đã dán vào chat |
| 8 | Part 7 | Nhờ AI chạy load test, eval, quality gate, dựng stack Docker, chụp ảnh và viết `BENCHMARK_REPORT.md` | Số liệu CSV/JSON thật, sửa knowledge base 2 câu, sửa Dockerfile thiếu `PYTHONUSERBASE`, trace/alert | Đối chiếu số trong báo cáo với file JSON/CSV. Phát hiện và ghi lại lỗi sai số lần chạy đầu (process cũ giữ cổng). _(bạn cần tự đọc lại báo cáo và giải thích được các con số)_ |
