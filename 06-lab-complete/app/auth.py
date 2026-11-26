"""
API Key authentication (tiêu chí 6).

  • Client gửi header  X-API-Key: <key>
  • Key phải trùng biến môi trường AGENT_API_KEY
  • Thiếu hoặc sai key → HTTP 401
"""
import hashlib
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """
    Dependency cho FastAPI: Depends(verify_api_key).
    Trả về user id ẩn danh (hash của key, 16 ký tự) để dùng cho rate limit và budget.
    Không lưu hay log key thật.
    """
    if not settings.agent_api_key or not api_key or \
            not secrets.compare_digest(api_key, settings.agent_api_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]
