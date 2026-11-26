"""
Production AI Agent — Part 6 Final Project.

Endpoints:
  GET  /health  liveness: 200 khi process còn chạy (kể cả khi Redis chết)
  GET  /ready   readiness: 200 khi Redis sẵn sàng, 503 khi không
  POST /ask     cần X-API-Key (401), rate limit (429), budget (402)

Graceful shutdown: uvicorn nhận SIGTERM → ngừng nhận request mới, xong request đang chạy,
rồi chạy phần shutdown của lifespan và thoát với exit code 0.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.logging_setup import setup_logging
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask

setup_logging()
logger = logging.getLogger("agent")

START_TIME = time.time()
_started = False  # True sau khi lifespan startup xong; False khi bắt đầu shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _started
    logger.info("startup", extra={"fields": {"event": "startup", "env": settings.environment}})
    _started = True
    yield
    # Shutdown: uvicorn đã ngừng nhận request mới và chờ request đang chạy xong trước khi tới đây
    _started = False
    logger.info("shutdown", extra={"fields": {"event": "shutdown"}})


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    logger.info("request", extra={"fields": {
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }})
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Không trả stack trace ra client; chi tiết nằm trong log
    logger.exception("unhandled_error", extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None  # cho phép có thêm, nhưng danh tính thật lấy từ API key


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "version": "1.0.0",
        "environment": settings.environment,
    }


@app.get("/ready")
def ready():
    if not _started or not redis_healthy():
        raise HTTPException(status_code=503, detail="Not ready: Redis unavailable")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, user: str = Depends(verify_api_key)):
    # Hàm sync (def) nên FastAPI chạy trong threadpool, không chặn event loop
    check_rate_limit(user)
    check_budget(user)
    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(user, input_tokens, output_tokens)
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
