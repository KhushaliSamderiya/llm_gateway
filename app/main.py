from fastapi import FastAPI

from app.config import settings  # noqa: F401  (loading it validates the config at startup)

app = FastAPI(title="LLM Gateway")


@app.get("/health")
def health():
    return {"status": "ok"}
