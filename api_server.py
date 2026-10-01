from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS
try:
    from persistent_store import status as supabase_status
except Exception:
    supabase_status = lambda: {"enabled": False, "error": "persistent_store unavailable"}


app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "strategy_config.json"

VALID_MODES = {"HARD", "SOFT", "OFF"}
STRATEGIES = {"major_rejection", "pullback", "breakout"}
GATES = {"rsi", "ema", "volume", "runway", "candle_size", "opposite_wick", "oi", "flow"}

DEFAULT_CONFIG = {
    "version": 1,
    "strategies": {
        "major_rejection": {
            "label": "Major Rejection",
            "gates": {g: "HARD" for g in GATES},
            "rsi": {"ce_min": 60.0, "pe_max": 40.0},
            "volume": {"min_ratio": 1.20},
            "runway": {"min_points": 15.0},
            "candle": {"min_range": 12.0, "max_range": 25.0},
            "wick": {"max_body_ratio": 0.05},
            "structure": {"oi_min_change_pct": 5.0, "flow_threshold": 0.15},
        },
        "pullback": {
            "label": "Pullback",
            "gates": {g: "HARD" for g in GATES},
            "pullback": {"ce_rsi_min": 60.0, "pe_rsi_max": 40.0, "ema_tolerance": 15.0},
            "volume": {"min_ratio": 1.20},
            "runway": {"min_points": 15.0},
            "candle": {"min_range": 12.0, "max_range": 25.0},
            "wick": {"max_body_ratio": 0.05},
            "structure": {"oi_min_change_pct": 5.0, "flow_threshold": 0.15},
        },
        "breakout": {
            "label": "Breakout",
            "gates": {g: "HARD" for g in GATES},
            "breakout": {"ce_rsi_min": 60.0, "pe_rsi_max": 40.0},
            "volume": {"min_ratio": 1.20},
            "runway": {"min_points": 15.0},
            "candle": {"min_range": 12.0, "max_range": 25.0},
            "wick": {"max_body_ratio": 0.05},
            "structure": {"oi_min_change_pct": 5.0, "flow_threshold": 0.15},
        },
    },
}


def load_json() -> dict[str, Any]:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else copy.deepcopy(DEFAULT_CONFIG)
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)


def atomic_write(payload: dict[str, Any]) -> None:
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(CONFIG_FILE)


def validate_config(value: Any) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "config must be an object"
    strategies = value.get("strategies")
    if not isinstance(strategies, dict):
        return False, "strategies object is required"
    for name in STRATEGIES:
        s = strategies.get(name)
        if not isinstance(s, dict):
            return False, f"missing strategy: {name}"
        gates = s.get("gates")
        if not isinstance(gates, dict):
            return False, f"missing gates for {name}"
        for gate in GATES:
            mode = str(gates.get(gate, "HARD")).upper()
            if mode not in VALID_MODES:
                return False, f"invalid mode {mode} for {name}.{gate}"
    return True, "ok"


def authorized() -> bool:
    expected = os.environ.get("STRATEGY_API_KEY", "").strip()
    if not expected:
        return True
    supplied = request.headers.get("X-Strategy-Key", "")
    return supplied == expected


@app.get("/api/strategy")
def get_strategy():
    return jsonify(load_json())


@app.put("/api/strategy")
def put_strategy():
    if not authorized():
        return jsonify({"status": "error", "error": "Unauthorized"}), 401

    incoming = request.get_json(silent=True)
    ok, message = validate_config(incoming)
    if not ok:
        return jsonify({"status": "error", "error": message}), 400

    current = load_json()
    incoming = copy.deepcopy(incoming)
    incoming["version"] = max(int(current.get("version", 1)), int(incoming.get("version", 1))) + 1
    atomic_write(incoming)

    return jsonify({
        "status": "ok",
        "saved": True,
        "version": incoming["version"],
        "config": incoming,
    })


def _iso_age_seconds(value):
    if not value:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _load_dashboard_values():
    values = {}
    for name, path in FILES.items():
        value = load_file(path)
        values[name] = value if isinstance(value, dict) else {}
    return values


def _data_health(values):
    raw = values.get("raw") or {}
    ind = values.get("indicators") or {}
    structure = values.get("market_structure") or {}
    paper = values.get("paper") or {}
    chain = raw.get("option_chain") if isinstance(raw.get("option_chain"), dict) else {}
    option_vol = raw.get("option_volume_candles") if isinstance(raw.get("option_volume_candles"), dict) else {}
    future_candles = raw.get("future_candles") if isinstance(raw.get("future_candles"), list) else []
    volume_ratio = ind.get("volume_ratio", ind.get("signal_volume_ratio"))
    return {
        "option_chain_contracts": len(chain),
        "option_chain_available": len(chain) > 0,
        "option_tick_count": int(raw.get("option_tick_count") or 0),
        "option_volume_history_contracts": len(option_vol),
        "option_volume_available": len(option_vol) > 0,
        "future_candles": len(future_candles),
        "future_candles_available": len(future_candles) > 0,
        "volume_source": ind.get("volume_source"),
        "volume_ratio": volume_ratio,
        "volume_data_valid": bool(ind.get("volume_data_valid", volume_ratio is not None)),
        "indicator_age_sec": _iso_age_seconds(ind.get("calculated_at")),
        "structure_age_sec": _iso_age_seconds(structure.get("last_update_ist")),
        "paper_age_sec": _iso_age_seconds(paper.get("last_update")),
        "worker_age_sec": _iso_age_seconds(raw.get("worker_timestamp")),
        "websocket_connected": bool(raw.get("websocket_connected")),
        "market_status": raw.get("market_status"),
    }


@app.get("/api/health")
def health():
    values = _load_dashboard_values()
    return jsonify({
        "status": "ok",
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "strategy_config": CONFIG_FILE.exists(),
        "supabase": supabase_status(),
        "data_health": _data_health(values),
    })


@app.get("/")
def root():
    return jsonify({
        "service": "NIFTY Paper Trading API",
        "status": "running",
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "endpoints": ["/api/health", "/api/dashboard", "/api/strategy"],
    })



FILES = {
    "raw": BASE_DIR / "data_raw.json",
    "indicators": BASE_DIR / "processed_indicators.json",
    "market_structure": BASE_DIR / "processed_market_structure.json",
    "paper": BASE_DIR / "paper_engine_output.json",
}


def load_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@app.get("/api/dashboard")
def dashboard():
    values = _load_dashboard_values()

    return jsonify({
        "api_version": 2,
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "raw": values["raw"],
        "indicators": values["indicators"],
        "market_structure": values["market_structure"],
        "paper": values["paper"],
        "source_files": {k: v.name for k, v in FILES.items()},
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
