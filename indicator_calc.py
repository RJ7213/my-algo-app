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
SIGNAL_FILE = "strategy_signal.json"


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
# LIVE INDICATOR SNAPSHOT
# ============================================================

def build_future_dataframe(future_candles):
    """Build a normalized 5-minute futures volume dataframe."""
    if not isinstance(future_candles, list):
        return pd.DataFrame(columns=["datetime", "volume"])

    rows = []
    for row in future_candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            dt = pd.to_datetime(row[0], errors="coerce", utc=True)
            volume = pd.to_numeric(row[5], errors="coerce")
            if pd.isna(dt) or pd.isna(volume):
                continue
            rows.append([dt.floor("5min"), float(volume)])
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=["datetime", "volume"])

    out = pd.DataFrame(rows, columns=["datetime", "volume"])
    out = (
        out.sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )
    return out


def volume_ratio_from_futures(
    spot_times,
    future_candles,
    fallback_volumes=None,
):
    """
    Calculate volume ratio using NIFTY FUTURES 5-minute volume.

    For every spot candle timestamp, the matching futures candle is
    used. The ratio is current completed/live candle volume divided by
    the mean of the previous 20 matching futures candles.
    """
    fdf = build_future_dataframe(future_candles)

    if fdf.empty:
        return 0.0, 0.0, 0.0, "NO_FUTURE_VOLUME"

    volume_map = dict(
        zip(fdf["datetime"], fdf["volume"])
    )

    normalized_times = []
    for value in spot_times:
        try:
            dt = pd.to_datetime(value, errors="coerce", utc=True)
            normalized_times.append(
                dt.floor("5min") if not pd.isna(dt) else None
            )
        except Exception:
            normalized_times.append(None)

    matched = []
    for i, dt in enumerate(normalized_times):
        value = volume_map.get(dt) if dt is not None else None
        if value is None and fallback_volumes is not None:
            try:
                value = float(fallback_volumes[i])
            except Exception:
                value = None
        matched.append(value)

    valid = [v for v in matched if v is not None and v >= 0]
    if len(matched) < 2:
        return 0.0, 0.0, 0.0, "INSUFFICIENT_FUTURE_VOLUME"

    current = matched[-1]
    if current is None:
        current = 0.0

    previous = [
        v for v in matched[-21:-1]
        if v is not None and v >= 0
    ]

    if not previous:
        return float(current), 0.0, 0.0, "NO_FUTURE_HISTORY"

    average = float(np.mean(previous))
    ratio = float(current / average) if average > 0 else 0.0

    return (
        float(current),
        average,
        round(ratio, 2),
        "FUTURES",
    )


def calculate_live_volume_ratio(
    df,
    future_candles,
    future_live_candle=None,
):
    """Live volume ratio. Current forming futures candle is included."""
    if df.empty:
        return 0.0, 0.0, 0.0, "NO_DATA"

    # Prefer the worker's explicitly live futures candle. This avoids
    # waiting for a REST refresh before the current candle volume moves.
    future_rows = list(future_candles or [])
    if future_live_candle:
        if future_rows:
            try:
                last_dt = pd.to_datetime(
                    future_rows[-1][0], errors="coerce", utc=True
                )
                live_dt = pd.to_datetime(
                    future_live_candle[0], errors="coerce", utc=True
                )
                if not pd.isna(last_dt) and not pd.isna(live_dt):
                    if last_dt.floor("5min") == live_dt.floor("5min"):
                        future_rows[-1] = list(future_live_candle)
                    elif live_dt.floor("5min") > last_dt.floor("5min"):
                        future_rows.append(list(future_live_candle))
            except Exception:
                pass
        else:
            future_rows.append(list(future_live_candle))

    times = list(df["datetime"])
    fallback = list(df["volume"])

    current, average, ratio, source = volume_ratio_from_futures(
        times,
        future_rows,
        fallback_volumes=fallback,
    )

    # If there is a live futures candle but the spot series does not yet
    # contain the same timestamp, use its live volume directly against the
    # last 20 completed futures candles.
    if future_live_candle:
        try:
            live_volume = float(future_live_candle[5])
            fdf = build_future_dataframe(future_rows)
            live_dt = pd.to_datetime(
                future_live_candle[0], errors="coerce", utc=True
            ).floor("5min")
            previous = fdf.loc[
                fdf["datetime"] < live_dt, "volume"
            ].tail(VOLUME_LOOKBACK)
            if not previous.empty:
                average = float(previous.mean())
                current = live_volume
                ratio = round(
                    current / average if average > 0 else 0.0,
                    2,
                )
                source = "FUTURES_LIVE"
        except Exception:
            pass

    return current, average, ratio, source


