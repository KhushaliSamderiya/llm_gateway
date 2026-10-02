import httpx

from app.providers.base import Provider, ProviderError, ProviderResult
from app.schemas import ChatRequest

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FINISH_REASONS = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter"}


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    def _build_payload(self, request: ChatRequest) -> dict:
        # OpenAI: system/user/assistant in one list.
        # Gemini: system prompt separate, and the assistant role is called "model".
        system = [{"text": m.content} for m in request.messages if m.role == "system"]
        contents = [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.content}],
            }
            for m in request.messages
            if m.role != "system"
        ]
        payload: dict = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": system}

        config = {}
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_tokens is not None:
            config["maxOutputTokens"] = request.max_tokens
        if config:
            payload["generationConfig"] = config
        return payload

    async def chat(self, request: ChatRequest) -> ProviderResult:
        try:
            resp = await self.client.post(
                URL.format(model=request.model),
                json=self._build_payload(request),
                headers={"x-goog-api-key": self.api_key},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("Gemini request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach Gemini", retryable=True) from exc

        if resp.status_code != 200:
            retryable = resp.status_code == 429 or resp.status_code >= 500
            try:
                detail = resp.json()["error"]["message"]
            except Exception:
                detail = resp.text[:200]
            raise ProviderError(
                f"Gemini returned HTTP {resp.status_code}: {detail}",
                retryable=retryable,
                status_code=resp.status_code,
            )

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError("Gemini returned no answer (possibly blocked)", retryable=False)

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        return ProviderResult(
            content=text,
            model=request.model,
            provider=self.name,
            prompt_tokens=usage.get("promptTokenCount", 0),
            # "Thinking" tokens are billed like output, so we count them as output
            completion_tokens=usage.get("candidatesTokenCount", 0)
            + usage.get("thoughtsTokenCount", 0),
            finish_reason=FINISH_REASONS.get(candidate.get("finishReason", ""), "stop"),
        )
