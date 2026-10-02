from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.chat import router as chat_router
from app.config import settings  # noqa: F401  (loading it validates the config at startup)
from app.errors import GatewayError

app = FastAPI(title="LLM Gateway")
app.include_router(chat_router)


def _error(status_code: int, message: str, error_type: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


@app.exception_handler(GatewayError)
async def gateway_error_handler(request: Request, exc: GatewayError):
    return _error(exc.status_code, exc.message, exc.error_type, exc.code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body")
    return _error(
        400,
        f"Invalid request: {field}: {first['msg']}",
        "invalid_request_error",
        "invalid_request",
    )


@app.get("/health")
def health():
    return {"status": "ok"}