def calculate_live_snapshot(
    df,
    spot,
    day_high,
    day_low,
    future_candles=None,
    future_live_candle=None,
    signal_otype="NONE",
):
    """
    LIVE values for dashboard.

    These values are recalculated continuously from the forming candle,
    but they are NEVER allowed to create an entry.
    """

    if df.empty:
        return {}

    last = df.iloc[-1]

    rsi_live = (
        float(last["RSI"])
        if not pd.isna(last["RSI"])
        else 50.0
    )

    ema9_live = float(last["EMA9"])
    ema20_live = float(last["EMA20"])

    live_volume, live_volume_avg, live_volume_ratio, volume_source = (
        calculate_live_volume_ratio(
            df,
            future_candles or [],
            future_live_candle,
        )
    )

    otype = str(signal_otype or "NONE").upper()
    if otype == "CE":
        live_runway = max(0.0, float(day_high) - float(spot))
        live_rsi_status = "PASS" if rsi_live >= 60.0 else "FAIL"
        live_ema_status = "PASS" if float(spot) >= ema9_live else "FAIL"
    elif otype == "PE":
        live_runway = max(0.0, float(spot) - float(day_low))
        live_rsi_status = "PASS" if rsi_live <= 40.0 else "FAIL"
        live_ema_status = "PASS" if float(spot) <= ema9_live else "FAIL"
    else:
        live_runway = 0.0
        live_rsi_status = "FAIL"
        live_ema_status = "FAIL"

    live_volume_status = (
        "PASS"
        if live_volume_ratio >= MIN_VOLUME_RATIO
        else "FAIL"
    )
    live_runway_status = (
        "PASS"
        if live_runway >= MIN_RUNWAY
        else "FAIL"
    )

    return {
        # Existing dashboard-friendly keys are LIVE values.
        "live_rsi": round(rsi_live, 2),
        "live_ema9": round(ema9_live, 2),
        "live_ema20": round(ema20_live, 2),
        "live_volume": round(live_volume, 2),
        "live_volume_avg": round(live_volume_avg, 2),
        "live_volume_ratio": live_volume_ratio,
        "live_volume_val": f"{live_volume_ratio}x",
        "live_volume_status": live_volume_status,
        "live_runway": round(live_runway, 1),
        "live_runway_val": f"{live_runway:.1f} pts",
        "live_runway_status": live_runway_status,
        "live_rsi_status": live_rsi_status,
        "live_ema_status": live_ema_status,
        "live_volume_source": volume_source,
        "live_signal_direction": otype,
        "live_spot": round(float(spot), 2),
        "live_intraday_high": round(float(day_high), 2),
        "live_intraday_low": round(float(day_low), 2),
        "live_candle_time": str(last["datetime"]),
        "live_candle_open": float(last["open"]),
        "live_candle_high": float(last["high"]),
        "live_candle_low": float(last["low"]),
        "live_candle_close": float(last["close"]),
    }


# ============================================================
# COMPLETED-CANDLE STRATEGY
# ============================================================


