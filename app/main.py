from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import AuthContext, authenticate
from app.config import settings  # noqa: F401  (loading it validates the config at startup)
from app.errors import GatewayError

app = FastAPI(title="LLM Gateway")


@app.exception_handler(GatewayError)
async def gateway_error_handler(request: Request, exc: GatewayError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "type": exc.error_type,
                "code": exc.code,
            }
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# Temporary endpoint to test auth. We'll remove it once the real endpoint exists.
@app.get("/v1/whoami")
def whoami(auth: AuthContext = Depends(authenticate)):
    return {
        "team": auth.team_name,
        "team_id": auth.team_id,
        "rate_limit_rpm": auth.rate_limit_rpm,
    }
