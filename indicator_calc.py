# indicator_calc.py
# ============================================================
# NIFTY TECHNICAL INDICATOR PROCESSOR - ARCHITECTURE V2
# ============================================================
#
# data_worker.py
#       |
#       v
# data_raw.json
#       |
#       v
# indicator_calc.py
#       |
#       v
# processed_indicators.json
#
# IMPORTANT:
#   This file is ONLY a technical/data processor.
#   It MUST NOT decide CALL/PUT, BUY/SELL, entry or exit.
#   Strategy decisions belong exclusively to paper_engine.py.
#
# Preserved technical processing:
#   - 5-minute completed/forming candle separation
#   - LIVE spot price
#   - LIVE RSI / EMA9 / EMA20
#   - completed-candle RSI / EMA9 / EMA20
#   - NIFTY futures volume alignment
#   - LIVE futures 5-minute volume
#   - volume average and volume ratio
#   - Day High / Day Low
#   - Previous Day High / Low
#   - Morning Box High / Low (09:15-10:00)
#   - psychological levels every 100 points
#   - nearest support / resistance
#   - major-level candidates for rejection/breakout processing
#   - candle range / body / upper wick / lower wick
#   - wick-to-body ratios
#   - candle-size status (12-25 points)
#   - opposite-wick information (5% body rule as DATA, not decision)
#   - runway distances to Day High / Day Low
#   - completed-candle context
#   - live/forming-candle context
#
# NO strategy signal is generated here.
# NO strategy_signal.json is written.
# ============================================================

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ============================================================
# LOGGING / CONSTANTS
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

IST = timezone(timedelta(hours=5, minutes=30))

RAW_FILE = "data_raw.json"
OUTPUT_FILE = "processed_indicators.json"

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 20
VOLUME_AVG_PERIOD = 20
VOLUME_PASS_RATIO = 1.20
CANDLE_MIN = 12.0
CANDLE_MAX = 25.0
RUNWAY_MIN = 15.0
WICK_BODY_MAX = 0.05
PSYCHOLOGICAL_STEP = 100

PUBLISH_INTERVAL_SEC = 0.50
WAIT_INTERVAL_SEC = 0.50
LOG_INTERVAL_SEC = 30.0


# ============================================================
# GENERIC HELPERS
# ============================================================

def now_ist() -> datetime:
    return datetime.now(IST)


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy/non-finite values into JSON-safe values."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (float, int)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(json_safe(payload), f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def load_raw() -> Optional[Dict[str, Any]]:
    try:
        with open(RAW_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def normalise_timestamp_series(series: pd.Series) -> pd.Series:
    """Parse timestamps and normalize them to IST."""
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    try:
        return dt.dt.tz_convert(IST)
    except Exception:
        # Defensive fallback for unusual pandas input.
        try:
            naive = pd.to_datetime(series, errors="coerce")
            if getattr(naive.dt, "tz", None) is None:
                return naive.dt.tz_localize(IST)
            return naive.dt.tz_convert(IST)
        except Exception:
            return pd.Series(pd.NaT, index=series.index)


def to_float_list(values: pd.Series) -> List[float]:
    return [float(x) for x in pd.to_numeric(values, errors="coerce").dropna().tolist()]


# ============================================================
# RSI / EMA
# ============================================================

def calculate_tv_rsi(series: pd.Series, period: int = RSI_PERIOD) -> float:
    """TradingView-style Wilder/RMA RSI approximation used by the old engine."""
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if len(values) < period + 1:
        return 50.0

    delta = values.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

    # Explicit handling of no-loss/no-gain edge cases.
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0 and last_gain == 0:
        return 50.0
    if last_loss == 0:
        return 100.0

    rs = last_gain / last_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def ema(series: pd.Series, span: int) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if values.empty:
        return 0.0
    return float(values.ewm(span=span, adjust=False).mean().iloc[-1])


# ============================================================
# CANDLE DATAFRAME
# ============================================================

def build_candle_dataframe(candles: Any) -> pd.DataFrame:
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()

    rows: List[List[Any]] = []
    for row in candles:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            rows.append(list(row[:6]))
        elif isinstance(row, dict):
            rows.append([
                row.get("date", row.get("datetime", row.get("timestamp"))),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume", 0),
            ])

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume"],
    )

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    df = df.dropna(subset=["datetime", "open", "high", "low", "close"]).copy()
    df["datetime"] = df["datetime"].dt.tz_convert(IST)

    df["volume"] = df["volume"].fillna(0.0)
    df = (
        df.sort_values("datetime")
        .drop_duplicates(subset=["datetime"], keep="last")
        .reset_index(drop=True)
    )
    return df


