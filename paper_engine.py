"""
paper_engine.py
===============

NIFTY PAPER-TRADING DECISION + EXECUTION ENGINE

LOCKED ARCHITECTURE
-------------------
data_worker.py
    -> data_raw.json
        raw spot / candles / futures / live option-chain / actual option LTP

indicator_calc.py
    -> processed_indicators.json
        technical calculations ONLY

market_structure.py
    -> processed_market_structure.json
        OI / order-flow / option-structure calculations ONLY

paper_engine.py
    -> ONLY place where strategy decisions and paper execution happen

Trading app.py
    -> READ-ONLY dashboard

NO LIVE ORDERS ARE SENT.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from persistent_store import load_bundle as remote_load_bundle, save_bundle as remote_save_bundle, cached_state as remote_cached_state, enabled as remote_persistence_enabled
except Exception:
    remote_load_bundle = None
    remote_save_bundle = None
    remote_cached_state = lambda: {}
    remote_persistence_enabled = lambda: False


# ============================================================
# CONFIG — STRATEGY RULES LOCKED
# ============================================================

RAW_FILE = Path("data_raw.json")
INDICATOR_FILE = Path("processed_indicators.json")
STRUCTURE_FILE = Path("processed_market_structure.json")

LEDGER_FILE = Path("trade_history.json")
STATE_FILE = Path("paper_engine_state.json")
OUTPUT_FILE = Path("paper_engine_output.json")

STARTING_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE", "10000"))
LOT_SIZE = int(os.getenv("NIFTY_LOT_SIZE", "65"))

# Existing risk model retained from the previous paper engine.
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "15"))

# Actual option LTP must be fresh before entry/exit.
MAX_OPTION_QUOTE_AGE_SEC = float(os.getenv("MAX_OPTION_QUOTE_AGE_SEC", "5"))

# Technical gates.
VOLUME_PASS_RATIO = 1.20
RUNWAY_MIN = 15.0
CANDLE_MIN = 12.0
CANDLE_MAX = 25.0
OPPOSITE_WICK_BODY_MAX = 0.05

# Setup tolerances.
MAJOR_LEVEL_TOLERANCE = 25.0
PULLBACK_EMA_TOLERANCE = 15.0
REJECTION_WICK_MIN_RANGE_FRACTION = 0.50
BREAKOUT_BUFFER = 0.0

# Psychological levels are 100-point levels.
PSY_STEP = 100

# Option contract strikes are 50 points apart.
STRIKE_STEP = 50

# OI/order-flow confirmation.
OI_CONFIRM_MIN_PCT = 5.0
FLOW_CONFIRM_THRESHOLD = 0.15

LOOP_SEC = 0.50


# ============================================================
# LOGGING / TIME
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def now_ist() -> datetime:
    return datetime.now(IST)


def now_iso() -> str:
    return now_ist().isoformat()


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default
    except Exception as exc:
        logging.warning("Could not read %s: %s", path, exc)
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def quote_age_seconds(timestamp: Any) -> float:
    if not timestamp:
        return float("inf")
    try:
        dt = datetime.fromisoformat(str(timestamp))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return max(0.0, (datetime.now(dt.tzinfo) - dt).total_seconds())
    except Exception:
        return float("inf")


def market_open_from_raw(raw: Dict[str, Any]) -> bool:
    return str(raw.get("market_status", "")).upper() == "OPEN"


# ============================================================
# LEDGER
# ============================================================

# Optional external persistence cache.  Supabase is used only when
# SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are configured.
_REMOTE_LEDGER = None
_REMOTE_STATE = None


def default_ledger() -> Dict[str, Any]:
    return {
        "starting_balance": STARTING_BALANCE,
        "wallet_balance": STARTING_BALANCE,
        "trades": [],
        "total_trades": 0,
        "closed_trades": 0,
        "target_hits": 0,
        "sl_hits": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "realized_pnl": 0.0,
        "active_running_pnl": 0.0,
        "last_update": now_iso(),
    }


def recalculate_ledger(ledger: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(ledger.get("trades"), list):
        ledger["trades"] = []

    trades = ledger["trades"]
    closed = [t for t in trades if t.get("status") != "ACTIVE"]

    wins = sum(
        1 for t in closed
        if (safe_float(t.get("pnl_realized"), 0.0) or 0.0) > 0
    )
    losses = sum(
        1 for t in closed
        if (safe_float(t.get("pnl_realized"), 0.0) or 0.0) < 0
    )

    realized = sum(
        safe_float(t.get("pnl_realized"), 0.0) or 0.0
        for t in closed
    )

    active_running = sum(
        safe_float(t.get("running_pnl"), 0.0) or 0.0
        for t in trades
        if t.get("status") == "ACTIVE"
    )

    start = safe_float(
        ledger.get("starting_balance"),
        STARTING_BALANCE,
    ) or STARTING_BALANCE

    # Wallet is changed ONLY when a trade is closed.
    wallet = safe_float(
        ledger.get("wallet_balance"),
        start,
    ) or start

    ledger.update({
        "starting_balance": start,
        "wallet_balance": round(wallet, 2),
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "target_hits": sum(1 for t in trades if t.get("status") == "TARGET_HIT"),
        "sl_hits": sum(1 for t in trades if t.get("status") == "SL_HIT"),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "total_pnl": round(wallet - start, 2),
        "realized_pnl": round(realized, 2),
        "active_running_pnl": round(active_running, 2),
        "last_update": now_iso(),
    })
    return ledger


def load_ledger() -> Dict[str, Any]:
    global _REMOTE_LEDGER, _REMOTE_STATE

    local = load_json(LEDGER_FILE, None)
    remote = None
    if remote_load_bundle is not None and remote_persistence_enabled():
        remote = remote_load_bundle()

    if remote is not None:
        _REMOTE_LEDGER, _REMOTE_STATE = remote
        ledger = _REMOTE_LEDGER
        # Keep a local recovery copy too.
        try:
            atomic_write_json(LEDGER_FILE, ledger)
        except Exception:
            pass
    elif isinstance(local, dict):
        ledger = local
    else:
        ledger = default_ledger()

    defaults = default_ledger()
    for key, value in defaults.items():
        ledger.setdefault(key, value)

    return recalculate_ledger(ledger)


def save_ledger(ledger: Dict[str, Any], force_remote: bool = False) -> Dict[str, Any]:
    ledger = recalculate_ledger(ledger)
    atomic_write_json(LEDGER_FILE, ledger)
    if remote_save_bundle is not None and remote_persistence_enabled():
        remote_save_bundle(ledger, _REMOTE_STATE or {}, force=force_remote)
    return ledger


def find_active_trade(ledger: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next(
        (t for t in ledger.get("trades", []) if t.get("status") == "ACTIVE"),
        None,
    )


def next_trade_id(trades: List[Dict[str, Any]]) -> str:
    highest = 0
    for trade in trades:
        tid = str(trade.get("trade_id", ""))
        if tid.startswith("T"):
            try:
                highest = max(highest, int(tid[1:]))
            except ValueError:
                pass
    return f"T{highest + 1:06d}"


# ============================================================
# CANDLE / LEVEL HELPERS
# ============================================================

def get_completed_candles(ind: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = ind.get("completed_candles")
    return rows if isinstance(rows, list) else []


def candle_fields(candle: Dict[str, Any]) -> Dict[str, float]:
    o = safe_float(candle.get("open"), 0.0) or 0.0
    h = safe_float(candle.get("high"), 0.0) or 0.0
    l = safe_float(candle.get("low"), 0.0) or 0.0
    c = safe_float(candle.get("close"), 0.0) or 0.0

    rng = max(0.0, h - l)
    body = abs(c - o)
    upper = max(0.0, h - max(o, c))
    lower = max(0.0, min(o, c) - l)

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "range": rng,
        "body": body,
        "upper_wick": upper,
        "lower_wick": lower,
    }


def get_level_engine(ind: Dict[str, Any]) -> Dict[str, Any]:
    level_engine = ind.get("level_engine")
    return level_engine if isinstance(level_engine, dict) else {}


def get_levels(ind: Dict[str, Any]) -> List[Dict[str, Any]]:
    levels = get_level_engine(ind).get("levels")
    return levels if isinstance(levels, list) else []


def unique_levels(levels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: Dict[float, Dict[str, Any]] = {}
    for level in levels:
        value = safe_float(level.get("level"))
        if value is None:
            continue
        key = round(value, 2)
        if key not in out:
            out[key] = dict(level)
    return list(out.values())


def nearest_major_below(
    levels: List[Dict[str, Any]],
    price: float,
) -> Optional[Dict[str, Any]]:
    candidates = [
        x for x in unique_levels(levels)
        if (safe_float(x.get("level")) or 0) < price
    ]
    candidates.sort(
        key=lambda x: abs(price - (safe_float(x.get("level")) or price))
    )
    return candidates[0] if candidates else None


def nearest_major_above(
    levels: List[Dict[str, Any]],
    price: float,
) -> Optional[Dict[str, Any]]:
    candidates = [
        x for x in unique_levels(levels)
        if (safe_float(x.get("level")) or 0) > price
    ]
    candidates.sort(
        key=lambda x: abs((safe_float(x.get("level")) or price) - price)
    )
    return candidates[0] if candidates else None


def nearest_major_to_price(
    levels: List[Dict[str, Any]],
    price: float,
    tolerance: float = MAJOR_LEVEL_TOLERANCE,
) -> Optional[Dict[str, Any]]:
    candidates = []
    for level in unique_levels(levels):
        value = safe_float(level.get("level"))
        if value is None:
            continue
        d = abs(price - value)
        if d <= tolerance:
            candidates.append((d, level))
    candidates.sort(key=lambda x: (x[0], -safe_float(x[1].get("strength"), 0.0)))
    return candidates[0][1] if candidates else None


def level_name(level: Optional[Dict[str, Any]]) -> str:
    if not level:
        return ""
    return str(level.get("name") or level.get("source") or "")


# ============================================================
# TECHNICAL SETUP DETECTION
# ============================================================

def detect_major_rejection(
    candle: Dict[str, float],
    levels: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    """
    Major Rejection:
      - completed candle only
      - candle range must later pass 12-25 gate
      - high/low must be near a real major level
      - rejection wick >= 50% of candle range
      - upper rejection => PE
      - lower rejection => CE

    This deliberately uses actual major levels, not EMA as a substitute.
    """
    h = candle["high"]
    l = candle["low"]
    rng = candle["range"]

    if rng <= 0:
        return None, None, "NO_RANGE"

    upper_level = nearest_major_to_price(levels, h)
    lower_level = nearest_major_to_price(levels, l)

    upper_rejection = (
        upper_level is not None
        and candle["upper_wick"] >= rng * REJECTION_WICK_MIN_RANGE_FRACTION
    )

    lower_rejection = (
        lower_level is not None
        and candle["lower_wick"] >= rng * REJECTION_WICK_MIN_RANGE_FRACTION
    )

    if upper_rejection and lower_rejection:
        # Prefer the larger rejection wick.
        if candle["upper_wick"] >= candle["lower_wick"]:
            return (
                "PE",
                upper_level,
                f"Upper rejection at {level_name(upper_level)}",
            )
        return (
            "CE",
            lower_level,
            f"Lower rejection at {level_name(lower_level)}",
        )

    if upper_rejection:
        return (
            "PE",
            upper_level,
            f"Upper rejection at {level_name(upper_level)}",
        )

    if lower_rejection:
        return (
            "CE",
            lower_level,
            f"Lower rejection at {level_name(lower_level)}",
        )

    return None, None, "NO_MAJOR_REJECTION"


def detect_pullback(
    candle: Dict[str, float],
    live_spot: float,
    ema9: Optional[float],
) -> Tuple[Optional[str], str]:
    """
    Pullback:
      - price close/live context near EMA9
      - direction determined by price relative to EMA9
      - EMA gate is strict <= 15 points
      - opposite wick <= 5% body is checked as a final candle gate
    """
    if ema9 is None:
        return None, "EMA9_UNAVAILABLE"

    if abs(live_spot - ema9) > PULLBACK_EMA_TOLERANCE:
        return None, "NOT_NEAR_EMA9"

    if live_spot >= ema9:
        return "CE", "Pullback above EMA9"
    return "PE", "Pullback below EMA9"


def detect_breakout(
    candle: Dict[str, float],
    levels: List[Dict[str, Any]],
    live_spot: float,
    ema9: Optional[float],
    ema20: Optional[float],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    """
    Breakout:
      - MUST break an actual major level.
      - EMA is trend context, NOT the breakout level.
      - bullish breakout = completed candle close above resistance
      - bearish breakout = completed candle close below support
    """
    close = candle["close"]
    high = candle["high"]
    low = candle["low"]

    resistance = nearest_major_above(levels, close)
    support = nearest_major_below(levels, close)

    bullish = False
    bearish = False

    if resistance:
        r = safe_float(resistance.get("level"))
        if r is not None:
            bullish = close > r + BREAKOUT_BUFFER and high >= r

    if support:
        s = safe_float(support.get("level"))
        if s is not None:
            bearish = close < s - BREAKOUT_BUFFER and low <= s

    if bullish and bearish:
        # Extremely unusual candle; reject ambiguous breakout.
        return None, None, "AMBIGUOUS_BREAKOUT"

    if bullish:
        return "CE", resistance, f"Bullish breakout of {level_name(resistance)}"

    if bearish:
        return "PE", support, f"Bearish breakout of {level_name(support)}"

    return None, None, "NO_MAJOR_BREAKOUT"


def opposite_wick_pass(
    candle: Dict[str, float],
    option_type: str,
) -> Tuple[bool, float]:
    body = max(candle["body"], 0.01)

    if option_type == "CE":
        opposite = candle["upper_wick"]
    else:
        opposite = candle["lower_wick"]

    return opposite <= body * OPPOSITE_WICK_BODY_MAX, opposite


# ============================================================
# OI / ORDER-FLOW CONFIRMATION
# ============================================================

def get_structure_context(structure: Dict[str, Any]) -> Dict[str, Any]:
    return structure if isinstance(structure, dict) else {}


def oi_level_confirmation(
    structure: Dict[str, Any],
    option_type: str,
    entry_price: float,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Descriptive market-structure confirmation.

    CE:
      - PE OI below price is supportive context.
      - heavy CE OI above price is opposing resistance.

    PE:
      - CE OI above price is supportive context.
      - heavy PE OI below price is opposing support.

    This does NOT independently generate a trade.
    """
    sr = structure.get("oi_support_resistance") or {}
    supports = sr.get("supports") or []
    resistances = sr.get("resistances") or []

    support = supports[0] if supports else None
    resistance = resistances[0] if resistances else None

    if option_type == "CE":
        if support:
            oi_pct = safe_float(support.get("oi_change_pct"), 0.0) or 0.0
            if oi_pct >= OI_CONFIRM_MIN_PCT:
                return (
                    "SUPPORTIVE",
                    "PE OI support building below price",
                    {"support": support, "resistance": resistance},
                )
            return (
                "NEUTRAL",
                "PE OI support present but not building strongly",
                {"support": support, "resistance": resistance},
            )
        return "NEUTRAL", "No nearby OI support", {"support": None, "resistance": resistance}

    if resistance:
        oi_pct = safe_float(resistance.get("oi_change_pct"), 0.0) or 0.0
        if oi_pct >= OI_CONFIRM_MIN_PCT:
            return (
                "SUPPORTIVE",
                "CE OI resistance building above price",
                {"support": support, "resistance": resistance},
            )
        return (
            "NEUTRAL",
            "CE OI resistance present but not building strongly",
            {"support": support, "resistance": resistance},
        )

    return "NEUTRAL", "No nearby OI resistance", {"support": support, "resistance": None}