def calculate_closed_candle_signal(
    df,
    spot,
    day_high,
    day_low,
    future_candles=None,
):
    """
    ALL entry logic is based on the LAST COMPLETED 5-minute candle (-2).

    Important: the completed candle's close is the signal reference. The
    newly forming candle's live spot is never used to create a new entry.
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
        row["RSI"] if not pd.isna(row["RSI"]) else 50.0
    )
    ema9 = float(row["EMA9"])
    ema20 = float(row["EMA20"])

    # The closed candle close is the ONLY price reference for entry logic.
    signal_spot = c_close

    psy_level = int(
        round(signal_spot / PSYCHOLOGICAL_STEP)
        * PSYCHOLOGICAL_STEP
    )

    is_candle_size_valid = (
        MIN_CANDLE_RANGE <= candle_range <= MAX_CANDLE_RANGE
    )

    upper_rejection = (
        abs(c_high - psy_level) <= PSY_REJECTION_DISTANCE
        and top_wick >= candle_range * 0.50
    )
    lower_rejection = (
        abs(c_low - psy_level) <= PSY_REJECTION_DISTANCE
        and bottom_wick >= candle_range * 0.50
    )
    is_rejection = upper_rejection or lower_rejection

    is_pullback = (
        not is_rejection
        and abs(signal_spot - ema9) <= 25.0
    )

    otype = "NONE"
    rsi_status = "FAIL"
    ema_status = "FAIL"
    setup_name = "NONE"
    candle_confirmed = False

    if is_rejection:
        if upper_rejection:
            otype = "PE"
        elif lower_rejection:
            otype = "CE"

        rsi_status = "PASS"
        ema_status = "PASS"
        setup_name = "Major Rejection"
        candle_confirmed = True

    elif is_pullback:
        otype = "CE" if signal_spot >= ema9 else "PE"

        rsi_status = (
            "PASS" if 45.0 <= rsi_v <= 55.0 else "FAIL"
        )
        ema_status = (
            "PASS" if abs(signal_spot - ema9) <= 15.0 else "FAIL"
        )
        setup_name = "Pullback"

        opposite_wick = (
            top_wick if otype == "CE" else bottom_wick
        )
        candle_confirmed = (
            opposite_wick <= candle_body * MAX_OPPOSITE_WICK_RATIO
        )

    else:
        if signal_spot > ema9:
            otype = "CE"
            rsi_status = "PASS" if rsi_v >= 60.0 else "FAIL"
        else:
            otype = "PE"
            rsi_status = "PASS" if rsi_v <= 40.0 else "FAIL"

        ema_status = "PASS"
        setup_name = "Breakout"

        opposite_wick = (
            top_wick if otype == "CE" else bottom_wick
        )
        candle_confirmed = (
            opposite_wick <= candle_body * MAX_OPPOSITE_WICK_RATIO
        )

    trade_type = f"{otype}_BUY" if otype != "NONE" else "NONE"

    # --------------------------------------------------------
    # VOLUME — NIFTY FUTURES, matched to the completed spot candle.
    # --------------------------------------------------------
    spot_times = list(df["datetime"].iloc[:-1])
    fallback_volumes = list(df["volume"].iloc[:-1])

    current_volume, vol_avg, vol_ratio, volume_source = (
        volume_ratio_from_futures(
            spot_times,
            future_candles or [],
            fallback_volumes=fallback_volumes,
        )
    )

    vol_status = (
        "PASS" if vol_ratio >= MIN_VOLUME_RATIO else "FAIL"
    )

    # --------------------------------------------------------
    # RUNWAY — live day high/low, but closed candle direction.
    # --------------------------------------------------------
    if otype == "CE":
        runway_distance = max(0.0, float(day_high) - signal_spot)
    elif otype == "PE":
        runway_distance = max(0.0, signal_spot - float(day_low))
    else:
        runway_distance = 0.0

    runway_status = (
        "PASS" if runway_distance >= MIN_RUNWAY else "FAIL"
    )

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
            f"LOCK | {setup_name} | Failed: "
            f"{', '.join(failed) if failed else 'SETUP'}"
        )

    elif not is_candle_size_valid:
        reason = (
            f"Size Lock | Candle range {candle_range:.1f} pts "
            f"(required {MIN_CANDLE_RANGE:.0f}-"
            f"{MAX_CANDLE_RANGE:.0f})"
        )

    elif not candle_confirmed:
        reason = (
            "Marubozu Lock | Opposite wick exceeds 5% of candle body"
        )

    else:
        reason = (
            f"SIGNAL READY | {setup_name} | {trade_type} | "
            f"Runway {runway_distance:.1f} pts"
        )

    option_strike = int(
        round(signal_spot / PSYCHOLOGICAL_STEP)
        * PSYCHOLOGICAL_STEP
    )

    if otype == "CE":
        next_wall = float(day_high)
    elif otype == "PE":
        next_wall = float(day_low)
    else:
        next_wall = float(signal_spot)

    return {
        "ready": True,
        "signal_triggered": bool(final_trigger),
        "trade_type": trade_type,
        "otype": otype,
        "option_strike": option_strike,
        "strategy_used": setup_name,
        "algo_reason": reason,

        # CLOSED-CANDLE values retained for paper trading/back-end audit.
        "signal_rsi": round(rsi_v, 2),
        "signal_ema9": round(ema9, 2),
        "signal_ema20": round(ema20, 2),
        "signal_volume": round(current_volume, 2),
        "signal_volume_avg": round(vol_avg, 2),
        "signal_volume_ratio": vol_ratio,
        "signal_volume_source": volume_source,
        "signal_runway": round(runway_distance, 1),

        # Backward-compatible fields used by paper_engine.
        "rsi_v": round(rsi_v, 2),
        "ema9": round(ema9, 2),
        "ema20": round(ema20, 2),
        "rsi_status": rsi_status,
        "ema_status": ema_status,
        "vol_status": vol_status,
        "vol_val": f"{vol_ratio}x",
        "volume_ratio": vol_ratio,
        "runway_status": runway_status,
        "runway_val": f"{runway_distance:.1f} pts",
        "run_df": runway_distance,
        "intraday_high": float(day_high),
        "intraday_low": float(day_low),
        "psy_level": psy_level,
        "next_w": next_wall,
        "c_open": c_open,
        "c_close": c_close,
        "c_low": c_low,
        "c_high": c_high,
        "candle_range": candle_range,
        "candle_body": candle_body,
        "top_wick": top_wick,
        "bottom_wick": bottom_wick,
        "candle_size_valid": bool(is_candle_size_valid),
        "candle_confirmed": bool(candle_confirmed),
        "candle_time": str(row["datetime"]),
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
                    "websocket_connected": raw.get("websocket_connected", False),
                    "data_timestamp": raw.get("worker_timestamp"),
                    "future_quote": raw.get("future_quote"),
                    "future_live_candle": raw.get("future_live_candle"),
                    "calculated_at": now_ist().isoformat(),
                }

                atomic_write_json(
                    SIGNAL_FILE,
                    payload,
                )

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

            # ----------------------------------------------------
            # CLOSED-CANDLE STRATEGY FIRST
            # ----------------------------------------------------
            # This decides the direction used by the live dashboard
            # statuses. It still cannot trigger until a new completed
            # candle is detected below.
            # ----------------------------------------------------

            live_idx, closed_idx = get_candle_status(df)

            closed_candle_time = str(
                df["datetime"].iloc[closed_idx]
            )

            signal = calculate_closed_candle_signal(
                df,
                spot,
                day_high,
                day_low,
                future_candles=raw.get("future_candles", []),
            )

            # ----------------------------------------------------
            # LIVE INDICATOR SNAPSHOT
            # ----------------------------------------------------
            # Same indicator engine, same output file. Dashboard reads
            # these live values; paper engine reads the signal fields.
            # ----------------------------------------------------

            live_snapshot = calculate_live_snapshot(
                df,
                spot,
                day_high,
                day_low,
                future_candles=raw.get("future_candles", []),
                future_live_candle=raw.get("future_live_candle"),
                signal_otype=signal.get("otype", "NONE"),
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

                # ------------------------------
                # DASHBOARD DISPLAY = LIVE INDICATORS
                # ------------------------------
                # Existing dashboard reads these legacy names. Keep
                # paper-engine/audit values under signal_* while these
                # aliases always represent the current forming candle.

                "rsi_v": live_snapshot.get("live_rsi", signal.get("rsi_v")),
                "ema9": live_snapshot.get("live_ema9", signal.get("ema9")),
                "ema20": live_snapshot.get("live_ema20", signal.get("ema20")),
                "rsi_status": live_snapshot.get("live_rsi_status", signal.get("rsi_status")),
                "ema_status": live_snapshot.get("live_ema_status", signal.get("ema_status")),
                "vol_status": live_snapshot.get("live_volume_status", signal.get("vol_status")),
                "vol_val": live_snapshot.get("live_volume_val", signal.get("vol_val")),
                "volume_ratio": live_snapshot.get("live_volume_ratio", signal.get("volume_ratio")),
                "runway_status": live_snapshot.get("live_runway_status", signal.get("runway_status")),
                "runway_val": live_snapshot.get("live_runway_val", signal.get("runway_val")),

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

            atomic_write_json(
                SIGNAL_FILE,
                payload,
            )

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
