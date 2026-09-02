#!/usr/bin/env bash
set -e

pids=()

python data_worker.py & pids+=("$!")
python market_structure.py & pids+=("$!")
python indicator_calc.py & pids+=("$!")
python paper_engine.py & pids+=("$!")

streamlit run "Trading app.py" --server.port "${PORT}" --server.address 0.0.0.0 &
streamlit_pid=$!

cleanup() {
  kill "$streamlit_pid" "${pids[@]}" 2>/dev/null || true
  wait "$streamlit_pid" "${pids[@]}" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT EXIT

wait "$streamlit_pid"
