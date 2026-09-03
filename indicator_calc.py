# indicator_calc.py
# ============================================================
# NIFTY TECHNICAL INDICATOR PROCESSOR - SOURCE OF TRUTH V3
# ============================================================
#
# SINGLE MARKET-DATA SOURCE:
#     data_worker.py -> data_raw.json
#
# indicator_calc.py ONLY transforms data_raw.json into technical
# indicator/level data. It does not fetch broker data and does not
# make CALL/PUT, BUY/SELL, entry or exit decisions.
#
# IMPORTANT SOURCE RULES:
#   - Spot / Day H/L / raw candles come from data_raw.json.
#   - Futures volume used for volume metrics comes ONLY from
#     futures data published in data_raw.json.
#   - RSI/EMA/candle/volume/levels are calculated ONCE here.
#   - paper_engine must consume this processed snapshot, not
#     recalculate indicators from another data source.
#   - Dashboard displays the same processed snapshot.
#
# NO strategy_signal.json is written here.
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


def json_safe(value: Any) -> Any:
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

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, int):
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
        json.dump(
            json_safe(payload),
            f,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    os.replace(tmp, path)


def load_raw() -> Optional[Dict[str, Any]]:
    try:
        with open(RAW_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ============================================================
# TIME NORMALIZATION
# ============================================================

def normalize_timestamp(value: Any) -> Optional[pd.Timestamp]:
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=True)

        if pd.isna(ts):
            return None

        return pd.Timestamp(ts).tz_convert(IST)

    except Exception:
        return None


def normalise_timestamp_series(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    return dt.dt.tz_convert(IST)


# ============================================================
# RSI / EMA
# ============================================================

def calculate_tv_rsi(
    series: pd.Series,
    period: int = RSI_PERIOD,
) -> float:
    values = (
        pd.to_numeric(series, errors="coerce")
        .dropna()
        .astype(float)
    )

    if len(values) < period + 1:
        return 50.0

    delta = values.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    alpha = 1.0 / period

    avg_gain = gain.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=alpha,
        adjust=False,
    ).mean()

    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])

    if last_loss == 0 and last_gain == 0:
        return 50.0

    if last_loss == 0:
        return 100.0

    rs = last_gain / last_loss

    return float(
        100.0 - (100.0 / (1.0 + rs))
    )


def ema(
    series: pd.Series,
    span: int,
) -> float:
    values = (
        pd.to_numeric(series, errors="coerce")
        .dropna()
        .astype(float)
    )

    if values.empty:
        return 0.0

    return float(
        values.ewm(
            span=span,
            adjust=False,
        ).mean().iloc[-1]
    )


# ============================================================
# CANDLE DATAFRAME
# ============================================================

