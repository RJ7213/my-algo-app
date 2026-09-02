# indicator_calc.py
# ============================================================
# NIFTY LIVE INDICATOR + STRATEGY ENGINE
# ============================================================
#
# Architecture:
#   data_worker.py  -> data_raw.json
#   indicator_calc.py reads ONLY data_raw.json
#   indicator_calc.py publishes strategy_signal.json
#   paper_engine.py reads data_raw.json + strategy_signal.json
#
# IMPORTANT:
#   1. Indicators are LIVE and recalculate from the live NIFTY tick.
#   2. Day High / Day Low come from live tick data supplied by worker.
#   3. Live volume uses live NIFTY FUTURES 5-min volume when available.
#   4. Strategy/entry confirmation uses the LAST COMPLETED 5-min candle.
#   5. No entry is generated from the still-forming candle.
#   6. Paper engine remains completely independent of Angel One.
# ============================================================

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

IST = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# CONSTANTS
# ============================================================

RSI_PERIOD = 14
VOLUME_AVG_PERIOD = 20
VOLUME_PASS_RATIO = 1.20
CANDLE_MIN = 12.0
CANDLE_MAX = 25.0
RUNWAY_MIN = 15.0
WICK_BODY_MAX = 0.05


# ============================================================
# TIME / JSON
# ============================================================

def now_ist():
    return datetime.now(IST)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_raw():
    try:
        with open("data_raw.json", "r") as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================
# RSI
# ============================================================

def calculate_tv_rsi(series, period=RSI_PERIOD):
    series = pd.to_numeric(series, errors="coerce").dropna()
    if len(series) < period + 1:
        return 50.0

    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).astype(float)
    loss = (-delta.where(delta < 0, 0.0)).astype(float)

    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, 0.00001)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi.iloc[-1])


# ============================================================
# DATAFRAME PREPARATION
# ============================================================

def build_spot_dataframe(candles):
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=[
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["datetime", "open", "high", "low", "close"]
    ).copy()

    df = df.sort_values("datetime").drop_duplicates(
        subset=["datetime"], keep="last"
    ).reset_index(drop=True)

    if "volume" not in df:
        df["volume"] = 0.0

    df["volume"] = df["volume"].fillna(0.0)
    return df


def normalise_timestamp_series(series):
    dt = pd.to_datetime(series, errors="coerce")
    try:
        if getattr(dt.dt, "tz", None) is None:
            return dt.dt.tz_localize(IST)
        return dt.dt.tz_convert(IST)
    except Exception:
        return dt


# ============================================================
# FUTURES VOLUME MERGE
# ============================================================