def option_flow_confirmation(
    structure: Dict[str, Any],
    option_type: str,
) -> Tuple[str, str]:
    """
    Uses the selected option's own order flow when available.
    A supportive option flow is a confirmation gate, not a signal by itself.
    """
    per_option = structure.get("order_flow", {}).get("per_option") or {}

    # Actual contract is checked later, so this function is intentionally
    # generic and uses chain-side aggregate flow here.
    side = "ce" if option_type == "CE" else "pe"
    side_data = (structure.get("order_flow", {}).get("options") or {}).get(side) or {}

    imbalance = safe_float(side_data.get("imbalance"), 0.0) or 0.0

    if imbalance >= FLOW_CONFIRM_THRESHOLD:
        return "SUPPORTIVE", f"{option_type} side buy-flow biased"
    if imbalance <= -FLOW_CONFIRM_THRESHOLD:
        return "OPPOSING", f"{option_type} side sell-flow biased"

    return "NEUTRAL", f"{option_type} side flow balanced"


def selected_contract_flow(
    structure: Dict[str, Any],
    strike: int,
    option_type: str,
) -> Tuple[str, str, Dict[str, Any]]:
    key = f"{strike}:{option_type}"
    per = structure.get("order_flow", {}).get("per_option") or {}
    item = per.get(key) or {}

    imbalance = safe_float(item.get("imbalance"), 0.0) or 0.0
    state = str(item.get("state") or "NO_DATA")

    if state in ("BUY_BIASED", "BUY_DOMINANT") and imbalance >= FLOW_CONFIRM_THRESHOLD:
        return "SUPPORTIVE", f"{key} order flow {state}", item

    if state in ("SELL_BIASED", "SELL_DOMINANT") and imbalance <= -FLOW_CONFIRM_THRESHOLD:
        return "OPPOSING", f"{key} order flow {state}", item

    if state == "BALANCED":
        return "NEUTRAL", f"{key} order flow balanced", item

    return "NEUTRAL", f"{key} order flow {state}", item


