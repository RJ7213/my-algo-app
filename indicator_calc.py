# indicator_calc.py
# ============================================================
# NIFTY INDICATOR + STRATEGY ENGINE
# ============================================================
#
# ARCHITECTURE
#
#   data_worker.py
#          |
#          v
#    data_raw.json
#          |
#          v
#  indicator_calc.py
#          |
#          +--> strategy_signal.json
#          |
#          v
#     paper_engine.py
#          |
#          v
#   trade_history.json
#          |
#          v
#      dashboard
#
# IMPORTANT:
#   - This file contains indicator + strategy calculation.
#   - Dashboard DOES NOT calculate RSI/EMA/volume/runway.
#   - data_worker DOES NOT calculate strategy.
#   - Paper engine handles trade execution simulation.
#   - Entry trigger is generated ONLY from the LAST COMPLETED
#     5-minute candle.
#   - Live candle is used for LIVE DISPLAY INDICATORS only.
#   - The current forming candle can NEVER create a new entry.
#
# Existing strategy rules preserved:
#   Major Rejection
#   Pullback
#   Breakout
#   RSI
#   EMA9
#   EMA20
#   Volume >= 1.20x
#   Runway >= 15 points
#   Candle range 12-25 points
#   Opposite wick <= 5% of body
#
# ============================================================

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone, time as dtime

import numpy as np
import pandas as pd


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

IST = timezone(timedelta(hours=5, minutes=30))

DATA_RAW_FILE = "data_raw.json"
SIGNAL_FILE = "processed_indicators.json"
LEGACY_SIGNAL_FILE = "strategy_signal.json"


# ============================================================
# STRATEGY CONSTANTS
# ============================================================

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 20

VOLUME_LOOKBACK = 20
MIN_VOLUME_RATIO = 1.20

MIN_RUNWAY = 15.0

MIN_CANDLE_RANGE = 12.0
MAX_CANDLE_RANGE = 25.0

MAX_OPPOSITE_WICK_RATIO = 0.05

PSYCHOLOGICAL_STEP = 100.0
PSY_REJECTION_DISTANCE = 25.0

TARGET_BUFFER = 5.0
LEVEL_MERGE_DISTANCE = 20.0
MORNING_BOX_START = "09:15"
MORNING_BOX_END = "09:30"
CONTINUOUS_SESSION_START = dtime(9, 15)
CONTINUOUS_SESSION_END = dtime(15, 15)


# ============================================================
# JSON
# ============================================================

def now_ist():
    return datetime.now(IST)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"

    with open(tmp, "w") as f:
        json.dump(
            payload,
            f,
            separators=(",", ":"),
            default=str,
        )

    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


CONFIG_FILE = "strategy_config.json"


def load_strategy_config():
    cfg = load_json(CONFIG_FILE, {})
    return cfg if isinstance(cfg, dict) else {}


def cfg_float(cfg, *keys, default):
    cur = cfg
    try:
        for key in keys:
            cur = cur[key]
        return float(cur)
    except (KeyError, TypeError, ValueError):
        return float(default)


# ============================================================
# RSI
# ============================================================

def calculate_tv_rsi(series, period=14):
    """
    TradingView-style Wilder/RMA RSI.
    """

    series = pd.to_numeric(
        series,
        errors="coerce",
    )

    if len(series) < period + 1:
        return 50.0

    delta = series.diff()

    gain = delta.where(
        delta > 0,
        0.0,
    ).astype(float)

    loss = (
        -delta.where(
            delta < 0,
            0.0,
        )
    ).astype(float)

    alpha = 1 / period

    avg_gain = gain.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        0.00001,
    )

    rsi = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    value = rsi.iloc[-1]

    if pd.isna(value):
        return 50.0

    return float(value)


# ============================================================
# DATAFRAME
# ============================================================

def continuous_session_only(df):
    if df is None or df.empty:
        return df
    result = df.copy()
    dt = pd.to_datetime(result["datetime"], errors="coerce")
    result = result.loc[dt.notna()].copy()
    dt = pd.to_datetime(result["datetime"], errors="coerce")
    times = dt.dt.time
    return result.loc[(dt.dt.weekday < 5) & (times >= CONTINUOUS_SESSION_START) & (times < CONTINUOUS_SESSION_END)].reset_index(drop=True)