def merge_futures_volume(spot_df, futures_candles):
    """
    Keep spot OHLC as the price source.
    Replace/attach volume from NIFTY FUTURES by candle timestamp.
    This is data alignment, not strategy logic.
    """
    out = spot_df.copy()
    out["futures_volume"] = 0.0

    if not isinstance(futures_candles, list) or not futures_candles:
        return out, 0

    try:
        fut = pd.DataFrame(
            futures_candles,
            columns=[
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        fut["datetime"] = pd.to_datetime(
            fut["date"], errors="coerce"
        )
        fut["volume"] = pd.to_numeric(
            fut["volume"], errors="coerce"
        ).fillna(0.0)
        fut = fut.dropna(subset=["datetime"]).copy()

        out_key = normalise_timestamp_series(out["datetime"]).dt.floor("min")
        fut_key = normalise_timestamp_series(fut["datetime"]).dt.floor("min")

        fmap = {}
        for key, vol in zip(fut_key, fut["volume"]):
            fmap[key] = float(vol)

        matched = 0
        merged = []
        for key, old_volume in zip(out_key, out["volume"]):
            if key in fmap:
                merged.append(fmap[key])
                matched += 1
            else:
                merged.append(float(old_volume) if pd.notna(old_volume) else 0.0)

        out["futures_volume"] = merged
        return out, matched

    except Exception as exc:
        logging.warning("⚠️ Futures volume merge failed: %s", exc)
        return out, 0


# ============================================================
# CLOSED CANDLE SELECTION
# ============================================================

def split_completed_and_forming(df, now):
    """
    Angel candle timestamp is treated as candle START time.
    A 5-min candle is completed only after start + 5 minutes.
    """
    work = df.copy()
    work["datetime_ist"] = normalise_timestamp_series(work["datetime"])
    cutoff = now.replace(second=0, microsecond=0)

    completed_mask = (
        work["datetime_ist"] + pd.Timedelta(minutes=5)
        <= pd.Timestamp(cutoff)
    )

    completed = work.loc[completed_mask].copy().reset_index(drop=True)
    forming = work.loc[~completed_mask].copy().reset_index(drop=True)
    return completed, forming


def build_live_dataframe(completed_df, forming_df, live_spot, now):
    """
    Build a synthetic current candle for LIVE RSI/EMA only.
    It is NEVER used for entry confirmation.
    """
    if completed_df.empty:
        return pd.DataFrame()

    last = completed_df.iloc[-1]

    bucket_start = now.replace(
        minute=(now.minute // 5) * 5,
        second=0,
        microsecond=0,
    )

    # If Angel supplied the current forming candle, use its OHLC structure.
    current = None
    if not forming_df.empty:
        same_bucket = forming_df[
            forming_df["datetime_ist"] == pd.Timestamp(bucket_start)
        ]
        if not same_bucket.empty:
            current = same_bucket.iloc[-1]

    if current is not None:
        live_open = float(current["open"])
        live_high = max(float(current["high"]), float(live_spot))
        live_low = min(float(current["low"]), float(live_spot))
    else:
        live_open = float(last["close"])
        live_high = max(live_open, float(live_spot))
        live_low = min(live_open, float(live_spot))

    live_row = {
        "date": bucket_start.isoformat(),
        "datetime": bucket_start,
        "datetime_ist": pd.Timestamp(bucket_start),
        "open": live_open,
        "high": live_high,
        "low": live_low,
        "close": float(live_spot),
        "volume": 0.0,
        "futures_volume": 0.0,
    }

    out = completed_df.copy()
    out = pd.concat([out, pd.DataFrame([live_row])], ignore_index=True)
    return out


# ============================================================
# LEVEL ENGINE
# ============================================================

def build_level_engine(df, spot, day_high, day_low):
    today = now_ist().date()
    levels = []

    def add(name, value, source, strength):
        if value is not None:
            levels.append({"name": name, "level": float(value), "source": source, "strength": strength})

    add("Day High", day_high, "DAY", 5)
    add("Day Low", day_low, "DAY", 5)

    dates = df["datetime"].dt.date
    prev_dates = sorted({d for d in dates if d < today})
    if prev_dates:
        prev = df[dates == prev_dates[-1]]
        if not prev.empty:
            add("Previous Day High", prev["high"].max(), "PREVIOUS_DAY", 4)
            add("Previous Day Low", prev["low"].min(), "PREVIOUS_DAY", 4)

    today_df = df[dates == today]
    if not today_df.empty:
        mins = today_df["datetime"].dt.hour * 60 + today_df["datetime"].dt.minute
        box = today_df[mins <= 600]
        if not box.empty:
            add("Morning Box High", box["high"].max(), "MORNING_BOX", 4)
            add("Morning Box Low", box["low"].min(), "MORNING_BOX", 4)

    base = round(float(spot) / 100.0) * 100.0
    for level in (base - 100, base, base + 100, base + 200):
        add(f"Psychological {int(level)}", level, "PSYCHOLOGICAL_100", 3)

    unique = {}
    for item in levels:
        key = round(item["level"], 2)
        if key not in unique or item["strength"] > unique[key]["strength"]:
            unique[key] = item

    ordered = sorted(unique.values(), key=lambda x: x["level"])
    supports = sorted([x for x in ordered if x["level"] < spot], key=lambda x: (spot-x["level"], -x["strength"]))
    resistances = sorted([x for x in ordered if x["level"] > spot], key=lambda x: (x["level"]-spot, -x["strength"]))

    return {
        "levels": ordered,
        "nearest_support": supports[0] if supports else None,
        "nearest_resistance": resistances[0] if resistances else None,
    }


# ============================================================
# STRATEGY EVALUATION
# ============================================================

def evaluate_strategy(
    signal_df,
    live_spot,
    intraday_high,
    intraday_low,
    signal_volume,
    signal_volume_avg,
):
    """Evaluate the existing strategy ONLY on the last completed candle."""

    if len(signal_df) < 22:
        return None

    # Signal indicators are calculated from completed candles only.
    signal_rsi = calculate_tv_rsi(signal_df["close"], RSI_PERIOD)
    signal_ema9 = float(
        signal_df["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    )
    signal_ema20 = float(
        signal_df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    )

    c = signal_df.iloc[-1]
    c_open = float(c["open"])
    c_close = float(c["close"])
    c_high = float(c["high"])
    c_low = float(c["low"])
    candle_time = str(c["date"])

    candle_range = abs(c_high - c_low)
    candle_body = abs(c_close - c_open)
    candle_body_safe = max(candle_body, 0.01)
    candle_range_safe = max(candle_range, 0.01)

    top_wick = max(0.0, c_high - max(c_open, c_close))
    bottom_wick = max(0.0, min(c_open, c_close) - c_low)

    # Strategy continues to use current/live spot for the live context,
    # but the candle structure is strictly the completed candle.
    psy_level = int(round(live_spot / 50.0) * 50)

    is_candle_size_valid = (
        CANDLE_MIN <= candle_range_safe <= CANDLE_MAX
    )

    upper_rejection = (
        abs(c_high - psy_level) <= 25.0
        and top_wick >= candle_range_safe * 0.50
    )

    lower_rejection = (
        abs(c_low - psy_level) <= 25.0
        and bottom_wick >= candle_range_safe * 0.50
    )

    is_rejection = upper_rejection or lower_rejection

    is_pullback = (
        not is_rejection
        and abs(live_spot - signal_ema9) <= 25.0
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
        otype = "CE" if live_spot >= signal_ema9 else "PE"

        rsi_status = (
            "PASS" if 45.0 <= signal_rsi <= 55.0 else "FAIL"
        )
        ema_status = (
            "PASS" if abs(live_spot - signal_ema9) <= 15.0 else "FAIL"
        )
        setup_name = "Pullback"

        opposite_wick = top_wick if otype == "CE" else bottom_wick
        candle_confirmed = (
            opposite_wick <= candle_body_safe * WICK_BODY_MAX
        )

    else:
        if live_spot > signal_ema9:
            otype = "CE"
            rsi_status = "PASS" if signal_rsi >= 60.0 else "FAIL"
        else:
            otype = "PE"
            rsi_status = "PASS" if signal_rsi <= 40.0 else "FAIL"

        ema_status = "PASS"
        setup_name = "Breakout"

        opposite_wick = top_wick if otype == "CE" else bottom_wick
        candle_confirmed = (
            opposite_wick <= candle_body_safe * WICK_BODY_MAX
        )

    trade_type = f"{otype}_BUY" if otype != "NONE" else "NONE"

    # ---------------------------------------------------------
    # CLOSED-CANDLE VOLUME GATE
    # ---------------------------------------------------------
    if signal_volume_avg > 0:
        volume_ratio = round(signal_volume / signal_volume_avg, 2)
    else:
        volume_ratio = 0.0

    volume_status = (
        "PASS" if volume_ratio >= VOLUME_PASS_RATIO else "FAIL"
    )

    # ---------------------------------------------------------
    # LIVE DAY HIGH / LOW RUNWAY
    # ---------------------------------------------------------
    if otype == "CE":
        runway_distance = max(0.0, intraday_high - live_spot)
    elif otype == "PE":
        runway_distance = max(0.0, live_spot - intraday_low)
    else:
        runway_distance = 0.0

    runway_status = (
        "PASS" if runway_distance >= RUNWAY_MIN else "FAIL"
    )

    signal_gate = (
        otype != "NONE"
        and rsi_status == "PASS"
        and ema_status == "PASS"
        and volume_status == "PASS"
        and runway_status == "PASS"
    )

    final_trigger = (
        signal_gate
        and is_candle_size_valid
        and candle_confirmed
    )

    failed = []
    if rsi_status != "PASS":
        failed.append("RSI")
    if ema_status != "PASS":
        failed.append("EMA")
    if volume_status != "PASS":
        failed.append("VOLUME")
    if runway_status != "PASS":
        failed.append("RUNWAY")

    if not signal_gate:
        reason = (
            f"🔒 {setup_name} LOCK | "
            f"Failed: {', '.join(failed) if failed else 'SETUP'}"
        )
    elif not is_candle_size_valid:
        reason = (
            f"⚠️ Size Lock | Candle range {candle_range:.1f} pts "
            f"(required {CANDLE_MIN:.0f}-{CANDLE_MAX:.0f})"
        )
    elif not candle_confirmed:
        reason = (
            "⚠️ Marubozu Lock | "
            "Opposite wick exceeds 5% of candle body"
        )
    else:
        reason = (
            f"🟢 SIGNAL READY | {setup_name} | {trade_type} | "
            f"Runway {runway_distance:.1f} pts"
        )

    return {
        "rsi_v": signal_rsi,
        "ema9": signal_ema9,
        "ema20": signal_ema20,
        "rsi_status": rsi_status,
        "ema_status": ema_status,
        "vol_status": volume_status,
        "vol_val": f"{volume_ratio}x",
        "runway_status": runway_status,
        "runway_val": f"{runway_distance:.1f} pts",
        "run_df": runway_distance,
        "otype": otype,
        "trade_type": trade_type,
        "option_strike": int(round(live_spot / 50.0) * 50),
        "next_w": intraday_high if otype == "CE" else intraday_low if otype == "PE" else live_spot,
        "algo_reason": reason,
        "signal_triggered": bool(final_trigger),
        "strategy_used": setup_name,
        "candle_time": candle_time,
        "c_open": c_open,
        "c_close": c_close,
        "c_high": c_high,
        "c_low": c_low,
        "candle_range": candle_range,
        "candle_body": candle_body,
        "top_wick": top_wick,
        "bottom_wick": bottom_wick,
        "candle_size_valid": bool(is_candle_size_valid),
        "candle_confirmed": bool(candle_confirmed),
        "signal_volume": signal_volume,
        "signal_volume_avg": signal_volume_avg,
        "signal_volume_ratio": volume_ratio,
    }


# ============================================================
# MAIN ENGINE
# ============================================================

def start_indicator_engine():
    logging.info(
        "🟢 LIVE Indicator engine started | "
        "Indicators=LIVE | Entry=ONLY CLOSED 5-MIN CANDLE"
    )

    last_logged_candle = None

    while True:
        raw = load_raw()
        if not raw:
            time.sleep(0.5)
            continue

        try:
            if "live_spot" not in raw:
                time.sleep(0.5)
                continue

            now = now_ist()
            spot = float(raw["live_spot"])

            candles = raw.get("candles") or []
            if len(candles) < 22:
                logging.info(
                    "⏳ Waiting for sufficient 5-min candles: %d/22",
                    len(candles),
                )
                time.sleep(1)
                continue

            df = build_spot_dataframe(candles)
            if len(df) < 22:
                time.sleep(1)
                continue

            # Merge NIFTY futures historical volume without changing spot OHLC.
            df, matched = merge_futures_volume(
                df,
                raw.get("futures_candles") or [],
            )

            completed_df, forming_df = split_completed_and_forming(df, now)

            if len(completed_df) < 22:
                logging.info(
                    "⏳ Waiting for completed 5-min candles: %d/22",
                    len(completed_df),
                )
                time.sleep(1)
                continue

            # -------------------------------------------------
            # LIVE INDICATORS
            # -------------------------------------------------
            live_df = build_live_dataframe(
                completed_df,
                forming_df,
                spot,
                now,
            )

            if live_df.empty:
                time.sleep(1)
                continue

            live_rsi = calculate_tv_rsi(live_df["close"], RSI_PERIOD)
            live_ema9 = float(
                live_df["close"].ewm(span=9, adjust=False).mean().iloc[-1]
            )
            live_ema20 = float(
                live_df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
            )

            # -------------------------------------------------
            # LIVE DAY HIGH / LOW
            # -------------------------------------------------
            live_high = raw.get("live_day_high")
            live_low = raw.get("live_day_low")

            if live_high is None:
                live_high = spot
            if live_low is None:
                live_low = spot

            intraday_high = max(float(live_high), spot)
            intraday_low = min(float(live_low), spot)

            # -------------------------------------------------
            # LIVE VOLUME
            # -------------------------------------------------
            live_volume = raw.get("live_futures_volume_5m")
            try:
                live_volume = float(live_volume) if live_volume is not None else None
            except (TypeError, ValueError):
                live_volume = None

            # Historical completed futures volumes.
            hist_volumes = pd.to_numeric(
                completed_df["futures_volume"], errors="coerce"
            ).fillna(0.0)

            nonzero_hist = hist_volumes[hist_volumes > 0]
            live_volume_avg = (
                float(nonzero_hist.tail(VOLUME_AVG_PERIOD).mean())
                if not nonzero_hist.empty
                else 0.0
            )

            if live_volume is not None and live_volume_avg > 0:
                live_volume_ratio = round(live_volume / live_volume_avg, 2)
                live_volume_status = (
                    "PASS" if live_volume_ratio >= VOLUME_PASS_RATIO else "FAIL"
                )
                live_volume_display = f"{live_volume_ratio}x Live"
            elif live_volume is not None:
                live_volume_ratio = 0.0
                live_volume_status = "FAIL"
                live_volume_display = "0.0x Live"
            else:
                live_volume_ratio = 0.0
                live_volume_status = "FAIL"
                live_volume_display = "WAIT"

            # -------------------------------------------------
            # CLOSED-CANDLE SIGNAL
            # -------------------------------------------------
            signal_volume_series = hist_volumes
            signal_volume = float(signal_volume_series.iloc[-1])
            signal_window = signal_volume_series.iloc[-(VOLUME_AVG_PERIOD + 1):-1]
            signal_window = signal_window[signal_window > 0]
            signal_volume_avg = (
                float(signal_window.tail(VOLUME_AVG_PERIOD).mean())
                if not signal_window.empty
                else 0.0
            )

            signal = evaluate_strategy(
                completed_df,
                spot,
                intraday_high,
                intraday_low,
                signal_volume,
                signal_volume_avg,
            )

            if signal is None:
                time.sleep(1)
                continue

            # -------------------------------------------------
            # OVERWRITE DASHBOARD VALUES WITH LIVE INDICATORS
            # -------------------------------------------------
            # Paper engine still uses signal_triggered, which was calculated
            # from the completed candle above. Dashboard gets live values.
            signal["live_spot"] = spot
            signal["rsi_v"] = round(live_rsi, 2)
            signal["ema9"] = round(live_ema9, 2)
            signal["ema20"] = round(live_ema20, 2)
            signal["vol_val"] = live_volume_display
            signal["vol_status"] = live_volume_status

            # Explicit closed-candle copies for backend/paper-trade records.
            closed_signal = evaluate_strategy(
                completed_df,
                spot,
                intraday_high,
                intraday_low,
                signal_volume,
                signal_volume_avg,
            )

            signal["signal_rsi"] = round(float(closed_signal["rsi_v"]), 2)
            signal["signal_ema9"] = round(float(closed_signal["ema9"]), 2)
            signal["signal_ema20"] = round(float(closed_signal["ema20"]), 2)
            signal["signal_rsi_status"] = closed_signal["rsi_status"]
            signal["signal_ema_status"] = closed_signal["ema_status"]
            signal["signal_vol_status"] = closed_signal["vol_status"]
            signal["signal_vol_val"] = closed_signal["vol_val"]
            signal["signal_runway_status"] = closed_signal["runway_status"]
            signal["signal_runway_val"] = closed_signal["runway_val"]
            signal["signal_algo_reason"] = closed_signal["algo_reason"]
            signal["signal_strategy_used"] = closed_signal["strategy_used"]
            signal["signal_candle_time"] = closed_signal["candle_time"]
            signal["signal_option_strike"] = closed_signal["option_strike"]
            signal["signal_trade_type"] = closed_signal["trade_type"]

            signal["intraday_high"] = intraday_high
            signal["intraday_low"] = intraday_low
            signal["psy_level"] = int(round(spot / 50.0) * 50)

            level_engine = build_level_engine(
                df, spot, intraday_high, intraday_low
            )
            signal["level_engine"] = level_engine
            signal["levels"] = level_engine["levels"]
            signal["nearest_support"] = (
                level_engine["nearest_support"]["level"]
                if level_engine["nearest_support"] else None
            )
            signal["nearest_resistance"] = (
                level_engine["nearest_resistance"]["level"]
                if level_engine["nearest_resistance"] else None
            )
            signal["live_volume"] = live_volume
            signal["live_volume_avg"] = live_volume_avg
            signal["live_volume_ratio"] = live_volume_ratio
            signal["live_volume_status"] = live_volume_status
            signal["completed_candle_count"] = len(completed_df)
            signal["forming_candle_present"] = not forming_df.empty
            signal["volume_merge_matches"] = matched
            signal["calculated_at"] = now.isoformat()

            atomic_write_json("strategy_signal.json", signal)

            # Useful logs without flooding Render with every tick.
            candle_key = signal["candle_time"]
            if candle_key != last_logged_candle:
                last_logged_candle = candle_key
                logging.info(
                    "🧠 SIGNAL CANDLE=%s | RSI=%.2f | EMA9=%.2f | "
                    "EMA20=%.2f | VOL=%.2fx | RUNWAY=%.1f | %s",
                    candle_key,
                    signal["signal_rsi"],
                    signal["signal_ema9"],
                    signal["signal_ema20"],
                    float(signal["signal_vol_val"].rstrip("x"))
                    if str(signal["signal_vol_val"]).endswith("x")
                    else 0.0,
                    float(closed_signal["run_df"]),
                    "TRIGGER" if signal["signal_triggered"] else "LOCK",
                )

            logging.debug(
                "LIVE INDICATORS | spot=%.2f RSI=%.2f EMA9=%.2f EMA20=%.2f "
                "liveVol=%s dayHigh=%.2f dayLow=%.2f",
                spot,
                live_rsi,
                live_ema9,
                live_ema20,
                live_volume_display,
                intraday_high,
                intraday_low,
            )

        except Exception as err:
            logging.exception("🔴 Indicator engine error: %s", err)

        time.sleep(1)


if __name__ == "__main__":
    start_indicator_engine()
