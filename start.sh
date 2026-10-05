#!/usr/bin/env bash
set -e

pids=()

echo "Starting NIFTY Algo Backend..."

python data_worker.py &
pids+=("$!")

python market_structure.py &
pids+=("$!")

python indicator_calc.py &
pids+=("$!")

python paper_engine.py &
pids+=("$!")

echo "Backend processors started."

python api_server.py &
api_pid=$!

cleanup() {
  echo "Stopping NIFTY Algo Backend..."
  kill "$api_pid" "${pids[@]}" 2>/dev/null || true
  wait "$api_pid" "${pids[@]}" 2>/dev/null || true
}

trap cleanup SIGTERM SIGINT EXIT

wait "$api_pid"
