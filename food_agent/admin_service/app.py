import os
import logging
import hashlib
import secrets
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from ..sdk.users import UserStore
from ..sdk.config import get_app_data_base_dir

# Setup Logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(levelname)s: %(name)s: %(message)s"
)
logger = logging.getLogger("food_agent.admin")

# Configuration
ADMIN_SECRET = os.environ.get("ADMIN_SHARED_SECRET")
DATA_BASE_DIR = get_app_data_base_dir()

if not ADMIN_SECRET:
    logger.critical("ADMIN_SHARED_SECRET is missing.")
    raise RuntimeError("Security Violation: ADMIN_SHARED_SECRET is required.")

if len(ADMIN_SECRET) < 32:
    logger.critical("ADMIN_SHARED_SECRET is too short (< 32 chars).")
    raise RuntimeError("Security Violation: ADMIN_SHARED_SECRET is too weak.")

# Setup
app = FastAPI(title="Food Agent Admin API")
# UserStore now takes the file path
user_store = UserStore(data_dir=DATA_BASE_DIR)

class SecretMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Health check bypass
        if request.url.path == "/health":
            return await call_next(request)
        
        secret_header = request.headers.get("X-Admin-Secret")
        if not secret_header:
            return JSONResponse({"error": "Forbidden: Missing Authentication"}, status_code=403)
            
        if not secrets.compare_digest(secret_header, ADMIN_SECRET):
            return JSONResponse({"error": "Forbidden: Invalid Shared Secret"}, status_code=403)
        
        return await call_next(request)

app.add_middleware(SecretMiddleware)

class UserCreate(BaseModel):
    email: EmailStr
    pat: Optional[str] = None

class UserResponse(BaseModel):
    model_config = {"json_schema_extra": {"exclude_none": True}}
    email: EmailStr
    pat_hash: str
    pat_length: int
    pat: Optional[str] = None

    def model_dump(self, **kwargs):
        kwargs.setdefault('exclude_none', True)
        return super().model_dump(**kwargs)

def mask_user(email: str, pat: str, show_token: bool = False) -> UserResponse:
    return UserResponse(
        email=email,
        pat_hash=hashlib.sha256(pat.encode()).hexdigest()[:12] + "...",
        pat_length=len(pat),
        pat=pat if show_token else None
    )

@app.post("/admin/users", response_model=UserResponse)
async def register_user(
    user: UserCreate,
    show_token: bool = Query(False)
):
    pat = user.pat or secrets.token_urlsafe(32)
    try:
        user_store.add_user(pat=pat, email=user.email)
        return mask_user(user.email, pat, show_token=show_token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/users", response_model=List[UserResponse])
async def list_users(
    email_filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100)
):
    cache = user_store.refresh_cache()
    results = []
    for pat, email in cache.items():
        if email_filter and email_filter not in email:
            continue
        results.append(mask_user(email, pat))
        if len(results) >= limit:
            break
    return results

@app.get("/admin/users/{email}", response_model=UserResponse)
async def get_user(email: str, show_token: bool = Query(False)):
    cache = user_store.refresh_cache()
    for pat, e in cache.items():
        if e == email:
            return mask_user(e, pat, show_token=show_token)
    raise HTTPException(status_code=404, detail="User not found.")

@app.get("/health")
async def health():
    return {"status": "ok"}