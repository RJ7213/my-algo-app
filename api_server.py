from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import os
from datetime import datetime, timezone, timedelta

app = FastAPI(title="NIFTY Paper Trading API")

# Android/Web access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IST = timezone(timedelta(hours=5, minutes=30))

FILES = {
    "raw": Path("data_raw.json"),
    "indicators": Path("processed_indicators.json"),
    "structure": Path("processed_market_structure.json"),
    "paper": Path("paper_engine_output.json"),
    "history": Path("trade_history.json"),
    "strategy": Path("strategy_config.json"),
}

API_KEY = os.getenv("ANDROID_API_KEY", "")


def check_api_key(x_api_key: str = ""):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )


def load_json(path: Path, default=None):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
            default=str
        )
        f.flush()
        os.fsync(f.fileno())

    tmp.replace(path)


@app.get("/")
def root():
    return {
        "app": "NIFTY Paper Trading API",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "time_ist": datetime.now(IST).isoformat()
    }


# ============================================================
# MARKET
# ============================================================

@app.get("/api/market")
def market(x_api_key: str = Header(default="")):

    check_api_key(x_api_key)

    raw = load_json(FILES["raw"], {})
    indicators = load_json(FILES["indicators"], {})
    structure = load_json(FILES["structure"], {})

    return {
        "server_time_ist": datetime.now(IST).isoformat(),

        "market": raw,
        "indicators": indicators,
        "structure": structure,
    }


# ============================================================
# TRADE
# ============================================================

@app.get("/api/trade")
def trade(x_api_key: str = Header(default="")):

    check_api_key(x_api_key)

    paper = load_json(FILES["paper"], {})

    return {
        "server_time_ist": datetime.now(IST).isoformat(),
        "paper": paper,
    }


# ============================================================
# HISTORY
# ============================================================

@app.get("/api/history")
def history(x_api_key: str = Header(default="")):

    check_api_key(x_api_key)

    history_data = load_json(FILES["history"], {})

    return {
        "server_time_ist": datetime.now(IST).isoformat(),
        "history": history_data,
    }


# ============================================================
# STRATEGY CONFIG
# ============================================================

@app.get("/api/strategy")
def get_strategy(x_api_key: str = Header(default="")):

    check_api_key(x_api_key)

    config = load_json(FILES["strategy"], {})

    return {
        "strategy": config
    }


@app.put("/api/strategy")
def update_strategy(
    config: dict,
    x_api_key: str = Header(default="")
):

    check_api_key(x_api_key)

    if not isinstance(config, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid strategy configuration"
        )

    save_json_atomic(
        FILES["strategy"],
        config
    )

    return {
        "success": True,
        "message": "Strategy configuration updated"
    }


# ============================================================
# DASHBOARD SNAPSHOT
# ============================================================

@app.get("/api/dashboard")
def dashboard(x_api_key: str = Header(default="")):

    check_api_key(x_api_key)

    raw = load_json(FILES["raw"], {})
    indicators = load_json(FILES["indicators"], {})
    structure = load_json(FILES["structure"], {})
    paper = load_json(FILES["paper"], {})
    history = load_json(FILES["history"], {})

    return {
        "server_time_ist": datetime.now(IST).isoformat(),

        "market": raw,
        "indicators": indicators,
        "structure": structure,
        "paper": paper,
        "history": history,
    }
