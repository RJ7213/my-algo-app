#!/usr/bin/env bash
set -e

pids=()

python data_worker.py &
pids+=("$!")

python market_structure.py &
pids+=("$!")

python indicator_calc.py &
pids+=("$!")

python paper_engine.py &
pids+=("$!")

# Old Streamlit dashboard
streamlit run "Trading app.py" \
    --server.port 8501 \
    --server.address 0.0.0.0 &
streamlit_pid=$!

# Android API
uvicorn api_server:app \
    --host 0.0.0.0 \
    --port "${PORT}" &
api_pid=$!

cleanup() {
    kill "$api_pid" "$streamlit_pid" "${pids[@]}" 2>/dev/null || true

    wait "$api_pid" "$streamlit_pid" "${pids[@]}" 2>/dev/null || true
}

trap cleanup SIGTERM SIGINT EXIT

wait "$api_pid"
