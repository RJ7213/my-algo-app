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
from datetime import datetime, timedelta, timezone

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

PSYCHOLOGICAL_STEP = 50.0
PSY_REJECTION_DISTANCE = 25.0

TARGET_BUFFER = 5.0


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

    return df


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
    """
    Build the major-level list consumed by paper_engine.

    Sources are deliberately limited to observable market structure:
    day high/low, recent swing highs/lows, and 100-point psychological
    levels. EMA is never used as a support/resistance substitute.
    """
    if df.empty or spot is None:
        return {"levels": [], "support": None, "resistance": None}

    levels = []

    def add(level, name, source, strength):
        try:
            value = float(level)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        levels.append({
            "level": round(value, 2),
            "name": name,
            "source": source,
            "strength": float(strength),
        })

    # Day extremes are genuine market levels.
    if day_low is not None:
        add(day_low, "Day Low", "day_range", 5.0)
    if day_high is not None:
        add(day_high, "Day High", "day_range", 5.0)

    # Recent 3-candle swing points. Keep the latest 120 completed candles.
    completed = df.iloc[:-1].tail(120).reset_index(drop=True)
    if len(completed) >= 3:
        for i in range(1, len(completed) - 1):
            prev_r = completed.iloc[i - 1]
            cur = completed.iloc[i]
            next_r = completed.iloc[i + 1]
            if float(cur["high"]) >= float(prev_r["high"]) and float(cur["high"]) >= float(next_r["high"]):
                add(cur["high"], "Swing High", "swing_high", 3.0)
            if float(cur["low"]) <= float(prev_r["low"]) and float(cur["low"]) <= float(next_r["low"]):
                add(cur["low"], "Swing Low", "swing_low", 3.0)

    # Psychological levels remain available for rejection context.
    center = round(float(spot) / PSYCHOLOGICAL_STEP) * PSYCHOLOGICAL_STEP
    for n in range(-6, 7):
        level = center + n * PSYCHOLOGICAL_STEP
        if abs(level - float(spot)) <= 600:
            add(level, "Psychological Level", "psychological", 1.0)

    # Deduplicate, keeping the strongest source at the same price.
    dedup = {}
    for item in levels:
        key = round(item["level"], 2)
        old = dedup.get(key)
        if old is None or item["strength"] > old["strength"]:
            dedup[key] = item
    levels = list(dedup.values())

    below = [x for x in levels if x["level"] < float(spot)]
    above = [x for x in levels if x["level"] > float(spot)]
    below.sort(key=lambda x: abs(float(spot) - x["level"]))
    above.sort(key=lambda x: abs(x["level"] - float(spot)))

    return {
        "levels": levels,
        "support": below[0]["level"] if below else None,
        "resistance": above[0]["level"] if above else None,
        "support_level": below[0] if below else None,
        "resistance_level": above[0] if above else None,
    }