def merge_futures_volume(
    spot_df: pd.DataFrame,
    futures_candles: Any,
) -> Tuple[pd.DataFrame, int]:
    """
    Align NIFTY futures candle volume with spot candle timestamps.
    Spot OHLC remains the price source.
    """
    out = spot_df.copy()
    out["futures_volume"] = 0.0

    fut = build_candle_dataframe(futures_candles)
    if fut.empty or out.empty:
        return out, 0

    fmap: Dict[pd.Timestamp, float] = {}
    for _, row in fut.iterrows():
        key = pd.Timestamp(row["datetime"]).floor("min")
        fmap[key] = float(row["volume"])

    matched = 0
    values: List[float] = []
    for _, row in out.iterrows():
        key = pd.Timestamp(row["datetime"]).floor("min")
        if key in fmap:
            values.append(fmap[key])
            matched += 1
        else:
            values.append(float(row["volume"]) if pd.notna(row["volume"]) else 0.0)

    out["futures_volume"] = values
    return out, matched


# ============================================================
# COMPLETED / FORMING CANDLE SPLIT
# ============================================================

def split_completed_and_forming(
    df: pd.DataFrame,
    now: datetime,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Angel 5-min candle timestamps are treated as candle START timestamps."""
    if df.empty:
        return df.copy(), df.copy()

    work = df.copy()
    work["datetime_ist"] = normalise_timestamp_series(work["datetime"])
    cutoff = pd.Timestamp(now.replace(second=0, microsecond=0))

    completed_mask = work["datetime_ist"] + pd.Timedelta(minutes=5) <= cutoff
    completed = work.loc[completed_mask].copy().reset_index(drop=True)
    forming = work.loc[~completed_mask].copy().reset_index(drop=True)
    return completed, forming


def build_live_dataframe(
    completed_df: pd.DataFrame,
    forming_df: pd.DataFrame,
    live_spot: float,
    now: datetime,
) -> pd.DataFrame:
    """Append a synthetic live candle for LIVE indicators only."""
    if completed_df.empty:
        return pd.DataFrame()

    last = completed_df.iloc[-1]
    bucket_start = now.replace(
        minute=(now.minute // 5) * 5,
        second=0,
        microsecond=0,
    )

    current = None
    if not forming_df.empty:
        same_bucket = forming_df[
            forming_df["datetime_ist"] == pd.Timestamp(bucket_start)
        ]
        if not same_bucket.empty:
            current = same_bucket.iloc[-1]

    if current is not None:
        live_open = float(current["open"])
        live_high = max(float(current["high"]), live_spot)
        live_low = min(float(current["low"]), live_spot)
    else:
        live_open = float(last["close"])
        live_high = max(live_open, live_spot)
        live_low = min(live_open, live_spot)

    live_row = {
        "date": bucket_start.isoformat(),
        "datetime": pd.Timestamp(bucket_start),
        "datetime_ist": pd.Timestamp(bucket_start),
        "open": live_open,
        "high": live_high,
        "low": live_low,
        "close": float(live_spot),
        "volume": 0.0,
        "futures_volume": 0.0,
    }

    return pd.concat([completed_df.copy(), pd.DataFrame([live_row])], ignore_index=True)


# ============================================================
# DAY / PREVIOUS DAY / MORNING BOX
# ============================================================

def _date_series(df: pd.DataFrame) -> pd.Series:
    return normalise_timestamp_series(df["datetime"]).dt.date


def calculate_session_levels(
    df: pd.DataFrame,
    spot: float,
    live_day_high: Optional[float],
    live_day_low: Optional[float],
    now: datetime,
) -> Dict[str, Any]:
    """Calculate structural price levels only; no trade decision."""
    levels: List[Dict[str, Any]] = []
    today = now.date()

    def add(name: str, value: Optional[float], source: str, strength: int) -> None:
        value = safe_float(value)
        if value is not None:
            levels.append({
                "name": name,
                "level": round(value, 2),
                "source": source,
                "strength": strength,
            })

    # Live day H/L from worker.
    day_high = safe_float(live_day_high)
    day_low = safe_float(live_day_low)
    if day_high is not None:
        day_high = max(day_high, spot)
    else:
        day_high = spot
    if day_low is not None:
        day_low = min(day_low, spot)
    else:
        day_low = spot

    add("Day High", day_high, "DAY", 5)
    add("Day Low", day_low, "DAY", 5)

    dates = _date_series(df)
    prior_dates = sorted({d for d in dates if d < today})
    previous_day_high = None
    previous_day_low = None
    if prior_dates:
        prev_day = df[dates == prior_dates[-1]]
        if not prev_day.empty:
            previous_day_high = float(prev_day["high"].max())
            previous_day_low = float(prev_day["low"].min())
            add("Previous Day High", previous_day_high, "PREVIOUS_DAY", 4)
            add("Previous Day Low", previous_day_low, "PREVIOUS_DAY", 4)

    # Morning Box = first 45 minutes: 09:15 inclusive to 10:00 exclusive.
    morning_high = None
    morning_low = None
    today_df = df[dates == today].copy()
    if not today_df.empty:
        local_dt = normalise_timestamp_series(today_df["datetime"])
        mins = local_dt.dt.hour * 60 + local_dt.dt.minute
        morning = today_df[(mins >= 9 * 60 + 15) & (mins < 10 * 60)]
        if not morning.empty:
            morning_high = float(morning["high"].max())
            morning_low = float(morning["low"].min())
            add("Morning Box High", morning_high, "MORNING_BOX", 4)
            add("Morning Box Low", morning_low, "MORNING_BOX", 4)

    # Psychological levels: 100-point spacing as required by the architecture.
    base = math.floor(spot / PSYCHOLOGICAL_STEP) * PSYCHOLOGICAL_STEP
    for level in range(
        int(base - 200),
        int(base + 301),
        PSYCHOLOGICAL_STEP,
    ):
        add(
            f"Psychological {level}",
            float(level),
            "PSYCHOLOGICAL_100",
            3,
        )

    # De-duplicate levels at same price while retaining strongest source.
    unique: Dict[float, Dict[str, Any]] = {}
    for item in levels:
        key = round(float(item["level"]), 2)
        if key not in unique or item["strength"] > unique[key]["strength"]:
            unique[key] = item

    ordered = sorted(unique.values(), key=lambda x: x["level"])
    supports = sorted(
        [x for x in ordered if x["level"] < spot],
        key=lambda x: (spot - x["level"], -x["strength"]),
    )
    resistances = sorted(
        [x for x in ordered if x["level"] > spot],
        key=lambda x: (x["level"] - spot, -x["strength"]),
    )

    nearest_support = supports[0] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    # Major levels are exposed as DATA for paper_engine.
    major_levels = sorted(
        [x for x in ordered if x["source"] in {"DAY", "PREVIOUS_DAY", "MORNING_BOX"}],
        key=lambda x: (abs(x["level"] - spot), -x["strength"]),
    )

    return {
        "levels": ordered,
        "major_levels": major_levels,
        "supports": supports,
        "resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "day_high": day_high,
        "day_low": day_low,
        "previous_day_high": previous_day_high,
        "previous_day_low": previous_day_low,
        "morning_box_high": morning_high,
        "morning_box_low": morning_low,
        "psychological_step": PSYCHOLOGICAL_STEP,
    }


# ============================================================
# CANDLE STRUCTURE
# ============================================================

def candle_structure(row: Optional[pd.Series]) -> Dict[str, Any]:
    if row is None:
        return {
            "time": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "range": None,
            "body": None,
            "upper_wick": None,
            "lower_wick": None,
            "body_ratio": None,
            "upper_wick_body_ratio": None,
            "lower_wick_body_ratio": None,
            "candle_size_valid": False,
            "opposite_wick_5pct_for_bull": False,
            "opposite_wick_5pct_for_bear": False,
            "bullish": False,
            "bearish": False,
        }

    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])

    rng = max(0.0, h - l)
    body = abs(c - o)
    safe_body = max(body, 0.01)
    upper = max(0.0, h - max(o, c))
    lower = max(0.0, min(o, c) - l)

    return {
        "time": str(row["date"]) if "date" in row else pd.Timestamp(row["datetime"]).isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "range": round(rng, 4),
        "body": round(body, 4),
        "upper_wick": round(upper, 4),
        "lower_wick": round(lower, 4),
        "body_ratio": round(body / max(rng, 0.01), 4),
        "upper_wick_body_ratio": round(upper / safe_body, 4),
        "lower_wick_body_ratio": round(lower / safe_body, 4),
        "candle_size_valid": bool(CANDLE_MIN <= rng <= CANDLE_MAX),
        "opposite_wick_5pct_for_bull": bool(upper <= safe_body * WICK_BODY_MAX),
        "opposite_wick_5pct_for_bear": bool(lower <= safe_body * WICK_BODY_MAX),
        "bullish": bool(c > o),
        "bearish": bool(c < o),
    }


def build_recent_candles(df: pd.DataFrame, count: int = 30) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    recent = df.tail(count)
    result: List[Dict[str, Any]] = []
    for _, row in recent.iterrows():
        item = candle_structure(row)
        item["volume"] = float(row.get("volume", 0.0))
        item["futures_volume"] = float(row.get("futures_volume", 0.0))
        item["datetime"] = pd.Timestamp(row["datetime"]).isoformat()
        result.append(item)
    return result


# ============================================================
# VOLUME PROCESSING
# ============================================================

def calculate_volume_metrics(
    completed_df: pd.DataFrame,
    live_futures_volume: Any,
) -> Dict[str, Any]:
    hist = pd.to_numeric(
        completed_df.get("futures_volume", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0.0)

    nonzero = hist[hist > 0]
    historical_avg = (
        float(nonzero.tail(VOLUME_AVG_PERIOD).mean())
        if not nonzero.empty
        else 0.0
    )

    # Last completed candle volume and average of prior candles only.
    signal_volume = float(hist.iloc[-1]) if not hist.empty else 0.0
    prior_window = hist.iloc[-(VOLUME_AVG_PERIOD + 1):-1]
    prior_nonzero = prior_window[prior_window > 0]
    signal_avg = (
        float(prior_nonzero.tail(VOLUME_AVG_PERIOD).mean())
        if not prior_nonzero.empty
        else 0.0
    )

    signal_ratio = (
        round(signal_volume / signal_avg, 4)
        if signal_avg > 0
        else 0.0
    )

    live_volume = safe_float(live_futures_volume)
    live_ratio = (
        round(live_volume / historical_avg, 4)
        if live_volume is not None and historical_avg > 0
        else 0.0
    )

    return {
        "source": "NIFTY_FUTURES",
        "live_futures_volume_5m": live_volume,
        "historical_average_volume": historical_avg,
        "completed_candle_volume": signal_volume,
        "completed_candle_average_prior_20": signal_avg,
        "completed_candle_ratio": signal_ratio,
        "live_volume_ratio": live_ratio,
        "volume_threshold_ratio": VOLUME_PASS_RATIO,
        "completed_volume_status": "PASS" if signal_ratio >= VOLUME_PASS_RATIO else "FAIL",
        "live_volume_status": "PASS" if live_ratio >= VOLUME_PASS_RATIO else "FAIL",
    }


# ============================================================
# RUNWAY / DISTANCE PROCESSING
# ============================================================

def calculate_distances(spot: float, day_high: float, day_low: float) -> Dict[str, Any]:
    upside = max(0.0, day_high - spot)
    downside = max(0.0, spot - day_low)

    return {
        "to_day_high": round(upside, 2),
        "to_day_low": round(downside, 2),
        "ce_runway": round(upside, 2),
        "pe_runway": round(downside, 2),
        "runway_min_points": RUNWAY_MIN,
        "ce_runway_status": "PASS" if upside >= RUNWAY_MIN else "FAIL",
        "pe_runway_status": "PASS" if downside >= RUNWAY_MIN else "FAIL",
    }


# ============================================================
# MAIN CALCULATION
# ============================================================

def calculate_indicators(raw: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    spot = safe_float(raw.get("live_spot"))
    if spot is None:
        # Compatibility with alternate worker shape.
        direct = raw.get("direct") or {}
        spot = safe_float(direct.get("spot"))
    if spot is None:
        return None

    candles = raw.get("candles") or []
    futures_candles = raw.get("futures_candles") or []

    df = build_candle_dataframe(candles)
    if df.empty:
        return None

    df, volume_matches = merge_futures_volume(df, futures_candles)
    completed_df, forming_df = split_completed_and_forming(df, now)

    if completed_df.empty:
        return None

    live_df = build_live_dataframe(completed_df, forming_df, spot, now)

    # --------------------------------------------------------
    # LIVE indicators: include current forming candle.
    # --------------------------------------------------------
    live_rsi = calculate_tv_rsi(live_df["close"], RSI_PERIOD) if not live_df.empty else 50.0
    live_ema9 = ema(live_df["close"], EMA_FAST) if not live_df.empty else 0.0
    live_ema20 = ema(live_df["close"], EMA_SLOW) if not live_df.empty else 0.0

    # --------------------------------------------------------
    # COMPLETED indicators: NEVER include forming candle.
    # --------------------------------------------------------
    closed_rsi = calculate_tv_rsi(completed_df["close"], RSI_PERIOD)
    closed_ema9 = ema(completed_df["close"], EMA_FAST)
    closed_ema20 = ema(completed_df["close"], EMA_SLOW)

    last_closed = completed_df.iloc[-1]
    closed_candle = candle_structure(last_closed)
    forming_candle = candle_structure(forming_df.iloc[-1]) if not forming_df.empty else None

    # --------------------------------------------------------
    # Day high / low. Worker is the primary live source.
    # --------------------------------------------------------
    worker_day_high = safe_float(raw.get("live_day_high"))
    worker_day_low = safe_float(raw.get("live_day_low"))

    if worker_day_high is None:
        today_mask = _date_series(df) == now.date()
        today_df = df[today_mask]
        worker_day_high = float(today_df["high"].max()) if not today_df.empty else spot
    if worker_day_low is None:
        today_mask = _date_series(df) == now.date()
        today_df = df[today_mask]
        worker_day_low = float(today_df["low"].min()) if not today_df.empty else spot

    intraday_high = max(worker_day_high, spot)
    intraday_low = min(worker_day_low, spot)

    # --------------------------------------------------------
    # Levels.
    # --------------------------------------------------------
    levels = calculate_session_levels(
        df=df,
        spot=spot,
        live_day_high=intraday_high,
        live_day_low=intraday_low,
        now=now,
    )

    # --------------------------------------------------------
    # Volume.
    # --------------------------------------------------------
    volume = calculate_volume_metrics(
        completed_df=completed_df,
        live_futures_volume=raw.get("live_futures_volume_5m"),
    )

    distances = calculate_distances(
        spot=spot,
        day_high=float(levels["day_high"]),
        day_low=float(levels["day_low"]),
    )

    # --------------------------------------------------------
    # EMA relationships / market context DATA only.
    # --------------------------------------------------------
    ema_context = {
        "live_ema9_above_ema20": bool(live_ema9 > live_ema20),
        "closed_ema9_above_ema20": bool(closed_ema9 > closed_ema20),
        "live_spot_above_ema9": bool(spot > live_ema9),
        "live_spot_above_ema20": bool(spot > live_ema20),
        "closed_close_above_ema9": bool(float(last_closed["close"]) > closed_ema9),
        "closed_close_above_ema20": bool(float(last_closed["close"]) > closed_ema20),
        "live_ema9_distance": round(spot - live_ema9, 2),
        "live_ema20_distance": round(spot - live_ema20, 2),
        "closed_ema9_distance": round(float(last_closed["close"]) - closed_ema9, 2),
        "closed_ema20_distance": round(float(last_closed["close"]) - closed_ema20, 2),
    }

    # --------------------------------------------------------
    # Level distances. Paper engine can use these to identify
    # rejection/breakout candidates without indicator deciding.
    # --------------------------------------------------------
    def level_distance(level_obj: Optional[Dict[str, Any]]) -> Optional[float]:
        if not level_obj:
            return None
        return round(abs(float(level_obj["level"]) - spot), 2)

    nearest_support_distance = level_distance(levels["nearest_support"])
    nearest_resistance_distance = level_distance(levels["nearest_resistance"])

    # The actual breakout reference is DATA: nearest structural level in
    # the direction of movement. No breakout decision is made here.
    breakout_candidates = {
        "upside": [
            x for x in levels["resistances"]
            if x["source"] in {"DAY", "PREVIOUS_DAY", "MORNING_BOX", "PSYCHOLOGICAL_100"}
        ][:5],
        "downside": [
            x for x in levels["supports"]
            if x["source"] in {"DAY", "PREVIOUS_DAY", "MORNING_BOX", "PSYCHOLOGICAL_100"}
        ][:5],
    }

    # --------------------------------------------------------
    # Full processed payload.
    # --------------------------------------------------------
    payload: Dict[str, Any] = {
        "schema_version": 2,
        "processor": "indicator_calc",
        "processor_role": "TECHNICAL_DATA_ONLY",
        "strategy_decision": False,
        "market_status": raw.get("market_status", "UNKNOWN"),
        "worker_status": raw.get("worker_status", "UNKNOWN"),
        "calculated_at_ist": now.isoformat(),
        "source_last_update": raw.get("last_update_ist", raw.get("last_update")),

        # Live market data.
        "live_spot": round(spot, 2),
        "spot_timestamp": raw.get("spot_timestamp"),
        "live_day_high": round(intraday_high, 2),
        "live_day_low": round(intraday_low, 2),

        # LIVE indicators.
        "live": {
            "rsi": round(live_rsi, 2),
            "ema9": round(live_ema9, 2),
            "ema20": round(live_ema20, 2),
            "candle": forming_candle,
            "forming_candle_present": bool(not forming_df.empty),
        },

        # COMPLETED candle indicators used by downstream strategy.
        "completed": {
            "candle_time": closed_candle["time"],
            "rsi": round(closed_rsi, 2),
            "ema9": round(closed_ema9, 2),
            "ema20": round(closed_ema20, 2),
            "candle": closed_candle,
            "is_confirmable_candle": True,
        },

        # Same values in explicit fields for easy paper_engine/dashboard access.
        "rsi_live": round(live_rsi, 2),
        "ema9_live": round(live_ema9, 2),
        "ema20_live": round(live_ema20, 2),
        "rsi_closed": round(closed_rsi, 2),
        "ema9_closed": round(closed_ema9, 2),
        "ema20_closed": round(closed_ema20, 2),

        "ema_context": ema_context,
        "volume": volume,
        "levels": levels["levels"],
        "major_levels": levels["major_levels"],
        "supports": levels["supports"],
        "resistances": levels["resistances"],
        "nearest_support": levels["nearest_support"],
        "nearest_resistance": levels["nearest_resistance"],
        "nearest_support_distance": nearest_support_distance,
        "nearest_resistance_distance": nearest_resistance_distance,
        "day_high": levels["day_high"],
        "day_low": levels["day_low"],
        "previous_day_high": levels["previous_day_high"],
        "previous_day_low": levels["previous_day_low"],
        "morning_box_high": levels["morning_box_high"],
        "morning_box_low": levels["morning_box_low"],
        "psychological_step": PSYCHOLOGICAL_STEP,
        "breakout_candidates": breakout_candidates,
        "distances": distances,

        # Rule thresholds are exposed as DATA so paper_engine does not need
        # to duplicate hidden constants.
        "thresholds": {
            "rsi_period": RSI_PERIOD,
            "ema_fast": EMA_FAST,
            "ema_slow": EMA_SLOW,
            "volume_avg_period": VOLUME_AVG_PERIOD,
            "volume_pass_ratio": VOLUME_PASS_RATIO,
            "candle_range_min": CANDLE_MIN,
            "candle_range_max": CANDLE_MAX,
            "runway_min_points": RUNWAY_MIN,
            "wick_body_max_ratio": WICK_BODY_MAX,
            "psychological_step": PSYCHOLOGICAL_STEP,
        },

        # Data quality / timing.
        "completed_candle_count": int(len(completed_df)),
        "forming_candle_count": int(len(forming_df)),
        "volume_merge_matches": int(volume_matches),
        "latest_completed_candle": closed_candle,
        "recent_completed_candles": build_recent_candles(completed_df, 30),
        "worker_websocket_connected": raw.get("websocket_connected"),
        "candle_last_success": raw.get("candle_last_success"),
        "candle_retry_delay": raw.get("candle_retry_delay"),
        "futures_candle_last_success": raw.get("futures_candle_last_success"),
        "futures_candle_retry_delay": raw.get("futures_candle_retry_delay"),
    }

    # Compatibility/raw passthrough useful to dashboard/paper engine,
    # without making a strategy decision.
    payload["futures_contract"] = raw.get("futures_contract")
    payload["futures_tick"] = raw.get("futures_tick")
    payload["live_futures_volume_5m"] = raw.get("live_futures_volume_5m")

    # --------------------------------------------------------
    # DOWNSTREAM FIELD COMPATIBILITY
    # --------------------------------------------------------
    # These are aliases of already-calculated technical data only.
    # They do NOT create any strategy decision.
    payload["rsi"] = round(live_rsi, 2)
    payload["ema9"] = round(live_ema9, 2)
    payload["ema20"] = round(live_ema20, 2)
    payload["signal_rsi"] = round(closed_rsi, 2)
    payload["signal_ema9"] = round(closed_ema9, 2)
    payload["signal_ema20"] = round(closed_ema20, 2)
    payload["intraday_high"] = round(intraday_high, 2)
    payload["intraday_low"] = round(intraday_low, 2)

    payload["signal_volume"] = volume.get("completed_candle_volume", 0.0)
    payload["signal_volume_avg"] = volume.get("completed_candle_average_prior_20", 0.0)
    payload["signal_volume_ratio"] = volume.get("completed_candle_ratio", 0.0)
    payload["live_volume"] = volume.get("live_futures_volume_5m")
    payload["live_volume_avg"] = volume.get("historical_average_volume", 0.0)
    payload["live_volume_ratio"] = volume.get("live_volume_ratio", 0.0)
    payload["signal_vol_status"] = volume.get("completed_volume_status")
    payload["signal_rsi_status"] = "AVAILABLE" if closed_rsi is not None else "UNAVAILABLE"
    payload["signal_ema_status"] = "AVAILABLE" if closed_ema9 is not None and closed_ema20 is not None else "UNAVAILABLE"

    # Paper engine expects the latest completed candles as a list.
    payload["completed_candles"] = payload["recent_completed_candles"]

    # Paper engine/dashboard compatibility: expose the same structural
    # level object already calculated above, without adding trade logic.
    payload["level_engine"] = levels

    # Direction-neutral runway data. CE/PE are kept separate so no
    # directional choice is made by this processor.
    payload["runway_ce"] = distances.get("ce_runway")
    payload["runway_pe"] = distances.get("pe_runway")
    payload["runway_status_ce"] = distances.get("ce_runway_status")
    payload["runway_status_pe"] = distances.get("pe_runway_status")

    return json_safe(payload)


# ============================================================
# ENGINE LOOP
# ============================================================

def start_indicator_engine() -> None:
    logging.info(
        "🟢 indicator_calc started | TECHNICAL DATA ONLY | "
        "No CALL/PUT | No BUY/SELL | No entry/exit"
    )

    last_log_time = 0.0
    last_candle_time = None

    while True:
        raw = load_raw()
        if not raw:
            time.sleep(WAIT_INTERVAL_SEC)
            continue

        try:
            now = now_ist()
            processed = calculate_indicators(raw, now)

            if processed is None:
                time.sleep(WAIT_INTERVAL_SEC)
                continue

            atomic_write_json(OUTPUT_FILE, processed)

            current_candle = (
                processed.get("completed", {}) or {}
            ).get("candle_time")
            current_time = time.time()

            if current_candle != last_candle_time or current_time - last_log_time >= LOG_INTERVAL_SEC:
                last_candle_time = current_candle
                last_log_time = current_time

                live = processed.get("live", {}) or {}
                closed = processed.get("completed", {}) or {}
                vol = processed.get("volume", {}) or {}

                logging.info(
                    "📊 INDICATORS | Spot=%.2f | LIVE RSI=%.2f EMA9=%.2f EMA20=%.2f | "
                    "CLOSED=%s RSI=%.2f EMA9=%.2f EMA20=%.2f | VOL=%.2fx | "
                    "DayH/L=%.2f/%.2f",
                    float(processed["live_spot"]),
                    float(live.get("rsi", 50.0)),
                    float(live.get("ema9", 0.0)),
                    float(live.get("ema20", 0.0)),
                    str(current_candle),
                    float(closed.get("rsi", 50.0)),
                    float(closed.get("ema9", 0.0)),
                    float(closed.get("ema20", 0.0)),
                    float(vol.get("completed_candle_ratio", 0.0)),
                    float(processed["live_day_high"]),
                    float(processed["live_day_low"]),
                )

        except Exception as exc:
            logging.exception("🔴 indicator_calc error: %s", exc)

        time.sleep(PUBLISH_INTERVAL_SEC)


if __name__ == "__main__":
    start_indicator_engine()
