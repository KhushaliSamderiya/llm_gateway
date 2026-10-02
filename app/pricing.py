from decimal import Decimal

# USD per 1 million tokens: (input, output).
# Verify against the provider's pricing page; these change.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
    "mock": (Decimal("0"), Decimal("0")),
}


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    price_in, price_out = PRICES.get(model, (Decimal("0"), Decimal("0")))
    cost = (price_in * prompt_tokens + price_out * completion_tokens) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))  # matches Numeric(12, 6)
