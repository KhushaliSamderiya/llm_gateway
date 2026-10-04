from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.errors import GatewayError

STATIC = Path(__file__).parent / "static"
ASSETS = {"dashboard.css": "text/css", "dashboard.js": "text/javascript"}
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}

router = APIRouter(include_in_schema=False)


@router.get("/dashboard")
def dashboard():
    return FileResponse(STATIC / "dashboard.html", media_type="text/html", headers=HEADERS)


@router.get("/dashboard/assets/{name}")
def asset(name: str):
    if name not in ASSETS:  # allowlist: no user-controlled file paths
        raise GatewayError(404, "Not found.", "invalid_request_error", "not_found")
    return FileResponse(STATIC / name, media_type=ASSETS[name], headers=HEADERS)
