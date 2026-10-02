import re
from collections import Counter

from app.schemas import Message

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
# 13-19 digits, optionally separated by single spaces or dashes
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
# Loose candidate; digit count is checked in code
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ().-]{8,}\d(?!\w)")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_card(value: str) -> bool:
    digits = _digits(value)
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


def _is_phone(value: str) -> bool:
    return 10 <= len(_digits(value)) <= 15


def redact_text(text: str) -> tuple[str, Counter]:
    counts: Counter = Counter()

    def replacer(label: str, check=None):
        def repl(match: re.Match) -> str:
            if check is not None and not check(match.group(0)):
                return match.group(0)
            counts[label] += 1
            return f"[{label}]"

        return repl

    # Order matters: more specific patterns first
    text = EMAIL_RE.sub(replacer("EMAIL"), text)
    text = CARD_RE.sub(replacer("CARD_NUMBER", _is_card), text)
    text = SSN_RE.sub(replacer("SSN"), text)
    text = PHONE_RE.sub(replacer("PHONE", _is_phone), text)
    return text, counts


def redact_messages(messages: list[Message]) -> tuple[list[Message], Counter]:
    total: Counter = Counter()
    cleaned = []
    for message in messages:
        text, counts = redact_text(message.content)
        total.update(counts)
        cleaned.append(message.model_copy(update={"content": text}))
    return cleaned, total
