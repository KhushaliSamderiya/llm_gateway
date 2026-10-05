# Before the connection-pool fix (2026-10-04)

Setup: 4 uvicorn workers, mock provider delay 800 ms, 50 users, 30 s, uncached traffic.

| Metric | Result |
|---|---|
| Completed requests | 345 |
| Throughput | 11.56 req/s (expected about 60: 50 users / 0.83 s) |
| Latency of completed requests | p50 825 ms, p95 912 ms, p99 924 ms |
| Failures reported by Locust | 0 |
| Postgres connections | 35 `idle in transaction`, 5 idle, 1 active (pool limit 5 + 10 per worker) |
| Server errors | `QueuePool limit of size 5 overflow 10 reached` from auth and from usage logging |

Cause: the auth dependency kept its database session open for the whole request, including
the slow provider call. Requests beyond the pool size queued for a connection. Locust
discarded requests still stuck when the run ended, so latency looked healthy while
throughput collapsed, and usage rows were silently dropped.
