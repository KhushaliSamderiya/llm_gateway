#!/usr/bin/env bash
# Reproducible load-test matrix. It starts its own gateway for each provider delay,
# creates a throwaway team, saves every result under benchmarks/<timestamp>/, and cleans up.
# Run from the project root with the virtualenv active:  bash scripts/benchmark.sh
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uvicorn > /dev/null && command -v locust > /dev/null \
  || { echo "Activate the virtualenv first: source .venv/bin/activate"; exit 1; }
docker compose exec -T redis redis-cli ping > /dev/null \
  || { echo "Redis is not reachable. Start the databases: docker compose up -d"; exit 1; }
if curl -s -o /dev/null http://127.0.0.1:8000/health; then
  echo "Something is already listening on port 8000. Stop that server first."
  exit 1
fi

OUT="benchmarks/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
ADMIN=$(grep '^ADMIN_API_KEY=' .env | cut -d= -f2)
SERVER_PID=""
TEAM_ID=""
KEY_ID=""
LOAD_KEY=""
DELAY=""

stop_server() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2> /dev/null || true
    wait "$SERVER_PID" 2> /dev/null || true
    SERVER_PID=""
  fi
}

flush_cache() {
  docker compose exec -T redis redis-cli EVAL \
    "for _,k in ipairs(redis.call('keys','cache:${TEAM_ID}:*')) do redis.call('del',k) end return 1" 0 > /dev/null
}

cleanup() {
  stop_server
  if [ -n "$TEAM_ID" ]; then
    docker compose exec -T postgres psql -U gateway -d gateway -q -c \
      "DELETE FROM requests WHERE team_id = $TEAM_ID; DELETE FROM api_keys WHERE team_id = $TEAM_ID; DELETE FROM teams WHERE id = $TEAM_ID;" > /dev/null || true
    docker compose exec -T redis redis-cli DEL "rl:key:$KEY_ID" "spend:team:$TEAM_ID:$(date -u +%Y-%m)" > /dev/null || true
    flush_cache || true
  fi
}
trap cleanup EXIT

start_server() {  # argument: provider delay in ms
  DELAY=$1
  MOCK_DELAY_MS=$DELAY uvicorn app.main:app --port 8000 --workers 4 > "$OUT/server-delay${DELAY}.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null; then return 0; fi
    sleep 0.5
  done
  echo "The server did not start. See $OUT/server-delay${DELAY}.log"
  exit 1
}

create_team() {
  TEAM_ID=$(curl -s -X POST http://127.0.0.1:8000/admin/v1/teams \
    -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
    -d "{\"name\":\"benchmark-$RANDOM\",\"monthly_budget_usd\":\"1000.00\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
  local resp
  resp=$(curl -s -X POST "http://127.0.0.1:8000/admin/v1/teams/$TEAM_ID/keys" \
    -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
    -d '{"label":"benchmark","rate_limit_rpm":100000}')
  LOAD_KEY=$(echo "$resp" | python3 -c "import sys, json; print(json.load(sys.stdin)['api_key'])")
  KEY_ID=$(echo "$resp" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
}

run() {  # arguments: name mode users seconds
  docker compose exec -T redis redis-cli DEL "rl:key:$KEY_ID" > /dev/null
  flush_cache
  echo "== $1  (mode $2, $3 users, $4 s, provider delay ${DELAY} ms)" | tee -a "$OUT/summary.txt"
  LOAD_KEY="$LOAD_KEY" MODE="$2" locust -f scripts/loadtest.py --headless \
    -u "$3" -r 25 -t "${4}s" --stop-timeout 40 --host http://127.0.0.1:8000 \
    --only-summary --csv "$OUT/$1" 2>&1 \
    | tee "$OUT/$1.txt" \
    | grep -E "^Type|Aggregated|HTTP statuses|^(BYPASS|HIT|MISS) " \
    | tee -a "$OUT/summary.txt" || true
  echo | tee -a "$OUT/summary.txt"
}

start_server 0
create_team
echo "Benchmark team $TEAM_ID. Results are saved in $OUT" | tee "$OUT/summary.txt"
echo | tee -a "$OUT/summary.txt"

run overhead-1user uncached 1 10
run uncached-50users uncached 50 30
run cached-50users cached 50 30

stop_server
start_server 800

( sleep 12; docker compose exec -T postgres psql -U gateway -d gateway -t -A -F' ' -c \
    "SELECT coalesce(state,'background'), count(*) FROM pg_stat_activity WHERE datname='gateway' GROUP BY 1 ORDER BY 2 DESC;" \
    > "$OUT/connections-during-uncached-800ms.txt" ) &
SAMPLER=$!
run uncached-50users-800ms uncached 50 30
wait "$SAMPLER" || true

run mixed-50users-800ms mixed 50 30

echo "Done. Results are in $OUT"