# ============================================================
# OPTION CONTRACT / LTP
# ============================================================

def nearest_strike(spot: float) -> int:
    return int(round(spot / STRIKE_STEP) * STRIKE_STEP)


def get_option_chain(raw: Dict[str, Any]) -> Dict[str, Any]:
    chain = raw.get("option_chain")
    return chain if isinstance(chain, dict) else {}


def get_option_quote(
    raw: Dict[str, Any],
    option_type: str,
    strike: int,
) -> Tuple[Optional[Dict[str, Any]], str]:
    chain = get_option_chain(raw)
    key = f"{strike}:{option_type}"

    item = chain.get(key)
    if not isinstance(item, dict):
        return None, f"Option contract not found: {key}"

    ltp = safe_float(item.get("ltp"))
    if ltp is None or ltp <= 0:
        return None, f"Invalid option LTP for {key}"

    timestamp = item.get("timestamp") or item.get("exchange_timestamp")
    age = quote_age_seconds(timestamp)

    if age > MAX_OPTION_QUOTE_AGE_SEC:
        return None, f"Stale option LTP for {key}: age={age:.1f}s"

    return item, "OK"


def option_contract_metadata(
    quote: Dict[str, Any],
    strike: int,
    option_type: str,
) -> Dict[str, Any]:
    return {
        "option_symbol": quote.get("symbol") or quote.get("tradingsymbol"),
        "option_token": quote.get("token") or quote.get("symboltoken"),
        "option_strike": strike,
        "option_type": option_type,
        "option_expiry": quote.get("expiry"),
        "option_ltp": safe_float(quote.get("ltp"), 0.0),
        "quote_timestamp": quote.get("timestamp"),
        "exchange_timestamp": quote.get("exchange_timestamp"),
    }