def build_candle_dataframe(
    candles: Any,
) -> pd.DataFrame:

    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()

    rows: List[List[Any]] = []

    for row in candles:

        if isinstance(row, (list, tuple)) and len(row) >= 6:

            rows.append(
                list(row[:6])
            )

        elif isinstance(row, dict):

            rows.append(
                [
                    row.get(
                        "date",
                        row.get(
                            "datetime",
                            row.get("timestamp"),
                        ),
                    ),
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row.get("close"),
                    row.get("volume", 0),
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

    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        )

    df["datetime"] = pd.to_datetime(
        df["date"],
        errors="coerce",
        utc=True,
    )

    df = df.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    ).copy()

    if df.empty:
        return df

    df["datetime"] = (
        df["datetime"].dt.tz_convert(IST)
    )

    df["volume"] = (
        df["volume"].fillna(0.0)
    )

    df = (
        df.sort_values("datetime")
        .drop_duplicates(
            subset=["datetime"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return df


# ============================================================
# WORKER CANDLE MERGE
# ============================================================

def merge_local_candles(
    api_df: pd.DataFrame,
    local_candles: Any,
) -> pd.DataFrame:

    if api_df.empty and not local_candles:
        return api_df.copy()

    local_df = build_candle_dataframe(
        local_candles
    )

    if local_df.empty:
        return api_df.copy()

    if api_df.empty:
        return local_df.copy()

    base = (
        api_df
        .copy()
        .set_index("datetime")
    )

    local = (
        local_df
        .copy()
        .set_index("datetime")
    )

    base.update(local)

    missing = local.index.difference(
        base.index
    )

    if len(missing):
        base = pd.concat(
            [
                base,
                local.loc[missing],
            ],
            axis=0,
        )

    return (
        base.reset_index()
        .sort_values("datetime")
        .reset_index(drop=True)
    )


# ============================================================
# FUTURES VOLUME ALIGNMENT
# ============================================================

def extract_local_future_volume(
    raw: Dict[str, Any],
) -> List[Dict[str, Any]]:

    value = raw.get(
        "local_futures_volume_candles"
    )

    if isinstance(value, list):
        return value

    # Current worker also exposes future_live_candle.
    live = raw.get("future_live_candle")

    if isinstance(live, list) and len(live) >= 6:

        return [
            {
                "date": live[0],
                "volume": safe_float(
                    live[5],
                    0.0,
                ),
            }
        ]

    if isinstance(live, dict):

        return [
            {
                "date": live.get(
                    "date",
                    live.get("datetime"),
                ),
                "volume": safe_float(
                    live.get("volume"),
                    0.0,
                ),
            }
        ]

    return []


def merge_futures_volume(
    spot_df: pd.DataFrame,
    futures_candles: Any,
    local_futures_candles: Any = None,
) -> Tuple[pd.DataFrame, int]:

    out = spot_df.copy()

    if out.empty:
        out["futures_volume"] = 0.0
        return out, 0

    out["futures_volume"] = 0.0

    fut = build_candle_dataframe(
        futures_candles
    )

    fmap: Dict[pd.Timestamp, float] = {}

    if not fut.empty:

        for _, row in fut.iterrows():

            key = pd.Timestamp(
                row["datetime"]
            ).floor("min")

            fmap[key] = float(
                row["volume"]
            )

    if isinstance(
        local_futures_candles,
        list,
    ):

        for row in local_futures_candles:

            if not isinstance(row, dict):
                continue

            dt = normalize_timestamp(
                row.get(
                    "date",
                    row.get("datetime"),
                )
            )

            if dt is None:
                continue

            vol = safe_float(
                row.get("volume"),
                0.0,
            )

            fmap[dt.floor("min")] = float(
                vol or 0.0
            )

    matched = 0
    values: List[float] = []

    for _, row in out.iterrows():

        key = pd.Timestamp(
            row["datetime"]
        ).floor("min")

        if key in fmap:

            values.append(
                fmap[key]
            )

            matched += 1

        else:

            values.append(0.0)

    out["futures_volume"] = values

    return out, matched


# ============================================================
# COMPLETED / FORMING
# ============================================================

def split_completed_and_forming(
    df: pd.DataFrame,
    now: datetime,
) -> Tuple[pd.DataFrame, pd.DataFrame]:

    if df.empty:
        return (
            df.copy(),
            df.copy(),
        )

    work = df.copy()

    work["datetime_ist"] = (
        normalise_timestamp_series(
            work["datetime"]
        )
    )

    cutoff = pd.Timestamp(
        now.replace(
            second=0,
            microsecond=0,
        )
    )

    completed_mask = (
        work["datetime_ist"]
        + pd.Timedelta(minutes=5)
        <= cutoff
    )

    completed = (
        work.loc[completed_mask]
        .copy()
        .reset_index(drop=True)
    )

    forming = (
        work.loc[~completed_mask]
        .copy()
        .reset_index(drop=True)
    )

    return completed, forming


def build_live_dataframe(
    completed_df: pd.DataFrame,
    forming_df: pd.DataFrame,
    live_spot: float,
    now: datetime,
) -> pd.DataFrame:

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
            forming_df["datetime_ist"]
            == pd.Timestamp(bucket_start)
        ]

        if not same_bucket.empty:
            current = same_bucket.iloc[-1]

    if current is not None:

        live_open = float(
            current["open"]
        )

        live_high = max(
            float(current["high"]),
            live_spot,
        )

        live_low = min(
            float(current["low"]),
            live_spot,
        )

    else:

        live_open = float(
            last["close"]
        )

        live_high = max(
            live_open,
            live_spot,
        )

        live_low = min(
            live_open,
            live_spot,
        )

    live_row = {
        "date": bucket_start.isoformat(),
        "datetime": pd.Timestamp(
            bucket_start
        ),
        "datetime_ist": pd.Timestamp(
            bucket_start
        ),
        "open": live_open,
        "high": live_high,
        "low": live_low,
        "close": float(live_spot),
        "volume": 0.0,
        "futures_volume": 0.0,
    }

    return pd.concat(
        [
            completed_df.copy(),
            pd.DataFrame([live_row]),
        ],
        ignore_index=True,
    )


# ============================================================
# SESSION LEVELS
# ============================================================

def _date_series(
    df: pd.DataFrame,
) -> pd.Series:

    return (
        normalise_timestamp_series(
            df["datetime"]
        ).dt.date
    )


def calculate_session_levels(
    df: pd.DataFrame,
    spot: float,
    worker_day_high: Optional[float],
    worker_day_low: Optional[float],
    now: datetime,
) -> Dict[str, Any]:

    levels: List[Dict[str, Any]] = []

    today = now.date()

    def add(
        name: str,
        value: Optional[float],
        source: str,
        strength: int,
    ) -> None:

        value = safe_float(value)

        if value is not None:

            levels.append(
                {
                    "name": name,
                    "level": round(value, 2),
                    "source": source,
                    "strength": strength,
                }
            )

    # --------------------------------------------------------
    # DAY H/L
    #
    # IMPORTANT:
    # data_worker is authoritative.
    # Do NOT recalculate a replacement Day H/L here.
    # --------------------------------------------------------

    day_high = safe_float(
        worker_day_high
    )

    day_low = safe_float(
        worker_day_low
    )

    if day_high is None:
        day_high = spot

    if day_low is None:
        day_low = spot

    # Keep current spot inside displayed range without
    # inventing a different source.
    day_high = max(
        day_high,
        spot,
    )

    day_low = min(
        day_low,
        spot,
    )

    add(
        "Day High",
        day_high,
        "DAY",
        5,
    )

    add(
        "Day Low",
        day_low,
        "DAY",
        5,
    )

    # --------------------------------------------------------
    # PREVIOUS DAY
    # --------------------------------------------------------

    dates = _date_series(df)

    prior_dates = sorted(
        {
            d
            for d in dates
            if d < today
        }
    )

    previous_day_high = None
    previous_day_low = None

    if prior_dates:

        prev_day = df[
            dates == prior_dates[-1]
        ]

        if not prev_day.empty:

            previous_day_high = float(
                prev_day["high"].max()
            )

            previous_day_low = float(
                prev_day["low"].min()
            )

            add(
                "Previous Day High",
                previous_day_high,
                "PREVIOUS_DAY",
                4,
            )

            add(
                "Previous Day Low",
                previous_day_low,
                "PREVIOUS_DAY",
                4,
            )

    # --------------------------------------------------------
    # MORNING BOX
    # --------------------------------------------------------

    morning_high = None
    morning_low = None

    today_df = df[
        dates == today
    ].copy()

    if not today_df.empty:

        local_dt = normalise_timestamp_series(
            today_df["datetime"]
        )

        mins = (
            local_dt.dt.hour * 60
            + local_dt.dt.minute
        )

        morning = today_df[
            (mins >= 9 * 60 + 15)
            & (mins < 10 * 60)
        ]

        if not morning.empty:

            morning_high = float(
                morning["high"].max()
            )

            morning_low = float(
                morning["low"].min()
            )

            add(
                "Morning Box High",
                morning_high,
                "MORNING_BOX",
                4,
            )

            add(
                "Morning Box Low",
                morning_low,
                "MORNING_BOX",
                4,
            )

    # --------------------------------------------------------
    # PSYCHOLOGICAL LEVELS
    # --------------------------------------------------------

    base = (
        math.floor(
            spot / PSYCHOLOGICAL_STEP
        )
        * PSYCHOLOGICAL_STEP
    )

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

    # --------------------------------------------------------
    # DEDUPLICATE
    # --------------------------------------------------------

    unique: Dict[
        float,
        Dict[str, Any],
    ] = {}

    for item in levels:

        key = round(
            float(item["level"]),
            2,
        )

        if (
            key not in unique
            or item["strength"]
            > unique[key]["strength"]
        ):
            unique[key] = item

    ordered = sorted(
        unique.values(),
        key=lambda x: x["level"],
    )

    supports = sorted(
        [
            x for x in ordered
            if x["level"] < spot
        ],
        key=lambda x: (
            spot - x["level"],
            -x["strength"],
        ),
    )

    resistances = sorted(
        [
            x for x in ordered
            if x["level"] > spot
        ],
        key=lambda x: (
            x["level"] - spot,
            -x["strength"],
        ),
    )

    nearest_support = (
        supports[0]
        if supports
        else None
    )

    nearest_resistance = (
        resistances[0]
        if resistances
        else None
    )

    major_levels = sorted(
        [
            x for x in ordered
            if x["source"] in {
                "DAY",
                "PREVIOUS_DAY",
                "MORNING_BOX",
            }
        ],
        key=lambda x: (
            abs(x["level"] - spot),
            -x["strength"],
        ),
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

def candle_structure(
    row: Optional[pd.Series],
) -> Dict[str, Any]:

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

    rng = max(
        0.0,
        h - l,
    )

    body = abs(
        c - o
    )

    safe_body = max(
        body,
        0.01,
    )

    upper = max(
        0.0,
        h - max(o, c),
    )

    lower = max(
        0.0,
        min(o, c) - l,
    )

    return {
        "time": (
            str(row["date"])
            if "date" in row
            else pd.Timestamp(
                row["datetime"]
            ).isoformat()
        ),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "range": round(rng, 4),
        "body": round(body, 4),
        "upper_wick": round(upper, 4),
        "lower_wick": round(lower, 4),
        "body_ratio": round(
            body / max(rng, 0.01),
            4,
        ),
        "upper_wick_body_ratio": round(
            upper / safe_body,
            4,
        ),
        "lower_wick_body_ratio": round(
            lower / safe_body,
            4,
        ),
        "candle_size_valid": bool(
            CANDLE_MIN
            <= rng
            <= CANDLE_MAX
        ),
        "opposite_wick_5pct_for_bull": bool(
            upper
            <= safe_body
            * WICK_BODY_MAX
        ),
        "opposite_wick_5pct_for_bear": bool(
            lower
            <= safe_body
            * WICK_BODY_MAX
        ),
        "bullish": bool(c > o),
        "bearish": bool(c < o),
    }


def build_recent_candles(
    df: pd.DataFrame,
    count: int = 30,
) -> List[Dict[str, Any]]:

    if df.empty:
        return []

    result: List[Dict[str, Any]] = []

    for _, row in df.tail(count).iterrows():

        item = candle_structure(row)

        item["volume"] = float(
            row.get("volume", 0.0)
        )

        item["futures_volume"] = float(
            row.get(
                "futures_volume",
                0.0,
            )
        )

        item["datetime"] = pd.Timestamp(
            row["datetime"]
        ).isoformat()

        result.append(item)

    return result


# ============================================================
# VOLUME
# ============================================================

def calculate_volume_metrics(
    completed_df: pd.DataFrame,
    live_futures_volume: Any,
) -> Dict[str, Any]:

    hist = pd.to_numeric(
        completed_df.get(
            "futures_volume",
            pd.Series(dtype=float),
        ),
        errors="coerce",
    ).fillna(0.0)

    nonzero = hist[
        hist > 0
    ]

    historical_avg = (
        float(
            nonzero
            .tail(VOLUME_AVG_PERIOD)
            .mean()
        )
        if not nonzero.empty
        else 0.0
    )

    signal_volume = (
        float(hist.iloc[-1])
        if not hist.empty
        else 0.0
    )

    prior_window = hist.iloc[
        -(VOLUME_AVG_PERIOD + 1):-1
    ]

    prior_nonzero = prior_window[
        prior_window > 0
    ]

    signal_avg = (
        float(
            prior_nonzero
            .tail(VOLUME_AVG_PERIOD)
            .mean()
        )
        if not prior_nonzero.empty
        else 0.0
    )

    signal_ratio = (
        round(
            signal_volume / signal_avg,
            4,
        )
        if signal_avg > 0
        else 0.0
    )

    live_volume = safe_float(
        live_futures_volume
    )

    live_ratio = (
        round(
            live_volume / historical_avg,
            4,
        )
        if (
            live_volume is not None
            and historical_avg > 0
        )
        else 0.0
    )

    return {
        "source": "NIFTY_FUTURES_FROM_DATA_RAW",
        "live_futures_volume_5m": live_volume,
        "historical_average_volume": historical_avg,
        "completed_candle_volume": signal_volume,
        "completed_candle_average_prior_20": signal_avg,
        "completed_candle_ratio": signal_ratio,
        "live_volume_ratio": live_ratio,
        "volume_threshold_ratio": VOLUME_PASS_RATIO,
        "completed_volume_status": (
            "PASS"
            if signal_ratio >= VOLUME_PASS_RATIO
            else "FAIL"
        ),
        "live_volume_status": (
            "PASS"
            if live_ratio >= VOLUME_PASS_RATIO
            else "FAIL"
        ),
        "data_quality": (
            "OK"
            if historical_avg > 0
            else "NO_FUTURES_VOLUME_HISTORY"
        ),
    }


# ============================================================
# DISTANCES / RUNWAY
# ============================================================

def calculate_distances(
    spot: float,
    day_high: float,
    day_low: float,
) -> Dict[str, Any]:

    upside = max(
        0.0,
        day_high - spot,
    )

    downside = max(
        0.0,
        spot - day_low,
    )

    return {
        "to_day_high": round(
            upside,
            2,
        ),
        "to_day_low": round(
            downside,
            2,
        ),
        "ce_runway": round(
            upside,
            2,
        ),
        "pe_runway": round(
            downside,
            2,
        ),
        "runway_min_points": RUNWAY_MIN,
        "ce_runway_status": (
            "PASS"
            if upside >= RUNWAY_MIN
            else "FAIL"
        ),
        "pe_runway_status": (
            "PASS"
            if downside >= RUNWAY_MIN
            else "FAIL"
        ),
    }


# ============================================================
# MAIN
# ============================================================

def calculate_indicators(
    raw: Dict[str, Any],
    now: datetime,
) -> Optional[Dict[str, Any]]:

    # --------------------------------------------------------
    # RAW SPOT: data_worker is the only market-data source.
    # --------------------------------------------------------

    spot = safe_float(
        raw.get("live_spot")
    )

    if spot is None:
        return None

    # --------------------------------------------------------
    # RAW CANDLES.
    # Worker currently publishes "candles".
    # Optional local list is accepted if/when worker publishes it.
    # --------------------------------------------------------

    candles = raw.get(
        "candles"
    ) or []

    local_candles = raw.get(
        "local_5m_candles"
    ) or []

    futures_candles = raw.get(
        "futures_candles"
    ) or []

    local_futures_volume = (
        extract_local_future_volume(raw)
    )

    api_df = build_candle_dataframe(
        candles
    )

    df = merge_local_candles(
        api_df,
        local_candles,
    )

    if df.empty:
        return None

    # --------------------------------------------------------
    # FUTURES VOLUME MUST COME FROM DATA_RAW.
    # --------------------------------------------------------

    df, volume_matches = merge_futures_volume(
        df,
        futures_candles,
        local_futures_volume,
    )

    completed_df, forming_df = (
        split_completed_and_forming(
            df,
            now,
        )
    )

    if completed_df.empty:
        return None

    live_df = build_live_dataframe(
        completed_df,
        forming_df,
        spot,
        now,
    )

    # --------------------------------------------------------
    # LIVE INDICATORS
    # --------------------------------------------------------

    live_rsi = (
        calculate_tv_rsi(
            live_df["close"],
            RSI_PERIOD,
        )
        if not live_df.empty
        else 50.0
    )

    live_ema9 = (
        ema(
            live_df["close"],
            EMA_FAST,
        )
        if not live_df.empty
        else 0.0
    )

    live_ema20 = (
        ema(
            live_df["close"],
            EMA_SLOW,
        )
        if not live_df.empty
        else 0.0
    )

    # --------------------------------------------------------
    # COMPLETED-CANDLE INDICATORS
    # --------------------------------------------------------

    closed_rsi = calculate_tv_rsi(
        completed_df["close"],
        RSI_PERIOD,
    )

    closed_ema9 = ema(
        completed_df["close"],
        EMA_FAST,
    )

    closed_ema20 = ema(
        completed_df["close"],
        EMA_SLOW,
    )

    last_closed = completed_df.iloc[-1]

    closed_candle = candle_structure(
        last_closed
    )

    forming_candle = (
        candle_structure(
            forming_df.iloc[-1]
        )
        if not forming_df.empty
        else None
    )

    # --------------------------------------------------------
    # DAY H/L
    #
    # IMPORTANT:
    # worker's intraday_high/intraday_low are authoritative.
    # We do NOT use a separately calculated day H/L as a source.
    # --------------------------------------------------------

    worker_day_high = safe_float(
        raw.get("intraday_high")
    )

    worker_day_low = safe_float(
        raw.get("intraday_low")
    )

    # Compatibility only for a future worker schema; still raw.
    if worker_day_high is None:
        worker_day_high = safe_float(
            raw.get("live_day_high")
        )

    if worker_day_low is None:
        worker_day_low = safe_float(
            raw.get("live_day_low")
        )

    if worker_day_high is None:
        worker_day_high = spot

    if worker_day_low is None:
        worker_day_low = spot

    # Keep spot inside the raw worker range.
    intraday_high = max(
        worker_day_high,
        spot,
    )

    intraday_low = min(
        worker_day_low,
        spot,
    )

    # --------------------------------------------------------
    # LEVELS
    # --------------------------------------------------------

    levels = calculate_session_levels(
        df=df,
        spot=spot,
        worker_day_high=intraday_high,
        worker_day_low=intraday_low,
        now=now,
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    live_futures_volume = safe_float(
        raw.get(
            "live_futures_volume_5m"
        )
    )

    # Current worker does not publish this key yet, so the
    # live volume may legitimately be unavailable. Never fake it.
    volume = calculate_volume_metrics(
        completed_df,
        live_futures_volume,
    )

    # --------------------------------------------------------
    # RUNWAY
    # --------------------------------------------------------

    distances = calculate_distances(
        spot=spot,
        day_high=float(
            levels["day_high"]
        ),
        day_low=float(
            levels["day_low"]
        ),
    )

    # --------------------------------------------------------
    # EMA CONTEXT DATA ONLY
    # --------------------------------------------------------

    ema_context = {
        "live_ema9_above_ema20": bool(
            live_ema9 > live_ema20
        ),
        "closed_ema9_above_ema20": bool(
            closed_ema9 > closed_ema20
        ),
        "live_spot_above_ema9": bool(
            spot > live_ema9
        ),
        "live_spot_above_ema20": bool(
            spot > live_ema20
        ),
        "closed_close_above_ema9": bool(
            float(last_closed["close"])
            > closed_ema9
        ),
        "closed_close_above_ema20": bool(
            float(last_closed["close"])
            > closed_ema20
        ),
        "live_ema9_distance": round(
            spot - live_ema9,
            2,
        ),
        "live_ema20_distance": round(
            spot - live_ema20,
            2,
        ),
        "closed_ema9_distance": round(
            float(last_closed["close"])
            - closed_ema9,
            2,
        ),
        "closed_ema20_distance": round(
            float(last_closed["close"])
            - closed_ema20,
            2,
        ),
    }

    # --------------------------------------------------------
    # LEVEL DISTANCES
    # --------------------------------------------------------

    def level_distance(
        level_obj: Optional[Dict[str, Any]],
    ) -> Optional[float]:

        if not level_obj:
            return None

        return round(
            abs(
                float(level_obj["level"])
                - spot
            ),
            2,
        )

    nearest_support_distance = (
        level_distance(
            levels["nearest_support"]
        )
    )

    nearest_resistance_distance = (
        level_distance(
            levels["nearest_resistance"]
        )
    )

    breakout_candidates = {
        "upside": [
            x
            for x in levels["resistances"]
            if x["source"] in {
                "DAY",
                "PREVIOUS_DAY",
                "MORNING_BOX",
                "PSYCHOLOGICAL_100",
            }
        ][:5],
        "downside": [
            x
            for x in levels["supports"]
            if x["source"] in {
                "DAY",
                "PREVIOUS_DAY",
                "MORNING_BOX",
                "PSYCHOLOGICAL_100",
            }
        ][:5],
    }

    # ========================================================
    # PUBLISHED PROCESSED SNAPSHOT
    # ========================================================
    #
    # Canonical flat keys are included so paper_engine and
    # dashboard use exactly the same processed values.
    # Nested live/completed blocks remain available for context.
    # ========================================================

    payload: Dict[str, Any] = {

        "schema_version": 3,

        "processor": "indicator_calc",

        "processor_role": "TECHNICAL_DATA_ONLY",

        "strategy_decision": False,

        # ----------------------------------------------------
        # SOURCE / TIMING
        # ----------------------------------------------------

        "data_source": "data_raw.json",

        "source_worker_timestamp": raw.get(
            "worker_timestamp"
        ),

        "source_spot_timestamp": raw.get(
            "spot_timestamp"
        ),

        "source_last_update": raw.get(
            "last_update"
        ),

        "calculated_at_ist": now.isoformat(),

        "market_status": raw.get(
            "market_status",
            "UNKNOWN",
        ),

        "websocket_connected": raw.get(
            "websocket_connected"
        ),

        # ----------------------------------------------------
        # RAW-DERIVED MARKET SNAPSHOT
        # ----------------------------------------------------

        "live_spot": round(
            spot,
            2,
        ),

        "spot_timestamp": raw.get(
            "spot_timestamp"
        ),

        # These are copied from worker, not independently
        # calculated from another source.
        "intraday_high": round(
            intraday_high,
            2,
        ),

        "intraday_low": round(
            intraday_low,
            2,
        ),

        "live_day_high": round(
            intraday_high,
            2,
        ),

        "live_day_low": round(
            intraday_low,
            2,
        ),

        "day_high": round(
            intraday_high,
            2,
        ),

        "day_low": round(
            intraday_low,
            2,
        ),

        # ----------------------------------------------------
        # CANONICAL LIVE INDICATORS
        # ----------------------------------------------------

        "rsi": round(
            live_rsi,
            2,
        ),

        "ema9": round(
            live_ema9,
            2,
        ),

        "ema20": round(
            live_ema20,
            2,
        ),

        "rsi_live": round(
            live_rsi,
            2,
        ),

        "ema9_live": round(
            live_ema9,
            2,
        ),

        "ema20_live": round(
            live_ema20,
            2,
        ),

        # ----------------------------------------------------
        # CANONICAL COMPLETED VALUES
        # ----------------------------------------------------

        "rsi_closed": round(
            closed_rsi,
            2,
        ),

        "ema9_closed": round(
            closed_ema9,
            2,
        ),

        "ema20_closed": round(
            closed_ema20,
            2,
        ),

        # ----------------------------------------------------
        # NESTED CONTEXT
        # ----------------------------------------------------

        "live": {
            "rsi": round(
                live_rsi,
                2,
            ),
            "ema9": round(
                live_ema9,
                2,
            ),
            "ema20": round(
                live_ema20,
                2,
            ),
            "candle": forming_candle,
            "forming_candle_present": bool(
                not forming_df.empty
            ),
        },

        "completed": {
            "candle_time": closed_candle[
                "time"
            ],
            "rsi": round(
                closed_rsi,
                2,
            ),
            "ema9": round(
                closed_ema9,
                2,
            ),
            "ema20": round(
                closed_ema20,
                2,
            ),
            "candle": closed_candle,
            "is_confirmable_candle": True,
        },

        # ----------------------------------------------------
        # TECHNICAL DATA
        # ----------------------------------------------------

        "ema_context": ema_context,

        "volume": volume,

        # Canonical dashboard/paper-engine volume field.
        "volume_ratio": volume[
            "completed_candle_ratio"
        ],

        "live_volume_ratio": volume[
            "live_volume_ratio"
        ],

        "levels": levels["levels"],

        "major_levels": levels[
            "major_levels"
        ],

        "supports": levels[
            "supports"
        ],

        "resistances": levels[
            "resistances"
        ],

        "nearest_support": levels[
            "nearest_support"
        ],

        "nearest_resistance": levels[
            "nearest_resistance"
        ],

        "nearest_support_distance":
            nearest_support_distance,

        "nearest_resistance_distance":
            nearest_resistance_distance,

        "previous_day_high":
            levels["previous_day_high"],

        "previous_day_low":
            levels["previous_day_low"],

        "morning_box_high":
            levels["morning_box_high"],

        "morning_box_low":
            levels["morning_box_low"],

        "psychological_step":
            PSYCHOLOGICAL_STEP,

        "breakout_candidates":
            breakout_candidates,

        "distances":
            distances,

        # ----------------------------------------------------
        # CANDLE DATA
        # ----------------------------------------------------

        "candle_range":
            closed_candle["range"],

        "candle_body":
            closed_candle["body"],

        "upper_wick":
            closed_candle["upper_wick"],

        "lower_wick":
            closed_candle["lower_wick"],

        "opposite_wick":
            (
                closed_candle["upper_wick"]
                if closed_candle["bullish"]
                else closed_candle["lower_wick"]
            ),

        "candle_size_valid":
            closed_candle[
                "candle_size_valid"
            ],

        "opposite_wick_5pct_for_bull":
            closed_candle[
                "opposite_wick_5pct_for_bull"
            ],

        "opposite_wick_5pct_for_bear":
            closed_candle[
                "opposite_wick_5pct_for_bear"
            ],

        "latest_completed_candle":
            closed_candle,

        "forming_candle":
            forming_candle,

        "recent_completed_candles":
            build_recent_candles(
                completed_df,
                30,
            ),

        # ----------------------------------------------------
        # RUNWAY DATA
        # ----------------------------------------------------

        "ce_runway":
            distances["ce_runway"],

        "pe_runway":
            distances["pe_runway"],

        "ce_runway_status":
            distances[
                "ce_runway_status"
            ],

        "pe_runway_status":
            distances[
                "pe_runway_status"
            ],

        "runway_min_points":
            RUNWAY_MIN,

        # ----------------------------------------------------
        # THRESHOLDS
        # ----------------------------------------------------

        "thresholds": {
            "rsi_period": RSI_PERIOD,
            "ema_fast": EMA_FAST,
            "ema_slow": EMA_SLOW,
            "volume_avg_period":
                VOLUME_AVG_PERIOD,
            "volume_pass_ratio":
                VOLUME_PASS_RATIO,
            "candle_range_min":
                CANDLE_MIN,
            "candle_range_max":
                CANDLE_MAX,
            "runway_min_points":
                RUNWAY_MIN,
            "wick_body_max_ratio":
                WICK_BODY_MAX,
            "psychological_step":
                PSYCHOLOGICAL_STEP,
        },

        # ----------------------------------------------------
        # DATA QUALITY
        # ----------------------------------------------------

        "data_quality": {
            "raw_spot": "OK",
            "raw_day_high": (
                "OK"
                if raw.get("intraday_high")
                is not None
                else "MISSING"
            ),
            "raw_day_low": (
                "OK"
                if raw.get("intraday_low")
                is not None
                else "MISSING"
            ),
            "candle_count":
                int(len(df)),
            "completed_candle_count":
                int(len(completed_df)),
            "forming_candle_count":
                int(len(forming_df)),
            "futures_volume_matches":
                int(volume_matches),
            "futures_volume_history":
                volume[
                    "data_quality"
                ],
        },

        "completed_candle_count":
            int(len(completed_df)),

        "forming_candle_count":
            int(len(forming_df)),

        "volume_merge_matches":
            int(volume_matches),

        "candle_last_success":
            raw.get("candle_last_success"),

        "candle_retry_delay":
            raw.get("candle_retry_delay"),

        "futures_candle_last_success":
            raw.get(
                "futures_candle_last_success"
            ),

        "futures_candle_retry_delay":
            raw.get(
                "futures_candle_retry_delay"
            ),

        # ----------------------------------------------------
        # RAW CONTRACT / QUOTE PASSTHROUGH
        # These are still from data_raw; no calculations.
        # ----------------------------------------------------

        "futures_contract":
            raw.get("future_contract"),

        "future_quote":
            raw.get("future_quote"),

        "option_quote":
            raw.get("option_quote"),

        "option_contract":
            raw.get("option_contract"),

        "live_futures_volume_5m":
            raw.get("live_futures_volume_5m"),
    }

    return json_safe(payload)


# ============================================================
# ENGINE LOOP
# ============================================================

def start_indicator_engine() -> None:

    logging.info(
        "🟢 indicator_calc started | "
        "SOURCE=data_raw.json | "
        "TECHNICAL DATA ONLY | "
        "No CALL/PUT | No BUY/SELL | No entry/exit"
    )

    last_log_time = 0.0
    last_candle_time = None

    while True:

        raw = load_raw()

        if not raw:
            time.sleep(
                WAIT_INTERVAL_SEC
            )
            continue

        try:

            now = now_ist()

            processed = calculate_indicators(
                raw,
                now,
            )

            if processed is None:

                time.sleep(
                    WAIT_INTERVAL_SEC
                )

                continue

            atomic_write_json(
                OUTPUT_FILE,
                processed,
            )

            current_candle = (
                processed.get(
                    "completed",
                    {},
                )
                or {}
            ).get(
                "candle_time"
            )

            current_time = time.time()

            if (
                current_candle
                != last_candle_time
                or
                current_time
                - last_log_time
                >= LOG_INTERVAL_SEC
            ):

                last_candle_time = (
                    current_candle
                )

                last_log_time = (
                    current_time
                )

                live = (
                    processed.get(
                        "live",
                        {},
                    )
                    or {}
                )

                closed = (
                    processed.get(
                        "completed",
                        {},
                    )
                    or {}
                )

                vol = (
                    processed.get(
                        "volume",
                        {},
                    )
                    or {}
                )

                quality = (
                    processed.get(
                        "data_quality",
                        {},
                    )
                    or {}
                )

                logging.info(
                    "📊 INDICATORS | "
                    "Spot=%.2f | "
                    "LIVE RSI=%.2f EMA9=%.2f EMA20=%.2f | "
                    "CLOSED=%s RSI=%.2f EMA9=%.2f EMA20=%.2f | "
                    "VOL=%.2fx LIVEVOL=%.2fx | "
                    "DayH/L=%.2f/%.2f | "
                    "FUT_MATCH=%s | FUT_DATA=%s",
                    float(
                        processed["live_spot"]
                    ),
                    float(
                        live.get(
                            "rsi",
                            50.0,
                        )
                    ),
                    float(
                        live.get(
                            "ema9",
                            0.0,
                        )
                    ),
                    float(
                        live.get(
                            "ema20",
                            0.0,
                        )
                    ),
                    str(
                        current_candle
                    ),
                    float(
                        closed.get(
                            "rsi",
                            50.0,
                        )
                    ),
                    float(
                        closed.get(
                            "ema9",
                            0.0,
                        )
                    ),
                    float(
                        closed.get(
                            "ema20",
                            0.0,
                        )
                    ),
                    float(
                        vol.get(
                            "completed_candle_ratio",
                            0.0,
                        )
                    ),
                    float(
                        vol.get(
                            "live_volume_ratio",
                            0.0,
                        )
                    ),
                    float(
                        processed[
                            "live_day_high"
                        ]
                    ),
                    float(
                        processed[
                            "live_day_low"
                        ]
                    ),
                    quality.get(
                        "futures_volume_matches",
                        0,
                    ),
                    quality.get(
                        "futures_volume_history",
                        "UNKNOWN",
                    ),
                )

        except Exception as exc:

            logging.exception(
                "🔴 indicator_calc error: %s",
                exc,
            )

        time.sleep(
            PUBLISH_INTERVAL_SEC
        )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    start_indicator_engine()
