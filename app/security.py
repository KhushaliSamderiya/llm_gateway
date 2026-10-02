import hashlib
import secrets

KEY_PREFIX = "gw_"


def generate_api_key() -> str:
    # 32 random bytes -> ~43 URL-safe characters; the prefix makes keys easy to spot
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    # 64 hex characters, which matches the String(64) column
    return hashlib.sha256(raw_key.encode()).hexdigest()
