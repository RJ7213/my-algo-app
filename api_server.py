"""
api_server.py
-------------
Read-only HTTP API for the Flutter NIFTY paper-trading dashboard.

IMPORTANT:
- Does NOT calculate strategy signals.
- Does NOT place broker orders.
- Only reads JSON snapshots produced by existing workers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent

FILES = {
    "raw": BASE_DIR / "data_raw.json",
    "indicators": BASE_DIR / "processed_indicators.json",
    "market_structure": BASE_DIR / "processed_market_structure.json",
    "paper": BASE_DIR / "paper_engine_output.json",
}


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def build_dashboard() -> dict:
    raw = load_json(FILES["raw"])
    indicators = load_json(FILES["indicators"])
    structure = load_json(FILES["market_structure"])
    paper = load_json(FILES["paper"])

    if not isinstance(raw, dict):
        raw = {}
    if not isinstance(indicators, dict):
        indicators = {}
    if not isinstance(structure, dict):
        structure = {}
    if not isinstance(paper, dict):
        paper = {}

    return {
        "api_version": 1,
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "raw": raw,
        "indicators": indicators,
        "market_structure": structure,
        "paper": paper,
        "source_files": {
            "raw": FILES["raw"].name,
            "indicators": FILES["indicators"].name,
            "market_structure": FILES["market_structure"].name,
            "paper": FILES["paper"].name,
        },
    }


@app.get("/")
def root():
    return jsonify({
        "service": "NIFTY Paper Trading API",
        "status": "running",
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "endpoints": ["/api/health", "/api/dashboard"],
    })


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "files": {name: path.exists() for name, path in FILES.items()},
    })


@app.get("/api/dashboard")
def dashboard():
    return jsonify(build_dashboard())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
