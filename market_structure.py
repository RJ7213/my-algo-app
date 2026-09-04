"""
market_structure.py
===================
NIFTY Market-Structure / Order-Flow Processor

ARCHITECTURE LOCK:
    data_worker.py
        -> raw market data
    market_structure.py
        -> ONLY market-structure calculations
    paper_engine.py
        -> ONLY strategy decisions + paper execution
    Trading app.py
        -> READ-ONLY dashboard

This engine NEVER:
    - creates CALL/PUT trade signals
    - enters/exits trades
    - selects a trade
    - writes strategy_signal.json
    - modifies wallet/P&L

It reads data_raw.json and publishes processed_market_structure.json.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# CONFIG
# ============================================================

RAW_FILE = Path(os.getenv("RAW_FILE", "data_raw.json"))
OUTPUT_FILE = Path(os.getenv("MARKET_STRUCTURE_FILE", "processed_market_structure.json"))

PUBLISH_INTERVAL_SEC = 0.50

# OI / structure
MIN_OI_FOR_MAJOR_LEVEL = float(os.getenv("MIN_OI_FOR_MAJOR_LEVEL", "0"))
TOP_OI_LEVELS = int(os.getenv("TOP_OI_LEVELS", "8"))
TOP_OI_PER_SIDE = int(os.getenv("TOP_OI_PER_SIDE", "5"))

# Psychological structure is 100 points.
PSYCHOLOGICAL_STEP = 100

# Option contract spacing is 50 points.
STRIKE_STEP = 50

# Near-money option structure window. Worker normally supplies +/- 500.
STRUCTURE_WINDOW_POINTS = int(os.getenv("STRUCTURE_WINDOW_POINTS", "500"))

# Order-flow imbalance thresholds.
ORDER_FLOW_IMBALANCE_THRESHOLD = float(
    os.getenv("ORDER_FLOW_IMBALANCE_THRESHOLD", "0.15")
)
ORDER_FLOW_STRONG_THRESHOLD = float(
    os.getenv("ORDER_FLOW_STRONG_THRESHOLD", "0.30")
)

# OI interpretation thresholds.
OI_CHANGE_SIGNIFICANT_PCT = float(
    os.getenv("OI_CHANGE_SIGNIFICANT_PCT", "5.0")
)

# Maximum best-5 levels considered.
BEST5_LEVELS = 5


# ============================================================
# BASIC HELPERS
# ============================================================

def now_ist() -> str:
    """Return current IST timestamp without requiring pytz."""
    from datetime import timezone, timedelta
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        if not math.isfinite(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def round_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def nearest_step(price: float, step: int) -> int:
    return int(round(price / step) * step)


def distance(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return abs(a - b)


def side_from_symbol(symbol: str) -> Optional[str]:
    s = str(symbol or "").upper()
    if s.endswith("CE"):
        return "CE"
    if s.endswith("PE"):
        return "PE"
    return None


# ============================================================
# OPTION-CHAIN NORMALIZATION
# ============================================================

def parse_strike_from_key_or_symbol(key: Any, item: Dict[str, Any]) -> Optional[float]:
    # Worker key is normally "23800:CE".
    if isinstance(key, str) and ":" in key:
        left = key.split(":", 1)[0]
        strike = safe_float(left)
        if strike is not None:
            return strike

    for field in ("strike", "strike_price", "strikePrice"):
        strike = safe_float(item.get(field))
        if strike is not None:
            # Some broker masters encode strike x100.
            if strike > 100000:
                strike /= 100.0
            return strike

    symbol = str(item.get("symbol") or item.get("trading_symbol") or "")
    import re
    m = re.search(r"(\d{4,6})(?:CE|PE)$", symbol.upper())
    if m:
        strike = float(m.group(1))
        if strike > 100000:
            strike /= 100.0
        return strike

    return None


def normalize_best5(item: Dict[str, Any]) -> Tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    """
    Worker already corrects Angel SDK's reversed best-5 naming.
    This function additionally accepts both buy/sell field spellings.
    """
    buy = item.get("best_5_buy_data")
    sell = item.get("best_5_sell_data")

    if not isinstance(buy, list):
        buy = item.get("best5_buy") if isinstance(item.get("best5_buy"), list) else []
    if not isinstance(sell, list):
        sell = item.get("best5_sell") if isinstance(item.get("best5_sell"), list) else []

    def clean(rows: List[Any]) -> List[Dict[str, float]]:
        out = []
        for row in rows[:BEST5_LEVELS]:
            if not isinstance(row, dict):
                continue
            price = safe_float(
                row.get("price", row.get("buy_price", row.get("sell_price")))
            )
            qty = safe_float(
                row.get("quantity", row.get("qty", row.get("buy_quantity", row.get("sell_quantity"))))
            )
            orders = safe_float(row.get("orders", row.get("order_count")))
            if price is None or qty is None:
                continue
            d = {"price": price, "quantity": qty}
            if orders is not None:
                d["orders"] = orders
            out.append(d)
        return out

    return clean(buy), clean(sell)


def normalize_option_chain(raw_chain: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw_chain, dict):
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    for key, raw in raw_chain.items():
        if not isinstance(raw, dict):
            continue

        strike = parse_strike_from_key_or_symbol(key, raw)
        if strike is None:
            continue

        symbol = str(raw.get("symbol") or raw.get("trading_symbol") or key)
        side = side_from_symbol(symbol)

        if side is None and isinstance(key, str) and ":" in key:
            side = key.rsplit(":", 1)[-1].upper()

        if side not in ("CE", "PE"):
            continue

        buy5, sell5 = normalize_best5(raw)

        oi = safe_float(
            raw.get("open_interest", raw.get("oi", raw.get("openInterest"))),
            0.0,
        )
        oi_change_pct = safe_float(
            raw.get(
                "open_interest_change_percentage",
                raw.get("oi_change_pct", raw.get("oi_change_percent")),
            ),
            0.0,
        )
        volume = safe_float(
            raw.get("volume_day", raw.get("volume", raw.get("volume_trade_for_the_day"))),
            0.0,
        )
        ltp = safe_float(raw.get("ltp", raw.get("last_traded_price")))

        total_buy = safe_float(
            raw.get("total_buy_quantity", raw.get("buy_quantity")),
            0.0,
        )
        total_sell = safe_float(
            raw.get("total_sell_quantity", raw.get("sell_quantity")),
            0.0,
        )

        result[f"{int(round(strike))}:{side}"] = {
            "strike": float(strike),
            "side": side,
            "symbol": symbol,
            "token": raw.get("token"),
            "expiry": raw.get("expiry"),
            "ltp": ltp,
            "oi": max(0.0, oi or 0.0),
            "oi_change_pct": oi_change_pct or 0.0,
            "volume": max(0.0, volume or 0.0),
            "total_buy_quantity": max(0.0, total_buy or 0.0),
            "total_sell_quantity": max(0.0, total_sell or 0.0),
            "best5_buy": buy5,
            "best5_sell": sell5,
            "timestamp": raw.get("timestamp"),
            "exchange_timestamp": raw.get("exchange_timestamp"),
        }

    return result


# ============================================================
# OI STRUCTURE
# ============================================================

def aggregate_side(chain: Dict[str, Dict[str, Any]], side: str) -> List[Dict[str, Any]]:
    rows = [x for x in chain.values() if x["side"] == side]
    rows.sort(key=lambda x: x["oi"], reverse=True)
    return rows


def build_oi_ladder(chain: Dict[str, Dict[str, Any]], side: str) -> List[Dict[str, Any]]:
    rows = aggregate_side(chain, side)
    return [
        {
            "strike": r["strike"],
            "side": side,
            "oi": round(r["oi"], 2),
            "oi_change_pct": round(r["oi_change_pct"], 3),
            "volume": round(r["volume"], 2),
            "ltp": round_price(r["ltp"]),
        }
        for r in rows
    ]


def top_oi_levels(chain: Dict[str, Dict[str, Any]], side: str, n: int) -> List[Dict[str, Any]]:
    rows = aggregate_side(chain, side)
    rows = [r for r in rows if r["oi"] >= MIN_OI_FOR_MAJOR_LEVEL]
    return [
        {
            "strike": r["strike"],
            "side": side,
            "oi": round(r["oi"], 2),
            "oi_change_pct": round(r["oi_change_pct"], 3),
            "volume": round(r["volume"], 2),
        }
        for r in rows[:n]
    ]


def build_oi_totals(chain: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    ce = [x for x in chain.values() if x["side"] == "CE"]
    pe = [x for x in chain.values() if x["side"] == "PE"]

    ce_oi = sum(x["oi"] for x in ce)
    pe_oi = sum(x["oi"] for x in pe)
    ce_vol = sum(x["volume"] for x in ce)
    pe_vol = sum(x["volume"] for x in pe)

    return {
        "ce_oi": round(ce_oi, 2),
        "pe_oi": round(pe_oi, 2),
        "total_oi": round(ce_oi + pe_oi, 2),
        "ce_volume": round(ce_vol, 2),
        "pe_volume": round(pe_vol, 2),
        "total_volume": round(ce_vol + pe_vol, 2),
        "pcr_oi": round(pe_oi / ce_oi, 4) if ce_oi > 0 else None,
        "pcr_volume": round(pe_vol / ce_vol, 4) if ce_vol > 0 else None,
    }


# ============================================================
# OI INTERPRETATION
# ============================================================

def classify_oi_change(oi_change_pct: float, option_side: str) -> str:
    """
    Describes option-side OI behavior, without turning it into a trade signal.
    """
    if oi_change_pct >= OI_CHANGE_SIGNIFICANT_PCT:
        return f"{option_side}_OI_BUILDUP"
    if oi_change_pct <= -OI_CHANGE_SIGNIFICANT_PCT:
        return f"{option_side}_OI_UNWINDING"
    return f"{option_side}_OI_STABLE"


def enrich_oi_levels(levels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for x in levels:
        y = dict(x)
        y["oi_state"] = classify_oi_change(
            safe_float(x.get("oi_change_pct"), 0.0) or 0.0,
            str(x.get("side")),
        )
        out.append(y)
    return out


# ============================================================
# MAJOR OI PSYCHOLOGICAL LEVEL
# ============================================================

def nearest_psychological_levels(spot: Optional[float], radius_points: int = 500) -> List[int]:
    if spot is None:
        return []
    center = nearest_step(spot, PSYCHOLOGICAL_STEP)
    return list(range(center - radius_points, center + radius_points + 1, PSYCHOLOGICAL_STEP))


def map_oi_to_psychological_levels(
    chain: Dict[str, Dict[str, Any]],
    spot: Optional[float],
) -> List[Dict[str, Any]]:
    levels = nearest_psychological_levels(spot, 500)
    if not levels:
        return []

    out = []
    for level in levels:
        ce = chain.get(f"{level}:CE")
        pe = chain.get(f"{level}:PE")

        ce_oi = ce["oi"] if ce else 0.0
        pe_oi = pe["oi"] if pe else 0.0
        total = ce_oi + pe_oi

        if total <= 0:
            continue

        if ce_oi > pe_oi:
            dominant = "CE"
        elif pe_oi > ce_oi:
            dominant = "PE"
        else:
            dominant = "BALANCED"

        out.append({
            "level": level,
            "distance_from_spot": round(abs(level - spot), 2) if spot is not None else None,
            "ce_oi": round(ce_oi, 2),
            "pe_oi": round(pe_oi, 2),
            "total_oi": round(total, 2),
            "dominant_oi_side": dominant,
        })

    out.sort(key=lambda x: x["total_oi"], reverse=True)
    return out


# ============================================================
# ORDER FLOW / BEST-5
# ============================================================

def best5_totals(item: Dict[str, Any]) -> Dict[str, float]:
    buy5 = item.get("best5_buy") or []
    sell5 = item.get("best5_sell") or []

    buy_qty = sum(safe_float(x.get("quantity"), 0.0) or 0.0 for x in buy5)
    sell_qty = sum(safe_float(x.get("quantity"), 0.0) or 0.0 for x in sell5)

    return {
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "total_qty": buy_qty + sell_qty,
    }


def order_flow_for_option(item: Dict[str, Any]) -> Dict[str, Any]:
    best = best5_totals(item)

    # Exchange total quantities are more useful than only the top five
    # when available. Best-5 is retained separately for microstructure.
    total_buy = max(0.0, safe_float(item.get("total_buy_quantity"), 0.0) or 0.0)
    total_sell = max(0.0, safe_float(item.get("total_sell_quantity"), 0.0) or 0.0)

    if total_buy + total_sell > 0:
        buy = total_buy
        sell = total_sell
        source = "exchange_total_buy_sell"
    else:
        buy = best["buy_qty"]
        sell = best["sell_qty"]
        source = "best5_buy_sell"

    total = buy + sell
    imbalance = (buy - sell) / total if total > 0 else 0.0

    if imbalance >= ORDER_FLOW_STRONG_THRESHOLD:
        state = "BUY_DOMINANT"
    elif imbalance >= ORDER_FLOW_IMBALANCE_THRESHOLD:
        state = "BUY_BIASED"
    elif imbalance <= -ORDER_FLOW_STRONG_THRESHOLD:
        state = "SELL_DOMINANT"
    elif imbalance <= -ORDER_FLOW_IMBALANCE_THRESHOLD:
        state = "SELL_BIASED"
    else:
        state = "BALANCED"

    return {
        "exchange_buy_qty": round(total_buy, 2),
        "exchange_sell_qty": round(total_sell, 2),
        "best5_buy_qty": round(best["buy_qty"], 2),
        "best5_sell_qty": round(best["sell_qty"], 2),
        "used_buy_qty": round(buy, 2),
        "used_sell_qty": round(sell, 2),
        "imbalance": round(imbalance, 5),
        "state": state,
        "source": source,
    }


def build_order_flow_summary(
    chain: Dict[str, Dict[str, Any]],
    spot: Optional[float],
) -> Dict[str, Any]:
    rows = list(chain.values())
    if spot is not None:
        rows = [
            x for x in rows
            if abs(x["strike"] - spot) <= STRUCTURE_WINDOW_POINTS
        ]

    ce = [x for x in rows if x["side"] == "CE"]
    pe = [x for x in rows if x["side"] == "PE"]

    def side_total(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        buy = sum(max(0.0, x["total_buy_quantity"]) for x in items)
        sell = sum(max(0.0, x["total_sell_quantity"]) for x in items)
        best_buy = sum(
            best5_totals(x)["buy_qty"] for x in items
        )
        best_sell = sum(
            best5_totals(x)["sell_qty"] for x in items
        )
        total = buy + sell
        imbalance = (buy - sell) / total if total > 0 else 0.0
        if imbalance >= ORDER_FLOW_STRONG_THRESHOLD:
            state = "BUY_DOMINANT"
        elif imbalance >= ORDER_FLOW_IMBALANCE_THRESHOLD:
            state = "BUY_BIASED"
        elif imbalance <= -ORDER_FLOW_STRONG_THRESHOLD:
            state = "SELL_DOMINANT"
        elif imbalance <= -ORDER_FLOW_IMBALANCE_THRESHOLD:
            state = "SELL_BIASED"
        else:
            state = "BALANCED"
        return {
            "buy_qty": round(buy, 2),
            "sell_qty": round(sell, 2),
            "best5_buy_qty": round(best_buy, 2),
            "best5_sell_qty": round(best_sell, 2),
            "imbalance": round(imbalance, 5),
            "state": state,
        }

    ce_sum = side_total(ce)
    pe_sum = side_total(pe)

    # Combined option-chain order-flow balance.
    buy = ce_sum["buy_qty"] + pe_sum["buy_qty"]
    sell = ce_sum["sell_qty"] + pe_sum["sell_qty"]
    total = buy + sell
    combined_imbalance = (buy - sell) / total if total > 0 else 0.0

    if combined_imbalance >= ORDER_FLOW_STRONG_THRESHOLD:
        combined_state = "BUY_DOMINANT"
    elif combined_imbalance >= ORDER_FLOW_IMBALANCE_THRESHOLD:
        combined_state = "BUY_BIASED"
    elif combined_imbalance <= -ORDER_FLOW_STRONG_THRESHOLD:
        combined_state = "SELL_DOMINANT"
    elif combined_imbalance <= -ORDER_FLOW_IMBALANCE_THRESHOLD:
        combined_state = "SELL_BIASED"
    else:
        combined_state = "BALANCED"

    return {
        "ce": ce_sum,
        "pe": pe_sum,
        "combined": {
            "buy_qty": round(buy, 2),
            "sell_qty": round(sell, 2),
            "imbalance": round(combined_imbalance, 5),
            "state": combined_state,
        },
    }


# ============================================================
# SUPPORT / RESISTANCE FROM OI
# ============================================================

def oi_support_resistance(
    chain: Dict[str, Dict[str, Any]],
    spot: Optional[float],
) -> Dict[str, Any]:
    if spot is None:
        return {"supports": [], "resistances": []}

    puts = [x for x in chain.values() if x["side"] == "PE" and x["strike"] <= spot]
    calls = [x for x in chain.values() if x["side"] == "CE" and x["strike"] >= spot]

    # Higher PE OI below spot = potential support.
    # Higher CE OI above spot = potential resistance.
    puts.sort(key=lambda x: (x["oi"], -abs(x["strike"] - spot)), reverse=True)
    calls.sort(key=lambda x: (x["oi"], -abs(x["strike"] - spot)), reverse=True)

    supports = [
        {
            "strike": x["strike"],
            "oi": round(x["oi"], 2),
            "oi_change_pct": round(x["oi_change_pct"], 3),
            "distance": round(spot - x["strike"], 2),
        }
        for x in puts[:TOP_OI_PER_SIDE]
    ]

    resistances = [
        {
            "strike": x["strike"],
            "oi": round(x["oi"], 2),
            "oi_change_pct": round(x["oi_change_pct"], 3),
            "distance": round(x["strike"] - spot, 2),
        }
        for x in calls[:TOP_OI_PER_SIDE]
    ]

    supports.sort(key=lambda x: x["distance"])
    resistances.sort(key=lambda x: x["distance"])

    return {
        "supports": supports,
        "resistances": resistances,
        # Compatibility values used by the read-only dashboard.
        "support": supports[0]["strike"] if supports else None,
        "resistance": resistances[0]["strike"] if resistances else None,
    }


# ============================================================
# FUTURES STRUCTURE
# ============================================================

def futures_structure(raw: Dict[str, Any]) -> Dict[str, Any]:
    # data_worker.py publishes the live futures snapshot as future_quote.
    # Keep the older futures_tick name as a compatibility fallback.
    tick = raw.get("future_quote")
    if not isinstance(tick, dict):
        tick = raw.get("futures_tick")
    if not isinstance(tick, dict):
        tick = {}

    ltp = safe_float(tick.get("ltp"))
    buy = safe_float(tick.get("total_buy_quantity"), 0.0) or 0.0
    sell = safe_float(tick.get("total_sell_quantity"), 0.0) or 0.0
    volume = safe_float(
        tick.get("volume_day", tick.get("volume_trade_for_the_day")),
        0.0,
    ) or 0.0
    oi = safe_float(
        tick.get("open_interest", tick.get("oi")),
        0.0,
    ) or 0.0
    oi_change_pct = safe_float(
        tick.get("open_interest_change_percentage", tick.get("oi_change_pct")),
        0.0,
    ) or 0.0

    total = buy + sell
    imbalance = (buy - sell) / total if total > 0 else 0.0

    if imbalance >= ORDER_FLOW_STRONG_THRESHOLD:
        flow_state = "BUY_DOMINANT"
    elif imbalance >= ORDER_FLOW_IMBALANCE_THRESHOLD:
        flow_state = "BUY_BIASED"
    elif imbalance <= -ORDER_FLOW_STRONG_THRESHOLD:
        flow_state = "SELL_DOMINANT"
    elif imbalance <= -ORDER_FLOW_IMBALANCE_THRESHOLD:
        flow_state = "SELL_BIASED"
    else:
        flow_state = "BALANCED"

    return {
        "contract": raw.get("future_contract") or raw.get("futures_contract"),
        "ltp": round_price(ltp),
        "volume_day": round(volume, 2),
        "open_interest": round(oi, 2),
        "oi_change_pct": round(oi_change_pct, 3),
        "total_buy_quantity": round(buy, 2),
        "total_sell_quantity": round(sell, 2),
        "order_flow_imbalance": round(imbalance, 5),
        "order_flow_state": flow_state,
        "timestamp": tick.get("timestamp"),
        "exchange_timestamp": tick.get("exchange_timestamp"),
    }


# ============================================================
# PRICE + OI LEVEL MAP
# ============================================================

def level_context(
    spot: Optional[float],
    oi_psych: List[Dict[str, Any]],
    oi_sr: Dict[str, Any],
) -> Dict[str, Any]:
    if spot is None:
        return {
            "nearest_oi_support": None,
            "nearest_oi_resistance": None,
            "nearest_major_oi_level": None,
            "nearest_major_oi_level_distance": None,
        }

    supports = oi_sr.get("supports") or []
    resistances = oi_sr.get("resistances") or []

    nearest_support = supports[0] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    major = sorted(
        oi_psych,
        key=lambda x: (
            -safe_float(x.get("total_oi"), 0.0),
            safe_float(x.get("distance_from_spot"), 999999.0),
        ),
    )
    nearest_major = major[0] if major else None

    return {
        "nearest_oi_support": nearest_support,
        "nearest_oi_resistance": nearest_resistance,
        "nearest_major_oi_level": nearest_major,
        "nearest_major_oi_level_distance": (
            nearest_major.get("distance_from_spot") if nearest_major else None
        ),
    }


# ============================================================
# MARKET STRUCTURE SCORECARD
# ============================================================

def structure_scorecard(
    spot: Optional[float],
    totals: Dict[str, Any],
    futures: Dict[str, Any],
    flow: Dict[str, Any],
    oi_psych: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Descriptive scorecard only.
    It is deliberately NOT a CALL/PUT/trade signal.
    Paper Engine can combine these observations with technical setup gates.
    """
    observations: List[str] = []

    pcr = totals.get("pcr_oi")
    if pcr is not None:
        if pcr > 1.20:
            observations.append("PUT_OI_HEAVIER")
        elif pcr < 0.80:
            observations.append("CALL_OI_HEAVIER")
        else:
            observations.append("OI_BALANCED")

    futures_flow = futures.get("order_flow_state")
    if futures_flow:
        observations.append(f"FUTURES_{futures_flow}")

    option_flow = flow.get("combined", {}).get("state")
    if option_flow:
        observations.append(f"OPTIONS_{option_flow}")

    if oi_psych:
        top = oi_psych[0]
        observations.append(
            f"MAX_OI_PSY_LEVEL_{int(round(top['level']))}"
        )

    # This is a structure score, not a directional trade score.
    score = 0
    if pcr is not None:
        if pcr > 1.20:
            score += 1
        elif pcr < 0.80:
            score -= 1

    if futures_flow in ("BUY_BIASED", "BUY_DOMINANT"):
        score += 1
    elif futures_flow in ("SELL_BIASED", "SELL_DOMINANT"):
        score -= 1

    return {
        "structure_score": score,
        "observations": observations,
        "directional_trade_signal": None,  # HARD LOCK: no trade signal here
    }


