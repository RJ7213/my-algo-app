#!/usr/bin/env bash
set -e

pids=()

python data_worker.py & pids+=("$!")
python market_structure.py & pids+=("$!")
python indicator_calc.py & pids+=("$!")
python paper_engine.py & pids+=("$!")

# Keep the existing Streamlit dashboard running internally during migration.
# Render exposes the API port publicly.
streamlit run "Trading app.py" \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true &
streamlit_pid=$!

# Public read-only API used by the Flutter Android app.
python api_server.py &
api_pid=$!

cleanup() {
  kill "$api_pid" "$streamlit_pid" "${pids[@]}" 2>/dev/null || true
  wait "$api_pid" "$streamlit_pid" "${pids[@]}" 2>/dev/null || true
}

trap cleanup SIGTERM SIGINT EXIT

wait "$api_pid"
