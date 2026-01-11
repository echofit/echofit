import os
import logging
import contextlib
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from ..sdk.users import UserStore
from ..mcp.server import mcp
from ..sdk.context import current_user_id
from ..sdk.config import get_app_data_base_dir

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("food_agent.mcp_service")

# Configuration
DATA_BASE_DIR = get_app_data_base_dir()
user_store = UserStore(data_dir=DATA_BASE_DIR)

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Allow health checks bypass
        if request.url.path == "/health":
            return await call_next(request)

        # Extract Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        pat = auth_header.split(" ")[1]
        user_email = user_store.get_user_by_pat(pat)
        
        if not user_email:
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        # Set User Context
        token = current_user_id.set(user_email)
        try:
            return await call_next(request)
        finally:
            current_user_id.reset(token)

# Lifespan to run the session manager (required for FastMCP Streamable HTTP)
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Check if already started (avoid double run in tests)
    if not getattr(mcp.session_manager, "_has_started", False):
        async with mcp.session_manager.run():
            yield
    else:
        yield

# Initialize App
app = FastAPI(
    title="Food Agent MCP Server",
    lifespan=lifespan
)

# Allow all hosts to avoid 421 errors
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(AuthMiddleware)

@app.get("/health")
async def health():
    return {"status": "ok"}

# Get the base MCP ASGI app
# With stateless_http=True and json_response=True, this uses simple POST requests
mcp_app = mcp.streamable_http_app()

# Mount it
app.mount("/", mcp_app)