# ============================================================
# LIVE INDICATOR SNAPSHOT
# ============================================================

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
):
    """
    ALL entry logic is based on the completed candle (-2).

    This prevents intrabar signal repainting.
    """

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
        MIN_CANDLE_RANGE
        <= candle_range
        <= MAX_CANDLE_RANGE
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

    is_pullback = (
        not is_rejection
        and abs(
            float(spot) - ema9
        )
        <= 25.0
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
            if 45.0 <= rsi_v <= 55.0
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
            * MAX_OPPOSITE_WICK_RATIO
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
            * MAX_OPPOSITE_WICK_RATIO
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
    # Volume
    #
    # Strategy volume comes from NIFTY spot candle data if
    # available. The worker also publishes FUTURE live volume.
    #
    # For the entry gate, use the completed candle's volume
    # against the previous 20 completed candles.
    # --------------------------------------------------------

    volume_source = volume_df if volume_df is not None and len(volume_df) >= 22 else df
    volume_window = volume_source["volume"].iloc[-22:-2]
    current_volume = float(volume_source["volume"].iloc[-2] or 0.0)
    vol_avg = float(volume_window.mean() if not volume_window.empty else 0.0)

    if vol_avg > 0:

        vol_ratio = round(
            current_volume
            / vol_avg,
            2,
        )

    else:

        vol_ratio = 0.0

    vol_status = (
        "PASS"
        if vol_ratio >= MIN_VOLUME_RATIO
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
        if runway_distance >= MIN_RUNWAY
        else "FAIL"
    )

    # --------------------------------------------------------
    # FINAL GATE
    # --------------------------------------------------------

    signal_gate = (
        otype != "NONE"
        and rsi_status == "PASS"
        and ema_status == "PASS"
        and vol_status == "PASS"
        and runway_status == "PASS"
    )

    final_trigger = (
        signal_gate
        and is_candle_size_valid
        and candle_confirmed
    )

    # --------------------------------------------------------
    # Reason
    # --------------------------------------------------------

    if not signal_gate:

        failed = []

        if rsi_status != "PASS":
            failed.append("RSI")

        if ema_status != "PASS":
            failed.append("EMA")

        if vol_status != "PASS":
            failed.append("VOLUME")

        if runway_status != "PASS":
            failed.append("RUNWAY")

        reason = (
            f"LOCK | {setup_name} | "
            f"Failed: "
            f"{', '.join(failed) if failed else 'SETUP'}"
        )

    elif not is_candle_size_valid:

        reason = (
            f"Size Lock | Candle range "
            f"{candle_range:.1f} pts "
            f"(required "
            f"{MIN_CANDLE_RANGE:.0f}-"
            f"{MAX_CANDLE_RANGE:.0f})"
        )

    elif not candle_confirmed:

        reason = (
            "Marubozu Lock | Opposite wick "
            "exceeds 5% of candle body"
        )

    else:

        reason = (
            f"SIGNAL READY | "
            f"{setup_name} | "
            f"{trade_type} | "
            f"Runway {runway_distance:.1f} pts"
        )

    # --------------------------------------------------------
    # Option strike
    # --------------------------------------------------------

    option_strike = int(
        round(
            float(spot)
            / PSYCHOLOGICAL_STEP
        )
        * PSYCHOLOGICAL_STEP
    )

    # --------------------------------------------------------
    # Next wall
    # --------------------------------------------------------

    if otype == "CE":
        next_wall = float(day_high)

    elif otype == "PE":
        next_wall = float(day_low)

    else:
        next_wall = float(spot)

    return {
        "ready": True,

        "signal_triggered":
            bool(final_trigger),

        "trade_type":
            trade_type,

        "otype":
            otype,

        "option_strike":
            option_strike,

        "strategy_used":
            setup_name,

        "algo_reason":
            reason,

        "rsi_v":
            round(rsi_v, 2),

        "ema9":
            round(ema9, 2),

        "ema20":
            round(ema20, 2),

        "rsi_status":
            rsi_status,

        "ema_status":
            ema_status,

        "vol_status":
            vol_status,

        "vol_val":
            f"{vol_ratio}x",

        "volume_ratio":
            vol_ratio,

        "runway_status":
            runway_status,

        "runway_val":
            f"{runway_distance:.1f} pts",

        "run_df":
            runway_distance,

        "intraday_high":
            float(day_high),

        "intraday_low":
            float(day_low),

        "psy_level":
            psy_level,

        "next_w":
            next_wall,

        "c_open":
            c_open,

        "c_close":
            c_close,

        "c_low":
            c_low,

        "c_high":
            c_high,

        "candle_range":
            candle_range,

        "candle_body":
            candle_body,

        "top_wick":
            top_wick,

        "bottom_wick":
            bottom_wick,

        "candle_size_valid":
            bool(is_candle_size_valid),

        "candle_confirmed":
            bool(candle_confirmed),

        "candle_time":
            str(row["datetime"]),

    }


# ============================================================
# ENGINE
# ============================================================

def start_indicator_engine():

    logging.info(
        "Indicator / strategy backend started"
    )

    last_published_closed_candle = None

    while True:

        try:

            raw = load_json(
                DATA_RAW_FILE,
                None,
            )

            if not isinstance(raw, dict):

                time.sleep(0.5)
                continue

            spot = raw.get(
                "live_spot"
            )

            if spot is None:

                time.sleep(0.5)
                continue

            spot = float(spot)

            candles = raw.get(
                "candles",
                [],
            )

            df = build_dataframe(
                candles
            )

            if len(df) < 22:

                payload = {
                    "live_spot": spot,
                    "signal_triggered": False,
                    "trade_type": "NONE",
                    "otype": "NONE",
                    "strategy_used": "NONE",
                    "algo_reason":
                        f"Waiting for sufficient candles: "
                        f"{len(df)}/22",
                    "engine_status": "WAITING",
                    "candle_count": len(df),
                    "rsi": None,
                    "ema9": None,
                    "ema20": None,
                    "signal_rsi": None,
                    "signal_ema9": None,
                    "signal_ema20": None,
                    "signal_volume_ratio": 0.0,
                    "completed_candles": [],
                    "level_engine": {"levels": [], "support": None, "resistance": None},
                    "support": None,
                    "resistance": None,
                    "calculated_at":
                        now_ist().isoformat(),
                }

                atomic_write_json(SIGNAL_FILE, payload)
                atomic_write_json(LEGACY_SIGNAL_FILE, payload)

                time.sleep(1)
                continue

            # ----------------------------------------------------
            # INDICATORS
            # ----------------------------------------------------

            df = calculate_indicators(
                df
            )

            # ----------------------------------------------------
            # LIVE DAY RANGE
            # ----------------------------------------------------

            day_high = float(
                raw.get(
                    "intraday_high",
                    spot,
                )
            )

            day_low = float(
                raw.get(
                    "intraday_low",
                    spot,
                )
            )

            future_df = build_dataframe(raw.get("future_candles", []))
            level_engine = build_level_engine(df, spot, day_high, day_low)

            # ----------------------------------------------------
            # LIVE INDICATOR SNAPSHOT
            # ----------------------------------------------------

            live_snapshot = (
                calculate_live_snapshot(
                    df,
                    spot,
                    day_high,
                    day_low,
                )
            )

            # ----------------------------------------------------
            # CLOSED CANDLE
            # ----------------------------------------------------

            live_idx, closed_idx = (
                get_candle_status(df)
            )

            closed_candle_time = str(
                df["datetime"].iloc[
                    closed_idx
                ]
            )

            signal = (
                calculate_closed_candle_signal(
                    df,
                    spot,
                    day_high,
                    day_low,
                    future_df,
                )
            )

            # ----------------------------------------------------
            # IMPORTANT:
            #
            # Only the newest completed candle can create a new
            # trigger.
            #
            # Once that candle has already been evaluated,
            # signal_triggered is forced FALSE until a new
            # completed candle arrives.
            # ----------------------------------------------------

            is_new_closed_candle = (
                closed_candle_time
                != last_published_closed_candle
            )

            if is_new_closed_candle:

                last_published_closed_candle = (
                    closed_candle_time
                )

            else:

                # Same closed candle:
                # Do not repeatedly trigger paper entries.
                signal["signal_triggered"] = False

                if signal.get("ready"):

                    if "SIGNAL READY" in str(
                        signal.get(
                            "algo_reason",
                            "",
                        )
                    ):

                        signal["algo_reason"] = (
                            "WAIT | Same completed candle "
                            "already evaluated"
                        )

            # ----------------------------------------------------
            # FINAL PAYLOAD
            # ----------------------------------------------------

            payload = {

                # ------------------------------
                # LIVE DATA
                # ------------------------------

                "live_spot":
                    spot,

                "spot_timestamp":
                    raw.get(
                        "spot_timestamp"
                    ),

                # ------------------------------
                # LIVE INDICATORS
                # ------------------------------

                **live_snapshot,

                # ------------------------------
                # COMPLETED-CANDLE STRATEGY
                # ------------------------------

                **signal,

                # Compatibility fields consumed by paper_engine.
                "rsi": signal.get("rsi_v"),
                "ema9": signal.get("ema9"),
                "ema20": signal.get("ema20"),
                "signal_rsi": signal.get("rsi_v"),
                "signal_ema9": signal.get("ema9"),
                "signal_ema20": signal.get("ema20"),
                "signal_volume_ratio": signal.get("volume_ratio"),
                "completed_candles": build_completed_candles(df),
                "level_engine": level_engine,
                "support": level_engine.get("support"),
                "resistance": level_engine.get("resistance"),

                # ------------------------------
                # Explicit candle status
                # ------------------------------

                "signal_candle_type":
                    "COMPLETED",

                "signal_candle_time":
                    closed_candle_time,

                "live_candle_time":
                    live_snapshot.get(
                        "live_candle_time"
                    ),

                # ------------------------------
                # Backend status
                # ------------------------------

                "engine_status":
                    "RUNNING",

                "calculated_at":
                    now_ist().isoformat(),

                "data_timestamp":
                    raw.get(
                        "worker_timestamp"
                    ),

                # ------------------------------
                # Raw source status
                # ------------------------------

                "websocket_connected":
                    raw.get(
                        "websocket_connected",
                        False,
                    ),

                "future_quote":
                    raw.get(
                        "future_quote"
                    ),

                "future_live_candle":
                    raw.get(
                        "future_live_candle"
                    ),

            }

            atomic_write_json(SIGNAL_FILE, payload)
            atomic_write_json(LEGACY_SIGNAL_FILE, payload)

        except Exception as exc:

            logging.exception(
                "Indicator engine error: %s",
                exc,
            )

        time.sleep(0.5)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    start_indicator_engine()