# ============================================================
# MAIN PROCESSOR
# ============================================================

def build_market_structure(raw: Dict[str, Any]) -> Dict[str, Any]:
    spot = safe_float(raw.get("live_spot"))

    chain = normalize_option_chain(raw.get("option_chain"))
    totals = build_oi_totals(chain)

    ce_ladder = build_oi_ladder(chain, "CE")
    pe_ladder = build_oi_ladder(chain, "PE")

    top_ce = enrich_oi_levels(top_oi_levels(chain, "CE", TOP_OI_LEVELS))
    top_pe = enrich_oi_levels(top_oi_levels(chain, "PE", TOP_OI_LEVELS))

    oi_psych = map_oi_to_psychological_levels(chain, spot)
    oi_sr = oi_support_resistance(chain, spot)

    flow_per_option: Dict[str, Any] = {}
    for key, item in chain.items():
        flow_per_option[key] = order_flow_for_option(item)

    option_flow = build_order_flow_summary(chain, spot)
    futures = futures_structure(raw)

    context = level_context(spot, oi_psych, oi_sr)
    scorecard = structure_scorecard(
        spot, totals, futures, option_flow, oi_psych
    )

    # Highest-OI psychological level, explicitly exposed for Paper Engine.
    max_oi_psych = oi_psych[0] if oi_psych else None

    # Near-ATM snapshots make downstream selection cheap.
    atm_strike = nearest_step(spot, STRIKE_STEP) if spot is not None else None
    atm = {}
    if atm_strike is not None:
        for side in ("CE", "PE"):
            key = f"{atm_strike}:{side}"
            if key in chain:
                atm[side] = {
                    **chain[key],
                    "order_flow": flow_per_option.get(key),
                }

    return {
        "schema_version": 1,
        "processor": "market_structure.py",
        "data_source": raw.get("data_source"),
        "market_status": raw.get("market_status"),
        "worker_status": raw.get("worker_status"),
        "last_update_ist": now_ist(),

        "spot": round_price(spot),
        "spot_timestamp": raw.get("spot_timestamp"),

        # ----------------------------------------------------
        # OI
        # ----------------------------------------------------
        "oi": {
            "totals": totals,
            "ce_ladder": ce_ladder,
            "pe_ladder": pe_ladder,
            "top_ce_oi": top_ce,
            "top_pe_oi": top_pe,
            "highest_oi_psychological_level": max_oi_psych,
            "psychological_oi_levels": oi_psych,
        },

        # ----------------------------------------------------
        # OI-derived structure
        # ----------------------------------------------------
        "oi_support_resistance": oi_sr,
        "level_context": context,

        # ----------------------------------------------------
        # Order flow
        # ----------------------------------------------------
        "order_flow": {
            "options": option_flow,
            "per_option": flow_per_option,
        },

        # ----------------------------------------------------
        # Futures
        # ----------------------------------------------------
        "futures": futures,

        # ----------------------------------------------------
        # ATM quick access
        # ----------------------------------------------------
        "atm": {
            "strike": atm_strike,
            "contracts": atm,
        },

        # ----------------------------------------------------
        # Metadata useful to dashboard/paper engine
        # ----------------------------------------------------
        "option_chain_meta": {
            "contracts_processed": len(chain),
            "window_points": STRUCTURE_WINDOW_POINTS,
            "strike_step": STRIKE_STEP,
            "chain_center": raw.get("option_chain_center"),
            "latest_tick": raw.get("option_chain_latest_tick"),
        },

        "scorecard": scorecard,

        # Explicit architecture lock.
        "trade_decision": {
            "signal": None,
            "trade_type": None,
            "entry": None,
            "exit": None,
            "reason": None,
            "owner": "paper_engine.py",
        },
    }


def main() -> None:
    print("============================================================")
    print("NIFTY MARKET STRUCTURE ENGINE")
    print("Mode: PROCESS ONLY / NO TRADE DECISIONS")
    print("============================================================")

    last_signature = None

    while True:
        raw = load_json(RAW_FILE)

        if raw is None:
            time.sleep(PUBLISH_INTERVAL_SEC)
            continue

        # Avoid needless recalculation when worker data hasn't changed.
        signature = (
            raw.get("last_update_ist"),
            raw.get("spot_timestamp"),
            raw.get("option_chain_latest_tick"),
            len(raw.get("option_chain") or {}),
        )

        if signature == last_signature:
            time.sleep(PUBLISH_INTERVAL_SEC)
            continue

        try:
            output = build_market_structure(raw)
            atomic_write_json(OUTPUT_FILE, output)
            last_signature = signature
        except Exception as exc:
            # Never destroy the last good output because one tick is malformed.
            print(f"⚠️ market_structure processing error: {exc}")

        time.sleep(PUBLISH_INTERVAL_SEC)


if __name__ == "__main__":
    main()