# ============================================================
# ENTRY DECISION
# ============================================================

def choose_setup(
    ind: Dict[str, Any],
    structure: Dict[str, Any],
    spot: float,
) -> Dict[str, Any]:
    """
    FINAL STRATEGY DECISION.

    Priority:
      1. Major Rejection
      2. Pullback
      3. Breakout

    All gates are evaluated after the setup is identified.
    """
    completed = get_completed_candles(ind)
    if not completed:
        return {
            "ready": False,
            "reason": "No completed candle",
            "setup": "NONE",
        }

    candle = candle_fields(completed[-1])
    candle_time = str(
        completed[-1].get("date")
        or completed[-1].get("datetime")
        or ""
    )

    ema9 = safe_float(ind.get("ema9"))
    ema20 = safe_float(ind.get("ema20"))
    rsi = safe_float(ind.get("rsi"))

    # The indicator engine publishes live indicators plus closed-candle copies.
    signal_ema9 = safe_float(ind.get("signal_ema9"), ema9)
    signal_ema20 = safe_float(ind.get("signal_ema20"), ema20)
    signal_rsi = safe_float(ind.get("signal_rsi"), rsi)

    if signal_ema9 is None:
        signal_ema9 = ema9
    if signal_ema20 is None:
        signal_ema20 = ema20
    if signal_rsi is None:
        signal_rsi = rsi

    levels = get_levels(ind)

    # -------------------------
    # SETUP DETECTION
    # -------------------------
    option_type, rejection_level, rejection_reason = detect_major_rejection(
        candle, levels
    )

    setup = "NONE"
    setup_level = rejection_level
    setup_reason = rejection_reason

    if option_type:
        setup = "Major Rejection"
    else:
        option_type, pullback_reason = detect_pullback(
            candle,
            spot,
            signal_ema9,
        )
        if option_type:
            setup = "Pullback"
            setup_level = nearest_major_to_price(levels, candle["close"])
            setup_reason = pullback_reason
        else:
            option_type, breakout_level, breakout_reason = detect_breakout(
                candle,
                levels,
                spot,
                signal_ema9,
                signal_ema20,
            )
            if option_type:
                setup = "Breakout"
                setup_level = breakout_level
                setup_reason = breakout_reason

    if not option_type:
        return {
            "ready": False,
            "reason": "No valid Major Rejection / Pullback / Breakout setup",
            "setup": "NONE",
            "candle_time": candle_time,
            "candle": candle,
            "rsi": signal_rsi,
            "ema9": signal_ema9,
            "ema20": signal_ema20,
        }

    # -------------------------
    # CANDLE SIZE GATE
    # -------------------------
    candle_size_pass = CANDLE_MIN <= candle["range"] <= CANDLE_MAX

    # -------------------------
    # OPPOSITE WICK GATE
    # -------------------------
    wick_pass, opposite_wick = opposite_wick_pass(candle, option_type)

    # -------------------------
    # RSI GATE
    # -------------------------
    if signal_rsi is None:
        rsi_pass = False
        rsi_reason = "RSI unavailable"
    elif setup == "Major Rejection":
        # Rejection is structurally validated; retain prior strategy behavior:
        # RSI gate is considered passed for a true major rejection.
        rsi_pass = True
        rsi_reason = "Major rejection RSI gate"
    elif setup == "Pullback":
        rsi_pass = 45.0 <= signal_rsi <= 55.0
        rsi_reason = "Pullback RSI 45-55"
    else:
        rsi_pass = signal_rsi >= 60.0 if option_type == "CE" else signal_rsi <= 40.0
        rsi_reason = "Breakout RSI directional threshold"

    # -------------------------
    # EMA GATE
    # -------------------------
    if signal_ema9 is None or signal_ema20 is None:
        ema_pass = False
        ema_reason = "EMA unavailable"
    elif setup == "Pullback":
        ema_pass = abs(spot - signal_ema9) <= PULLBACK_EMA_TOLERANCE
        ema_reason = "Pullback within 15 points of EMA9"
    elif setup == "Breakout":
        # EMA is trend context only; actual breakout level is separate.
        if option_type == "CE":
            ema_pass = signal_ema9 >= signal_ema20
            ema_reason = "Bullish EMA9 >= EMA20"
        else:
            ema_pass = signal_ema9 <= signal_ema20
            ema_reason = "Bearish EMA9 <= EMA20"
    else:
        # Rejection uses major-level structure, while EMA is a context gate.
        ema_pass = True
        ema_reason = "Major rejection structural gate"

    # -------------------------
    # VOLUME GATE
    # -------------------------
    volume_ratio = safe_float(
        ind.get("signal_volume_ratio"),
        0.0,
    ) or 0.0
    volume_pass = volume_ratio >= VOLUME_PASS_RATIO

    # -------------------------
    # RUNWAY GATE
    # -------------------------
    day_high = safe_float(ind.get("intraday_high"), spot) or spot
    day_low = safe_float(ind.get("intraday_low"), spot) or spot

    if option_type == "CE":
        runway = max(0.0, day_high - spot)
    else:
        runway = max(0.0, spot - day_low)

    runway_pass = runway >= RUNWAY_MIN

    # -------------------------
    # OI / ORDER-FLOW CONTEXT
    # -------------------------
    oi_state, oi_reason, oi_details = oi_level_confirmation(
        structure,
        option_type,
        spot,
    )

    strike = nearest_strike(spot)
    flow_state, flow_reason, contract_flow = selected_contract_flow(
        structure,
        strike,
        option_type,
    )

    # Market structure is a confirmation gate, but does not replace
    # the technical setup gates.
    structure_pass = (
        oi_state != "OPPOSING"
        and flow_state != "OPPOSING"
    )

    # -------------------------
    # FINAL GATE
    # -------------------------
    failed: List[str] = []

    if not rsi_pass:
        failed.append("RSI")
    if not ema_pass:
        failed.append("EMA")
    if not volume_pass:
        failed.append("VOLUME")
    if not runway_pass:
        failed.append("RUNWAY")
    if not candle_size_pass:
        failed.append("CANDLE_SIZE")
    if not wick_pass:
        failed.append("OPPOSITE_WICK")
    if not structure_pass:
        failed.append("OI_ORDER_FLOW")

    ready = not failed

    if ready:
        reason = (
            f"SIGNAL READY | {setup} | {option_type}_BUY | "
            f"{setup_reason} | "
            f"RSI={signal_rsi:.2f} | "
            f"VOL={volume_ratio:.2f}x | "
            f"RUNWAY={runway:.1f} | "
            f"OI={oi_state} | FLOW={flow_state}"
        )
    else:
        reason = (
            f"LOCKED | {setup} | "
            f"Failed: {', '.join(failed)} | "
            f"{setup_reason}"
        )

    return {
        "ready": ready,
        "setup": setup,
        "trade_type": f"{option_type}_BUY",
        "option_type": option_type,
        "option_strike": strike,
        "candle_time": candle_time,
        "reason": reason,
        "setup_reason": setup_reason,
        "setup_level": setup_level,
        "rsi": signal_rsi,
        "ema9": signal_ema9,
        "ema20": signal_ema20,
        "rsi_pass": rsi_pass,
        "rsi_reason": rsi_reason,
        "ema_pass": ema_pass,
        "ema_reason": ema_reason,
        "volume_ratio": volume_ratio,
        "volume_pass": volume_pass,
        "runway": runway,
        "runway_pass": runway_pass,
        "candle_range": candle["range"],
        "candle_body": candle["body"],
        "upper_wick": candle["upper_wick"],
        "lower_wick": candle["lower_wick"],
        "opposite_wick": opposite_wick,
        "wick_pass": wick_pass,
        "candle_size_pass": candle_size_pass,
        "structure_pass": structure_pass,
        "oi_state": oi_state,
        "oi_reason": oi_reason,
        "oi_details": oi_details,
        "flow_state": flow_state,
        "flow_reason": flow_reason,
        "contract_flow": contract_flow,
        "failed_gates": failed,
        "spot": spot,
        "day_high": day_high,
        "day_low": day_low,
    }


