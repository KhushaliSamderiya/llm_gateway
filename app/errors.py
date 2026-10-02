class GatewayError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        code: str,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code
        self.headers = headers or {}
