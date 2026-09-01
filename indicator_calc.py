# indicator_calc.py
#
# Indicator engine NEVER talks to Angel One.
# Reads data_raw.json and publishes strategy_signal.json.
#
# IMPORTANT:
# - Indicators calculate continuously from available candles.
# - Signal structure uses ONLY the last COMPLETED 5-minute candle (-2).
# - It does NOT wait for the current 5-minute candle to close.
# - It only requires enough historical candles to calculate indicators.

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"

    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    os.replace(tmp, path)


def calculate_tv_rsi(series, period=14):

    if len(series) < period + 1:
        return 50.0

    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    alpha = 1.0 / period

    avg_gain = gain.ewm(
        alpha=alpha,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=alpha,
        adjust=False
    ).mean()

    avg_loss = avg_loss.replace(0, 0.00001)

    rs = avg_gain / avg_loss

    rsi = 100.0 - (100.0 / (1.0 + rs))

    return float(rsi.iloc[-1])


def load_raw():

    try:

        with open("data_raw.json", "r") as f:
            return json.load(f)

    except Exception:

        return None


def start_indicator_engine():

    logging.info("🟢 Indicator engine started")

    last_logged_candle_count = -1
    last_signal_candle = ""

    while True:

        raw = load_raw()

        if not raw:
            time.sleep(1)
            continue

        try:

            if "live_spot" not in raw:
                time.sleep(1)
                continue

            spot = float(raw["live_spot"])

            candles = raw.get("candles") or []

            # -------------------------------------------------
            # MINIMUM DATA
            #
            # We need:
            # 14 RSI period
            # EMA 20
            # volume average
            # previous completed candle
            #
            # 22 candles is sufficient.
            # -------------------------------------------------

            if len(candles) < 22:

                if len(candles) != last_logged_candle_count:

                    logging.info(
                        "Waiting for historical candles: %d/22",
                        len(candles)
                    )

                    last_logged_candle_count = len(candles)

                time.sleep(1)
                continue

            # -------------------------------------------------
            # DATAFRAME
            # -------------------------------------------------

            df = pd.DataFrame(
                candles,
                columns=[
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume"
                ]
            )

            for col in [
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]:

                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce"
                )

            df["datetime"] = pd.to_datetime(
                df["date"],
                errors="coerce"
            )

            df = df.dropna(
                subset=[
                    "datetime",
                    "open",
                    "high",
                    "low",
                    "close"
                ]
            ).reset_index(drop=True)

            if len(df) < 22:

                time.sleep(1)
                continue

            # -------------------------------------------------
            # IMPORTANT:
            #
            # -1 = currently forming candle
            # -2 = LAST COMPLETED 5-MIN CANDLE
            #
            # Signal candle is ALWAYS -2.
            # -------------------------------------------------

            closed_idx = -2

            signal_candle_time = str(
                df["date"].iloc[closed_idx]
            )

            # -------------------------------------------------
            # INDICATORS
            #
            # Indicators use available historical data.
            # No waiting for next candle close.
            # -------------------------------------------------

            rsi_v = calculate_tv_rsi(
                df["close"],
                14
            )

            ema9 = float(
                df["close"]
                .ewm(
                    span=9,
                    adjust=False
                )
                .mean()
                .iloc[-1]
            )

            ema20 = float(
                df["close"]
                .ewm(
                    span=20,
                    adjust=False
                )
                .mean()
                .iloc[-1]
            )

            # -------------------------------------------------
            # TODAY HIGH / LOW
            # -------------------------------------------------

            now_dt = now_ist()

            today_str = now_dt.strftime(
                "%Y-%m-%d"
            )

            df_t = df[
                df["datetime"]
                .dt.strftime("%Y-%m-%d")
                == today_str
            ]

            if not df_t.empty:

                intraday_high = float(
                    df_t["high"].max()
                )

                intraday_low = float(
                    df_t["low"].min()
                )

            else:

                intraday_high = spot + 50.0
                intraday_low = spot - 50.0

            # -------------------------------------------------
            # COMPLETED CANDLE DATA
            # -------------------------------------------------

            c_open = float(
                df["open"].iloc[closed_idx]
            )

            c_close = float(
                df["close"].iloc[closed_idx]
            )

            c_high = float(
                df["high"].iloc[closed_idx]
            )

            c_low = float(
                df["low"].iloc[closed_idx]
            )

            candle_range = abs(
                c_high - c_low
            )

            if candle_range <= 0:
                candle_range = 0.01

            candle_body = abs(
                c_close - c_open
            )

            if candle_body <= 0:
                candle_body = 0.01

            top_wick = max(
                0.0,
                c_high - max(
                    c_open,
                    c_close
                )
            )

            bottom_wick = max(
                0.0,
                min(
                    c_open,
                    c_close
                ) - c_low
            )

            # -------------------------------------------------
            # PSYCHOLOGICAL LEVEL
            # -------------------------------------------------

            psy_level = int(
                round(spot / 50.0) * 50
            )

            # -------------------------------------------------
            # CANDLE SIZE
            # -------------------------------------------------

            is_candle_size_valid = (
                12.0 <= candle_range <= 25.0
            )

            # -------------------------------------------------
            # REJECTION
            # -------------------------------------------------

            upper_rejection = (
                abs(c_high - psy_level) <= 25.0
                and top_wick >= candle_range * 0.50
            )

            lower_rejection = (
                abs(c_low - psy_level) <= 25.0
                and bottom_wick >= candle_range * 0.50
            )

            is_rejection = (
                upper_rejection
                or lower_rejection
            )

            # -------------------------------------------------
            # PULLBACK
            #
            # Current LIVE spot can be compared with EMA9.
            # No candle-close wait here.
            # -------------------------------------------------

            is_pullback = (
                not is_rejection
                and abs(spot - ema9) <= 25.0
            )

            # -------------------------------------------------
            # DEFAULT
            # -------------------------------------------------

            otype = "NONE"

            rsi_status = "FAIL"
            ema_status = "FAIL"

            setup_name = "NONE"

            candle_confirmed = False

            # -------------------------------------------------
            # MAJOR REJECTION
            # -------------------------------------------------

            if is_rejection:

                if upper_rejection:
                    otype = "PE"

                elif lower_rejection:
                    otype = "CE"

                rsi_status = "PASS"
                ema_status = "PASS"

                setup_name = "Major Rejection"

                candle_confirmed = True

            # -------------------------------------------------
            # PULLBACK
            # -------------------------------------------------

            elif is_pullback:

                otype = (
                    "CE"
                    if spot >= ema9
                    else "PE"
                )

                rsi_status = (
                    "PASS"
                    if 45.0 <= rsi_v <= 55.0
                    else "FAIL"
                )

                ema_status = (
                    "PASS"
                    if abs(spot - ema9) <= 15.0
                    else "FAIL"
                )

                setup_name = "Pullback"

                # Fixed 5% opposite-wick rule.
                if otype == "CE":
                    opposite_wick = top_wick
                else:
                    opposite_wick = bottom_wick

                candle_confirmed = (
                    opposite_wick <= candle_body * 0.05
                )

            # -------------------------------------------------
            # BREAKOUT
            # -------------------------------------------------

            else:

                if spot > ema9:

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

                if otype == "CE":
                    opposite_wick = top_wick
                else:
                    opposite_wick = bottom_wick

                candle_confirmed = (
                    opposite_wick <= candle_body * 0.05
                )

            # -------------------------------------------------
            # TRADE TYPE
            # -------------------------------------------------

            trade_type = (
                f"{otype}_BUY"
                if otype != "NONE"
                else "NONE"
            )

            # -------------------------------------------------
            # VOLUME
            #
            # Previous 20 completed candles.
            # Signal candle itself is included as current_volume.
            # -------------------------------------------------

            volume_window = df[
                "volume"
            ].iloc[-22:-2]

            volume_window = volume_window.dropna()

            vol_avg = float(
                volume_window.mean()
            ) if not volume_window.empty else 0.0

            current_volume = float(
                df["volume"].iloc[closed_idx]
            ) if pd.notna(
                df["volume"].iloc[closed_idx]
            ) else 0.0

            if vol_avg > 0:

                vol_ratio = round(
                    current_volume / vol_avg,
                    2
                )

            else:

                vol_ratio = 0.0

            vol_status = (
                "PASS"
                if vol_ratio >= 1.20
                else "FAIL"
            )

            # -------------------------------------------------
            # RUNWAY
            # -------------------------------------------------

            if otype == "CE":

                runway_distance = (
                    intraday_high - spot
                )

            elif otype == "PE":

                runway_distance = (
                    spot - intraday_low
                )

            else:

                runway_distance = 0.0

            runway_distance = max(
                0.0,
                runway_distance
            )

            runway_status = (
                "PASS"
                if runway_distance >= 15.0
                else "FAIL"
            )

            # -------------------------------------------------
            # FINAL GATE
            # -------------------------------------------------

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

            # -------------------------------------------------
            # REASON
            # -------------------------------------------------

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
                    f"🔒 {setup_name} LOCK | "
                    f"Failed: "
                    f"{', '.join(failed) if failed else 'SETUP'}"
                )

            elif not is_candle_size_valid:

                reason = (
                    f"⚠️ Size Lock | "
                    f"Candle range "
                    f"{candle_range:.1f} pts "
                    f"(required 12-25)"
                )

            elif not candle_confirmed:

                reason = (
                    "⚠️ Marubozu Lock | "
                    "Opposite wick exceeds 5% "
                    "of candle body"
                )

            else:

                reason = (
                    f"🟢 SIGNAL READY | "
                    f"{setup_name} | "
                    f"{trade_type} | "
                    f"Runway "
                    f"{runway_distance:.1f} pts"
                )

            # -------------------------------------------------
            # OPTION STRIKE
            # -------------------------------------------------

            option_strike = int(
                round(spot / 50.0) * 50
            )

            # -------------------------------------------------
            # TARGET REFERENCE
            # -------------------------------------------------

            if otype == "CE":

                next_wall = intraday_high

            elif otype == "PE":

                next_wall = intraday_low

            else:

                next_wall = spot

            # -------------------------------------------------
            # OUTPUT
            # -------------------------------------------------

            payload = {

                "live_spot": spot,

                "rsi_v": round(
                    rsi_v,
                    2
                ),

                "ema9": round(
                    ema9,
                    2
                ),

                "ema20": round(
                    ema20,
                    2
                ),

                "rsi_status":
                    rsi_status,

                "ema_status":
                    ema_status,

                "vol_status":
                    vol_status,

                "vol_val":
                    f"{vol_ratio}x",

                "runway_status":
                    runway_status,

                "runway_val":
                    f"{runway_distance:.1f} pts",

                "intraday_high":
                    intraday_high,

                "intraday_low":
                    intraday_low,

                "psy_level":
                    psy_level,

                "algo_reason":
                    reason,

                "signal_triggered":
                    bool(final_trigger),

                "trade_type":
                    trade_type,

                "otype":
                    otype,

                "option_strike":
                    option_strike,

                "next_w":
                    next_wall,

                "run_df":
                    runway_distance,

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
                    bool(
                        is_candle_size_valid
                    ),

                "candle_confirmed":
                    bool(
                        candle_confirmed
                    ),

                "strategy_used":
                    setup_name,

                "candle_time":
                    signal_candle_time,

                "calculated_at":
                    now_dt.isoformat(),
            }

            atomic_write_json(
                "strategy_signal.json",
                payload
            )

            # -------------------------------------------------
            # LOG ONLY WHEN COMPLETED CANDLE CHANGES
            # -------------------------------------------------

            if signal_candle_time != last_signal_candle:

                logging.info(
                    "🕐 Completed candle: %s | "
                    "Spot %.2f | RSI %.2f | "
                    "EMA9 %.2f | Setup %s | "
                    "Signal %s",
                    signal_candle_time,
                    spot,
                    rsi_v,
                    ema9,
                    setup_name,
                    "READY" if final_trigger else "LOCKED"
                )

                last_signal_candle = (
                    signal_candle_time
                )

        except Exception as err:

            logging.exception(
                "Indicator engine error: %s",
                err
            )

        # -------------------------------------------------
        # IMPORTANT:
        # Indicator recalculates every second.
        # It does NOT wait for a 5-minute close.
        # -------------------------------------------------

        time.sleep(1)


if __name__ == "__main__":
    start_indicator_engine()