# ============================================================
# INDEX STOP / TARGET
# ============================================================

def calculate_index_risk_levels(
    decision: Dict[str, Any],
    ind: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Index-level exit model.

    CE:
      SL = signal candle low
      Target = next major resistance above entry

    PE:
      SL = signal candle high
      Target = next major support below entry

    If the next major target is not available, use the minimum 15-point
    runway distance as a fallback target.

    This is paper execution logic only.
    """
    candle = decision.get("candle")
    # The detailed candle is reconstructed from completed_candles.
    completed = get_completed_candles(ind)
    if completed:
        c = candle_fields(completed[-1])
    else:
        c = None

    spot = safe_float(decision.get("spot"))
    option_type = decision.get("option_type")

    if spot is None or option_type not in ("CE", "PE") or c is None:
        return None, None, "Cannot calculate index SL/target"

    levels = get_levels(ind)

    if option_type == "CE":
        index_sl = c["low"]
        target_level = nearest_major_above(levels, spot)
        if target_level:
            index_target = safe_float(target_level.get("level"))
            target_source = level_name(target_level)
        else:
            index_target = spot + RUNWAY_MIN
            target_source = "15-point fallback"
    else:
        index_sl = c["high"]
        target_level = nearest_major_below(levels, spot)
        if target_level:
            index_target = safe_float(target_level.get("level"))
            target_source = level_name(target_level)
        else:
            index_target = spot - RUNWAY_MIN
            target_source = "15-point fallback"

    if index_target is None:
        return None, None, "Target unavailable"

    # Ensure target is genuinely in the expected direction.
    if option_type == "CE" and index_target <= spot:
        index_target = spot + RUNWAY_MIN
        target_source = "15-point fallback"
    elif option_type == "PE" and index_target >= spot:
        index_target = spot - RUNWAY_MIN
        target_source = "15-point fallback"

    return float(index_sl), float(index_target), target_source


# ============================================================
# PAPER ENTRY
# ============================================================

def calculate_quantity(
    wallet: float,
    option_ltp: float,
    index_sl: float,
    index_entry: float,
) -> Tuple[int, float, float]:
    """
    Retains the previous paper risk model:
      risk budget = 15% of wallet
      premium SL distance = max(5, min(index distance * 0.50, premium * 0.50))

    No fake entry premium is used.
    """
    index_distance = abs(index_entry - index_sl)

    premium_sl = max(
        5.0,
        min(index_distance * 0.50, option_ltp * 0.50),
    )

    risk_budget = wallet * (RISK_PER_TRADE_PCT / 100.0)

    risk_per_lot = premium_sl * LOT_SIZE

    lots = int(risk_budget / max(risk_per_lot, 1.0))
    lots = max(1, lots)

    qty = lots * LOT_SIZE

    return qty, premium_sl, risk_budget


def create_trade(
    ledger: Dict[str, Any],
    decision: Dict[str, Any],
    ind: Dict[str, Any],
    structure: Dict[str, Any],
    quote: Dict[str, Any],
) -> Dict[str, Any]:
    spot = float(decision["spot"])
    option_type = str(decision["option_type"])
    strike = int(decision["option_strike"])
    option_ltp = float(quote["ltp"])

    index_sl, index_target, target_source = calculate_index_risk_levels(
        decision,
        ind,
    )

    if index_sl is None or index_target is None:
        raise ValueError("Index SL/Target unavailable")

    wallet = safe_float(
        ledger.get("wallet_balance"),
        STARTING_BALANCE,
    ) or STARTING_BALANCE

    qty, premium_sl_distance, risk_budget = calculate_quantity(
        wallet,
        option_ltp,
        index_sl,
        spot,
    )

    premium_target_distance = max(
        10.0,
        abs(index_target - spot) * 0.50,
    )

    premium_sl = max(
        0.05,
        round(option_ltp - premium_sl_distance, 2),
    )
    premium_target = round(
        option_ltp + premium_target_distance,
        2,
    )

    metadata = option_contract_metadata(
        quote,
        strike,
        option_type,
    )

    trade = {
        "trade_id": next_trade_id(ledger["trades"]),
        "status": "ACTIVE",

        "entry_time": now_iso(),
        "time": now_ist().strftime("%H:%M:%S"),

        "type": decision["trade_type"],
        "strategy_used": decision["setup"],
        "setup_reason": decision["setup_reason"],

        "option_symbol": metadata["option_symbol"],
        "option_token": metadata["option_token"],
        "option_strike": strike,
        "option_type": option_type,
        "option_expiry": metadata["option_expiry"],

        # Actual option LTP only.
        "entry": round(option_ltp, 2),
        "option_entry_ltp": round(option_ltp, 2),
        "current_option_ltp": round(option_ltp, 2),

        "qty": qty,
        "lot_size": LOT_SIZE,
        "risk_budget": round(risk_budget, 2),

        "premium_sl": round(premium_sl, 2),
        "premium_target": round(premium_target, 2),
        "sl": round(premium_sl, 2),
        "target": round(premium_target, 2),

        "index_entry": round(spot, 2),
        "index_sl": round(index_sl, 2),
        "index_target": round(index_target, 2),
        "target_source": target_source,

        "pnl_realized": 0.0,
        "running_pnl": 0.0,

        "last_quote_time": quote.get("timestamp"),
        "last_quote_age": round(
            quote_age_seconds(quote.get("timestamp")),
            2,
        ),

        "entry_signal_key": f"{decision['candle_time']}|{decision['trade_type']}|{strike}",
        "candle_time": decision["candle_time"],

        "signal_rsi": decision.get("rsi"),
        "signal_ema9": decision.get("ema9"),
        "signal_ema20": decision.get("ema20"),
        "volume_ratio": decision.get("volume_ratio"),
        "runway": decision.get("runway"),

        "candle_range": decision.get("candle_range"),
        "candle_body": decision.get("candle_body"),
        "upper_wick": decision.get("upper_wick"),
        "lower_wick": decision.get("lower_wick"),

        "oi_state": decision.get("oi_state"),
        "oi_reason": decision.get("oi_reason"),
        "flow_state": decision.get("flow_state"),
        "flow_reason": decision.get("flow_reason"),

        "breakout_level": (
            decision.get("setup_level", {}).get("level")
            if isinstance(decision.get("setup_level"), dict)
            else None
        ),
        "breakout_level_source": (
            level_name(decision.get("setup_level"))
            if decision.get("setup") == "Breakout"
            else ""
        ),

        "entry_spot": round(spot, 2),
        "entry_quote_timestamp": quote.get("timestamp"),
        "entry_quote_age": round(
            quote_age_seconds(quote.get("timestamp")),
            2,
        ),

        "exit_pending": False,
        "exit_trigger": None,
    }

    return trade


# ============================================================
# RUNNING P&L / EXIT
# ============================================================

def update_active_running_pnl(
    active: Dict[str, Any],
    quote: Optional[Dict[str, Any]],
    spot: float,
) -> None:
    if quote is None:
        active["current_option_ltp"] = None
        active["running_pnl"] = 0.0
        return

    ltp = safe_float(quote.get("ltp"))
    if ltp is None or ltp <= 0:
        active["current_option_ltp"] = None
        active["running_pnl"] = 0.0
        return

    entry = safe_float(active.get("option_entry_ltp"))
    qty = safe_int(active.get("qty"), 0)

    if entry is None or qty <= 0:
        return

    running = (ltp - entry) * qty

    active["current_option_ltp"] = round(ltp, 2)
    active["running_pnl"] = round(running, 2)
    active["last_quote_time"] = quote.get("timestamp")
    active["last_quote_age"] = round(
        quote_age_seconds(quote.get("timestamp")),
        2,
    )
    active["last_spot"] = round(spot, 2)


def exit_trigger(
    active: Dict[str, Any],
    spot: float,
) -> Tuple[Optional[str], Optional[str]]:
    option_type = str(active.get("option_type") or "").upper()

    target = safe_float(active.get("index_target"))
    sl = safe_float(active.get("index_sl"))

    if option_type == "CE":
        if target is not None and spot >= target:
            return "TARGET_HIT", "INDEX_TARGET"
        if sl is not None and spot <= sl:
            return "SL_HIT", "INDEX_STOP"

    elif option_type == "PE":
        if target is not None and spot <= target:
            return "TARGET_HIT", "INDEX_TARGET"
        if sl is not None and spot >= sl:
            return "SL_HIT", "INDEX_STOP"

    return None, None


def close_trade(
    ledger: Dict[str, Any],
    active: Dict[str, Any],
    quote: Dict[str, Any],
    spot: float,
    status: str,
    reason: str,
) -> float:
    exit_ltp = safe_float(quote.get("ltp"))
    entry_ltp = safe_float(active.get("option_entry_ltp"))
    qty = safe_int(active.get("qty"), 0)

    if exit_ltp is None or exit_ltp <= 0:
        raise ValueError("Cannot close without actual option LTP")

    if entry_ltp is None or qty <= 0:
        raise ValueError("Invalid active trade entry/quantity")

    pnl = (exit_ltp - entry_ltp) * qty

    active.update({
        "status": status,
        "exit_time": now_iso(),
        "exit_clock": now_ist().strftime("%H:%M:%S"),
        "exit_price": round(exit_ltp, 2),
        "option_exit_ltp": round(exit_ltp, 2),
        "pnl_realized": round(pnl, 2),
        "running_pnl": 0.0,
        "current_option_ltp": round(exit_ltp, 2),
        "index_exit": round(spot, 2),
        "exit_reason": reason,
        "exit_quote_time": quote.get("timestamp"),
        "exit_quote_age": round(
            quote_age_seconds(quote.get("timestamp")),
            2,
        ),
        "exit_pending": False,
        "exit_trigger": None,
    })

    # CRITICAL LOCK:
    # Running P&L NEVER changes wallet.
    # Wallet changes only here, after realized P&L is known.
    old_wallet = safe_float(
        ledger.get("wallet_balance"),
        STARTING_BALANCE,
    ) or STARTING_BALANCE

    ledger["wallet_balance"] = round(old_wallet + pnl, 2)

    return round(pnl, 2)


# ============================================================
# STATE / DUPLICATE PROTECTION
# ============================================================

def load_state() -> Dict[str, Any]:
    local = load_json(
        STATE_FILE,
        {
            "last_entry_candle": "",
            "last_entry_signal_key": "",
            "last_exit_trade_id": "",
            "last_processed_candle": "",
        },
    )

    state = _REMOTE_STATE if isinstance(_REMOTE_STATE, dict) else local
    if not isinstance(state, dict):
        state = {}

    state.setdefault("last_entry_candle", "")
    state.setdefault("last_entry_signal_key", "")
    state.setdefault("last_exit_trade_id", "")
    state.setdefault("last_processed_candle", "")
    atomic_write_json(STATE_FILE, state)
    return state


def save_state(state: Dict[str, Any], force_remote: bool = False) -> None:
    global _REMOTE_STATE
    _REMOTE_STATE = dict(state)
    atomic_write_json(STATE_FILE, state)
    if remote_save_bundle is not None and remote_persistence_enabled():
        # Ledger is loaded globally by start_paper_engine before state is saved.
        current_ledger = load_json(LEDGER_FILE, default_ledger())
        remote_save_bundle(current_ledger, state, force=force_remote)


# ============================================================
# OUTPUT SNAPSHOT
# ============================================================

def publish_output(
    raw: Dict[str, Any],
    ind: Dict[str, Any],
    structure: Dict[str, Any],
    ledger: Dict[str, Any],
    decision: Optional[Dict[str, Any]],
    active: Optional[Dict[str, Any]],
) -> None:
    output = {
        "schema_version": 1,
        "engine": "paper_engine.py",
        "mode": "PAPER_ONLY",
        "last_update_ist": now_iso(),

        "market_status": raw.get("market_status"),
        "worker_status": raw.get("worker_status"),
        "live_spot": raw.get("live_spot"),

        "decision": decision or {
            "ready": False,
            "setup": "NONE",
            "reason": "No decision available",
        },

        "active_trade": active,

        "wallet_balance": ledger.get("wallet_balance"),
        "starting_balance": ledger.get("starting_balance"),
        "realized_pnl": ledger.get("realized_pnl"),
        "running_pnl": ledger.get("active_running_pnl"),
        "total_pnl": ledger.get("total_pnl"),

        "trade_count": ledger.get("total_trades"),
        "closed_trades": ledger.get("closed_trades"),
        "target_hits": ledger.get("target_hits"),
        "sl_hits": ledger.get("sl_hits"),
        "win_rate": ledger.get("win_rate"),

        "architecture": {
            "trade_decision_owner": "paper_engine.py",
            "live_orders": False,
            "uses_actual_option_ltp": True,
            "wallet_updates_only_on_realized_pnl": True,
            "indicator_source": "processed_indicators.json",
            "market_structure_source": "processed_market_structure.json",
            "raw_source": "data_raw.json",
        },
    }

    atomic_write_json(OUTPUT_FILE, output)


# ============================================================
# MAIN LOOP
# ============================================================

def process_once(
    raw: Dict[str, Any],
    ind: Dict[str, Any],
    structure: Dict[str, Any],
    ledger: Dict[str, Any],
    state: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    spot = safe_float(raw.get("live_spot"))

    if spot is None or spot <= 0:
        publish_output(raw, ind, structure, ledger, None, find_active_trade(ledger))
        return ledger, state

    active = find_active_trade(ledger)

    # ========================================================
    # 1. ACTIVE TRADE MANAGEMENT — EVERY TICK
    # ========================================================
    if active is not None:
        strike = safe_int(active.get("option_strike"), 0)
        option_type = str(active.get("option_type") or "").upper()

        quote, quote_status = get_option_quote(
            raw,
            option_type,
            strike,
        )

        update_active_running_pnl(active, quote, spot)

        trigger, trigger_reason = exit_trigger(active, spot)

        if trigger:
            if quote is None:
                active["exit_pending"] = True
                active["exit_trigger"] = trigger
                active["exit_trigger_spot"] = round(spot, 2)
                active["exit_trigger_time"] = now_iso()
                active["exit_wait_reason"] = quote_status
                logging.warning(
                    "⏳ %s reached for %s but waiting for fresh actual option LTP | %s",
                    trigger,
                    active.get("option_symbol"),
                    quote_status,
                )
            else:
                try:
                    pnl = close_trade(
                        ledger,
                        active,
                        quote,
                        spot,
                        trigger,
                        trigger_reason or trigger,
                    )
                    save_ledger(ledger, force_remote=True)

                    state["last_exit_trade_id"] = active.get("trade_id", "")
                    state["last_processed_candle"] = str(
                        active.get("candle_time", "")
                    )
                    save_state(state, force_remote=True)

                    logging.info(
                        "🔴 PAPER EXIT | %s | Entry %.2f | Exit %.2f | Qty %d | P&L ₹%.2f | %s",
                        active.get("option_symbol"),
                        safe_float(active.get("option_entry_ltp"), 0.0) or 0.0,
                        safe_float(active.get("option_exit_ltp"), 0.0) or 0.0,
                        safe_int(active.get("qty"), 0),
                        pnl,
                        trigger,
                    )

                    active = None

                except Exception as exc:
                    logging.exception("Exit error: %s", exc)

        save_ledger(ledger)
        publish_output(raw, ind, structure, ledger, None, active)
        return ledger, state

    # ========================================================
    # 2. NO ACTIVE TRADE — ENTRY DECISION
    # ========================================================

    decision = choose_setup(
        ind,
        structure,
        spot,
    )

    candle_time = str(decision.get("candle_time") or "")

    # Entry is evaluated only once per completed candle.
    if not candle_time:
        publish_output(raw, ind, structure, ledger, decision, None)
        return ledger, state

    if candle_time == state.get("last_entry_candle"):
        publish_output(raw, ind, structure, ledger, decision, None)
        return ledger, state

    # Even a locked candle is marked processed, so the same candle
    # cannot repeatedly trigger expensive entry checks.
    state["last_entry_candle"] = candle_time
    state["last_processed_candle"] = candle_time

    if not decision.get("ready"):
        save_state(state)
        save_ledger(ledger)
        publish_output(raw, ind, structure, ledger, decision, None)
        return ledger, state

    option_type = str(decision["option_type"]).upper()
    strike = int(decision["option_strike"])

    signal_key = (
        f"{candle_time}|{decision.get('trade_type')}|{strike}"
    )

    if signal_key == state.get("last_entry_signal_key"):
        save_state(state)
        publish_output(raw, ind, structure, ledger, decision, None)
        return ledger, state

    # ========================================================
    # 3. ACTUAL OPTION LTP — HARD ENTRY GATE
    # ========================================================

    quote, quote_status = get_option_quote(
        raw,
        option_type,
        strike,
    )

    if quote is None:
        decision = dict(decision)
        decision["ready_for_paper_entry"] = False
        decision["entry_waiting_for_option"] = True
        decision["entry_wait_reason"] = quote_status
        logging.info(
            "🟡 Signal ready but waiting for actual option LTP | %s",
            quote_status,
        )
        save_state(state)
        publish_output(raw, ind, structure, ledger, decision, None)
        return ledger, state

    # ========================================================
    # 4. CREATE PAPER TRADE
    # ========================================================

    try:
        trade = create_trade(
            ledger,
            decision,
            ind,
            structure,
            quote,
        )

        ledger["trades"].append(trade)
        state["last_entry_signal_key"] = signal_key

        save_ledger(ledger, force_remote=True)
        save_state(state, force_remote=True)

        logging.info(
            "🟢 PAPER ENTRY | %s | %s | Strike=%d | "
            "Option LTP=₹%.2f | Qty=%d | Index SL=%.2f | Index Target=%.2f | Strategy=%s",
            trade.get("option_symbol"),
            trade.get("trade_type"),
            strike,
            trade.get("option_entry_ltp"),
            trade.get("qty"),
            trade.get("index_sl"),
            trade.get("index_target"),
            trade.get("strategy_used"),
        )

    except Exception as exc:
        logging.exception("Paper entry creation failed: %s", exc)

    active = find_active_trade(ledger)
    publish_output(raw, ind, structure, ledger, decision, active)

    return ledger, state


def start_paper_engine() -> None:
    logging.info("============================================================")
    logging.info("🟢 NIFTY PAPER ENGINE STARTED")
    logging.info("Mode: PAPER ONLY — NO LIVE ORDERS")
    logging.info("Decision owner: paper_engine.py")
    logging.info("Actual option LTP: REQUIRED")
    logging.info("============================================================")

    ledger = load_ledger()
    state = load_state()

    last_missing_log = 0.0

    while True:
        try:
            raw = load_json(RAW_FILE, None)
            ind = load_json(INDICATOR_FILE, None)
            structure = load_json(STRUCTURE_FILE, None)

            if not isinstance(raw, dict):
                time.sleep(LOOP_SEC)
                continue

            # ------------------------------------------------
            # Market closed:
            # - no new trades
            # - worker retains last snapshot
            # - ACTIVE trade is NOT force-closed
            # ------------------------------------------------
            if not market_open_from_raw(raw):
                active = find_active_trade(ledger)

                if active:
                    # Do not manufacture an exit price after close.
                    # Preserve the last known running P&L.
                    publish_output(
                        raw,
                        ind if isinstance(ind, dict) else {},
                        structure if isinstance(structure, dict) else {},
                        ledger,
                        None,
                        active,
                    )
                else:
                    publish_output(
                        raw,
                        ind if isinstance(ind, dict) else {},
                        structure if isinstance(structure, dict) else {},
                        ledger,
                        None,
                        None,
                    )

                time.sleep(1.0)
                continue

            if not isinstance(ind, dict) or not isinstance(structure, dict):
                if time.time() - last_missing_log > 10:
                    logging.warning(
                        "⏳ Waiting for processed_indicators.json / "
                        "processed_market_structure.json"
                    )
                    last_missing_log = time.time()
                time.sleep(LOOP_SEC)
                continue

            ledger, state = process_once(
                raw,
                ind,
                structure,
                ledger,
                state,
            )

        except Exception as exc:
            logging.exception("🔴 Paper engine error: %s", exc)

        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    start_paper_engine()