def build_dataframe(candles):
    if not isinstance(candles, list):
        return pd.DataFrame()

    rows = []

    for row in candles:

        if not isinstance(row, (list, tuple)):
            continue

        if len(row) < 6:
            continue

        rows.append(
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
            ]
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=[
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    for col in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    df["datetime"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    )

    df = df.sort_values(
        "datetime"
    )

    # One row per timestamp.
    df = (
        df.drop_duplicates(
            subset=["datetime"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return continuous_session_only(df)
# ============================================================
# INDICATORS
# ============================================================

def calculate_indicators(df):

    df = df.copy()

    df["EMA9"] = (
        df["close"]
        .ewm(
            span=EMA_FAST,
            adjust=False,
        )
        .mean()
    )

    df["EMA20"] = (
        df["close"]
        .ewm(
            span=EMA_SLOW,
            adjust=False,
        )
        .mean()
    )

    # Calculate RSI for every candle.
    delta = df["close"].diff()

    gain = delta.where(
        delta > 0,
        0.0,
    ).astype(float)

    loss = (
        -delta.where(
            delta < 0,
            0.0,
        )
    ).astype(float)

    alpha = 1 / RSI_PERIOD

    avg_gain = gain.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        0.00001,
    )

    df["RSI"] = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    return df


# ============================================================
# CURRENT / CLOSED CANDLE
# ============================================================

def get_candle_status(df):
    """
    Returns:
        live index = -1
        closed index = -2

    The latest row is treated as forming because the worker
    publishes the current 5-minute candle continuously.
    """

    if len(df) < 22:
        return None, None

    return -1, -2


# ============================================================
# CANDLE STRUCTURE
# ============================================================

def candle_metrics(row):

    c_open = float(row["open"])
    c_close = float(row["close"])
    c_high = float(row["high"])
    c_low = float(row["low"])

    candle_range = abs(
        c_high - c_low
    )

    candle_body = abs(
        c_close - c_open
    )

    if candle_range <= 0:
        candle_range = 0.01

    if candle_body <= 0:
        candle_body = 0.01

    top_wick = max(
        0.0,
        c_high
        - max(
            c_open,
            c_close,
        ),
    )

    bottom_wick = max(
        0.0,
        min(
            c_open,
            c_close,
        )
        - c_low,
    )

    return {
        "c_open": c_open,
        "c_close": c_close,
        "c_high": c_high,
        "c_low": c_low,
        "candle_range": candle_range,
        "candle_body": candle_body,
        "top_wick": top_wick,
        "bottom_wick": bottom_wick,
    }


# ============================================================
# LEVEL ENGINE / STRUCTURE SNAPSHOT
# ============================================================

def build_completed_candles(df):
    """Publish completed candles in the schema expected by paper_engine."""
    if df.empty or len(df) < 2:
        return []

    completed = df.iloc[:-1].tail(250)
    out = []
    for _, row in completed.iterrows():
        out.append({
            "date": str(row["datetime"]),
            "datetime": str(row["datetime"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"] or 0.0),
        })
    return out


def build_level_engine(df, spot, day_high, day_low):
    """Build fixed intraday S/R zones from completed candles only."""
    empty = {
        "levels": [], "zones": [], "support": None, "resistance": None,
        "support_level": None, "resistance_level": None,
        "previous_day_high": None, "previous_day_low": None,
        "morning_box_high": None, "morning_box_low": None,
    }
    if df.empty or spot is None:
        return empty

    completed = df.iloc[:-1].copy()
    if completed.empty:
        return empty
    completed["session_date"] = completed["datetime"].dt.date
    current_date = completed["session_date"].max()
    current = completed[completed["session_date"] == current_date].copy()
    prior_dates = sorted(x for x in completed["session_date"].unique() if x < current_date)
    previous = (
        completed[completed["session_date"] == prior_dates[-1]].copy()
        if prior_dates else completed.iloc[0:0].copy()
    )

    raw_levels = []
    def add(value, name, source, strength, allowed):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        raw_levels.append({
            "level": round(value, 2), "name": name, "source": source,
            "strength": float(strength), "allowed_setups": list(allowed),
        })

    pdh = float(previous["high"].max()) if not previous.empty else None
    pdl = float(previous["low"].min()) if not previous.empty else None
    add(pdh, "Previous Day High", "previous_day_high", 7.0, ["REJECTION", "BREAKOUT"])
    add(pdl, "Previous Day Low", "previous_day_low", 7.0, ["REJECTION", "BREAKOUT"])

    morning = current[
        (current["datetime"].dt.strftime("%H:%M") >= MORNING_BOX_START)
        & (current["datetime"].dt.strftime("%H:%M") < MORNING_BOX_END)
    ]
    box_complete = (
        not current.empty
        and current["datetime"].dt.strftime("%H:%M").max() >= MORNING_BOX_END
        and len(morning) >= 3
    )
    mbh = float(morning["high"].max()) if box_complete else None
    mbl = float(morning["low"].min()) if box_complete else None
    add(mbh, "Morning Box High", "morning_box_high", 6.0, ["REJECTION", "BREAKOUT"])
    add(mbl, "Morning Box Low", "morning_box_low", 6.0, ["REJECTION", "BREAKOUT"])

    add(day_high, "Day High", "day_high", 5.0, ["REJECTION"])
    add(day_low, "Day Low", "day_low", 5.0, ["REJECTION"])

    swings = current.reset_index(drop=True)
    if len(swings) >= 3:
        for i in range(1, len(swings) - 1):
            a, b, c = swings.iloc[i-1], swings.iloc[i], swings.iloc[i+1]
            if float(b["high"]) >= float(a["high"]) and float(b["high"]) >= float(c["high"]):
                add(b["high"], "Swing High", "swing_high", 3.0, ["REJECTION", "BREAKOUT"])
            if float(b["low"]) <= float(a["low"]) and float(b["low"]) <= float(c["low"]):
                add(b["low"], "Swing Low", "swing_low", 3.0, ["REJECTION", "BREAKOUT"])

    center = round(float(spot) / PSYCHOLOGICAL_STEP) * PSYCHOLOGICAL_STEP
    for n in range(-6, 7):
        level = center + n * PSYCHOLOGICAL_STEP
        if abs(level - float(spot)) <= 600:
            add(level, "Psychological Level", "psychological", 1.0, ["REJECTION"])

    # Exact-price dedupe first, retaining the strongest source.
    dedup = {}
    for item in raw_levels:
        key = round(item["level"], 2)
        old = dedup.get(key)
        if old is None or item["strength"] > old["strength"]:
            dedup[key] = item
    ordered = sorted(dedup.values(), key=lambda x: x["level"])

    # Merge only while the total zone width remains <= 20 points.
    groups = []
    for item in ordered:
        if not groups or item["level"] - groups[-1][0]["level"] > LEVEL_MERGE_DISTANCE:
            groups.append([item])
        else:
            groups[-1].append(item)

    zones = []
    for group in groups:
        strongest = sorted(group, key=lambda x: (-x["strength"], x["level"]))[0]
        sources = sorted({x["source"] for x in group})
        allowed = sorted({a for x in group for a in x["allowed_setups"]})
        # Psychological-only zones are rejection-only. Confluence may inherit breakout eligibility.
        zone = {
            "level": strongest["level"],
            "anchor_level": strongest["level"],
            "zone_low": min(x["level"] for x in group),
            "zone_high": max(x["level"] for x in group),
            "name": strongest["name"] + (" Confluence" if len(group) > 1 else ""),
            "source": strongest["source"],
            "sources": sources,
            "strength": strongest["strength"],
            "combined_strength": round(sum(x["strength"] for x in group), 2),
            "confluence_count": len(group),
            "allowed_setups": allowed,
        }
        zones.append(zone)

    below = [z for z in zones if z["zone_high"] < float(spot)]
    above = [z for z in zones if z["zone_low"] > float(spot)]
    inside = [z for z in zones if z["zone_low"] <= float(spot) <= z["zone_high"]]
    below.sort(key=lambda z: float(spot) - z["zone_high"])
    above.sort(key=lambda z: z["zone_low"] - float(spot))
    support = below[0] if below else (inside[0] if inside else None)
    resistance = above[0] if above else (inside[0] if inside else None)
    return {
        "levels": zones, "zones": zones,
        "support": support["zone_high"] if support else None,
        "resistance": resistance["zone_low"] if resistance else None,
        "support_level": support, "resistance_level": resistance,
        "previous_day_high": pdh, "previous_day_low": pdl,
        "morning_box_high": mbh, "morning_box_low": mbl,
        "merge_distance": LEVEL_MERGE_DISTANCE,
    }

def calculate_live_snapshot(
    df,
    spot,
    day_high,
    day_low,
):
    """
    LIVE values for dashboard.

    These values are NOT allowed to create an entry.
    """

    if df.empty:
        return {}

    last = df.iloc[-1]

    rsi_live = (
        float(last["RSI"])
        if not pd.isna(last["RSI"])
        else 50.0
    )

    ema9_live = float(
        last["EMA9"]
    )

    ema20_live = float(
        last["EMA20"]
    )

    return {
        "live_rsi": round(
            rsi_live,
            2,
        ),
        "live_ema9": round(
            ema9_live,
            2,
        ),
        "live_ema20": round(
            ema20_live,
            2,
        ),
        "live_spot": round(
            float(spot),
            2,
        ),
        "live_intraday_high": round(
            float(day_high),
            2,
        ),
        "live_intraday_low": round(
            float(day_low),
            2,
        ),
        "live_candle_time": str(
            last["datetime"]
        ),
        "live_candle_open": float(
            last["open"]
        ),
        "live_candle_high": float(
            last["high"]
        ),
        "live_candle_low": float(
            last["low"]
        ),
        "live_candle_close": float(
            last["close"]
        ),
    }


# ============================================================
# COMPLETED-CANDLE STRATEGY
# ============================================================

def calculate_closed_candle_signal(
    df,
    spot,
    day_high,
    day_low,
    volume_df=None,
    option_volume_snapshot=None,
):
    """
    ALL entry logic is based on the completed candle (-2).

    This prevents intrabar signal repainting.
    """

    cfg = load_strategy_config()
    min_candle_range = cfg_float(cfg, "candle", "min_range", default=MIN_CANDLE_RANGE)
    max_candle_range = cfg_float(cfg, "candle", "max_range", default=MAX_CANDLE_RANGE)
    min_runway = cfg_float(cfg, "runway", "min_points", default=MIN_RUNWAY)
    wick_ratio = cfg_float(cfg, "wick", "max_body_ratio", default=MAX_OPPOSITE_WICK_RATIO)
    volume_min_ratio = cfg_float(cfg, "volume", "min_ratio", default=MIN_VOLUME_RATIO)

    if len(df) < 22:

        return {
            "ready": False,
            "reason": "Waiting for 22 candles",
        }

    closed_idx = -2

    row = df.iloc[closed_idx]

    metrics = candle_metrics(row)

    c_open = metrics["c_open"]
    c_close = metrics["c_close"]
    c_high = metrics["c_high"]
    c_low = metrics["c_low"]

    candle_range = metrics["candle_range"]
    candle_body = metrics["candle_body"]

    top_wick = metrics["top_wick"]
    bottom_wick = metrics["bottom_wick"]

    rsi_v = float(
        row["RSI"]
        if not pd.isna(row["RSI"])
        else 50.0
    )

    ema9 = float(
        row["EMA9"]
    )

    ema20 = float(
        row["EMA20"]
    )

    # --------------------------------------------------------
    # Psychological level
    # --------------------------------------------------------

    psy_level = int(
        round(
            float(spot)
            / PSYCHOLOGICAL_STEP
        )
        * PSYCHOLOGICAL_STEP
    )

    # --------------------------------------------------------
    # Candle size
    # --------------------------------------------------------

    is_candle_size_valid = (
        min_candle_range
        <= candle_range
        <= max_candle_range
    )

    # --------------------------------------------------------
    # Rejection
    # --------------------------------------------------------

    upper_rejection = (
        abs(c_high - psy_level)
        <= PSY_REJECTION_DISTANCE
        and top_wick
        >= candle_range * 0.50
    )

    lower_rejection = (
        abs(c_low - psy_level)
        <= PSY_REJECTION_DISTANCE
        and bottom_wick
        >= candle_range * 0.50
    )

    is_rejection = (
        upper_rejection
        or lower_rejection
    )

    # --------------------------------------------------------
    # Pullback
    # --------------------------------------------------------

    cfg = load_strategy_config()
    pullback_tolerance = cfg_float(
        cfg, "pullback", "ema_tolerance",
        default=cfg_float(cfg, "ema", "pullback_tolerance", default=15.0),
    )
    pullback_ce_rsi_min = cfg_float(
        cfg, "pullback", "ce_rsi_min",
        default=cfg_float(cfg, "rsi", "ce_min", default=60.0),
    )
    pullback_pe_rsi_max = cfg_float(
        cfg, "pullback", "pe_rsi_max",
        default=cfg_float(cfg, "rsi", "pe_max", default=40.0),
    )

    is_pullback = (
        not is_rejection
        and abs(float(spot) - ema9) <= pullback_tolerance
    )

    # --------------------------------------------------------
    # Defaults
    # --------------------------------------------------------

    otype = "NONE"

    rsi_status = "FAIL"
    ema_status = "FAIL"

    setup_name = "NONE"

    candle_confirmed = False

    # --------------------------------------------------------
    # MAJOR REJECTION
    # --------------------------------------------------------

    if is_rejection:

        if upper_rejection:
            otype = "PE"
        elif lower_rejection:
            otype = "CE"

        rsi_status = "PASS"
        ema_status = "PASS"

        setup_name = "Major Rejection"

        # Existing rejection structure itself confirms candle.
        candle_confirmed = True

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    elif is_pullback:

        otype = (
            "CE"
            if float(spot) >= ema9
            else "PE"
        )

        rsi_status = (
            "PASS"
            if (
                (otype == "CE" and rsi_v >= pullback_ce_rsi_min)
                or (otype == "PE" and rsi_v <= pullback_pe_rsi_max)
            )
            else "FAIL"
        )

        ema_status = (
            "PASS"
            if abs(
                float(spot) - ema9
            ) <= 15.0
            else "FAIL"
        )

        setup_name = "Pullback"

        opposite_wick = (
            top_wick
            if otype == "CE"
            else bottom_wick
        )

        candle_confirmed = (
            opposite_wick
            <= candle_body
            * wick_ratio
        )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    else:

        if float(spot) > ema9:

            otype = "CE"

            rsi_status = (
                "PASS"
                if rsi_v >= 60.0
                else "FAIL"
            )

        else:

            otype = "PE"

            rsi_status = (
                "PASS"
                if rsi_v <= 40.0
                else "FAIL"
            )

        ema_status = "PASS"

        setup_name = "Breakout"

        opposite_wick = (
            top_wick
            if otype == "CE"
            else bottom_wick
        )

        candle_confirmed = (
            opposite_wick
            <= candle_body
            * wick_ratio
        )

    # --------------------------------------------------------
    # Trade type
    # --------------------------------------------------------

    trade_type = (
        f"{otype}_BUY"
        if otype != "NONE"
        else "NONE"
    )

    # --------------------------------------------------------
    # OPTION VOLUME
    # Exact selected option contract only.
    # volume_day is cumulative broker volume; the indicator engine
    # converts tracked cumulative snapshots into completed 5-minute
    # bucket volume and compares the latest completed bucket with
    # prior completed buckets.
    # --------------------------------------------------------
    selected_volume = option_volume_snapshot or {}
    current_volume = selected_volume.get("current_bucket_volume")
    vol_avg = selected_volume.get("average_previous_bucket_volume")
    vol_ratio = selected_volume.get("volume_ratio")
    vol_data_valid = bool(selected_volume.get("data_valid", False))

    if vol_ratio is None and current_volume is not None and vol_avg not in (None, 0):
        vol_ratio = round(float(current_volume) / float(vol_avg), 2)
        vol_data_valid = True

    vol_status = (
        "PASS"
        if vol_data_valid and vol_ratio is not None and vol_ratio >= volume_min_ratio
        else "FAIL"
    )
    # --------------------------------------------------------
    # RUNWAY
    # --------------------------------------------------------

    if otype == "CE":

        runway_distance = (
            float(day_high)
            - float(spot)
        )

    elif otype == "PE":

        runway_distance = (
            float(spot)
            - float(day_low)
        )

    else:

        runway_distance = 0.0

    runway_distance = max(
        0.0,
        runway_distance,
    )

    runway_status = (
        "PASS"
        if runway_distance >= min_runway
        else "FAIL"
    )

    # --------------------------------------------------------
    # FINAL GATE
    # --------------------------------------------------------


