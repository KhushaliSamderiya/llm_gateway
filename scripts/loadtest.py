import os
import random
import uuid
from collections import Counter, defaultdict

from locust import HttpUser, constant, events, task

KEY = os.environ["LOAD_KEY"]
MODE = os.environ.get("MODE", "mixed")  # uncached | cached | mixed
assert MODE in {"uncached", "cached", "mixed"}, "MODE must be uncached, cached, or mixed"

HOT_PROMPTS = [f"hot question number {i}" for i in range(20)]
latencies: dict[str, list[float]] = defaultdict(list)
statuses: Counter = Counter()


def body() -> dict:
    if MODE == "uncached":
        # No temperature: the gateway never caches this, so every call reaches the provider
        return {"model": "mock", "messages": [{"role": "user", "content": "load test"}]}
    if MODE == "cached":
        content = "load test"
    elif random.random() < 0.4:
        content = random.choice(HOT_PROMPTS)
    else:
        content = f"unique {uuid.uuid4().hex}"
    return {
        "model": "mock",
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }


class GatewayUser(HttpUser):
    wait_time = constant(0)  # closed loop: send the next request as soon as one finishes

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {KEY}"

    @task
    def chat(self):
        with self.client.post(
            "/v1/chat/completions",
            json=body(),
            catch_response=True,
            name=f"chat ({MODE})",
        ) as r:
            statuses[r.status_code] += 1
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
                return
            outcome = r.headers.get("x-gateway-cache", "?")
            latencies[outcome].append(r.elapsed.total_seconds() * 1000)


def pct(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(p * len(sorted_values)))]


@events.test_stop.add_listener
def report(environment, **kwargs):
    print("\n--- client-side view, by cache outcome ---")
    print("HTTP statuses:", dict(statuses))
    total = sum(len(v) for v in latencies.values())
    for outcome, values in sorted(latencies.items()):
        values = sorted(values)
        print(
            f"{outcome:7} {len(values):7} requests ({len(values) / total:5.1%})"
            f"   p50 {pct(values, 0.5):7.1f} ms"
            f"   p95 {pct(values, 0.95):7.1f} ms"
            f"   p99 {pct(values, 0.99):7.1f} ms"
        )
