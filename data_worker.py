# data_worker.py
#
# ============================================================
# ANGEL ONE DATA WORKER
# ============================================================
#
# ONLY component that talks to Angel One.
#
# WebSocket:
#   - NIFTY live LTP
#   - selected option live LTP
#
# REST:
#   - NIFTY SPOT historical 5-min candles
#   - NIFTY FUTURES historical 5-min candles
#   - option contract resolution
#   - NIFTY futures contract resolution
#
# IMPORTANT:
#   Spot candles provide:
#       OPEN / HIGH / LOW / CLOSE
#
#   NIFTY Futures candles provide:
#       VOLUME
#
#   data_raw.json "candles" therefore contains:
#       [date, spot_open, spot_high, spot_low,
#        spot_close, FUTURES_VOLUME]
#
# This allows existing indicator_calc.py to continue working
# without modification.
#
# ============================================================

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pyotp


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


# ============================================================
# ENVIRONMENT
# ============================================================

CID = os.getenv("ANGEL_CLIENT_CODE")
AKEY = os.getenv("ANGEL_API_KEY")
PIN = os.getenv("ANGEL_PIN")
TKEY = os.getenv("ANGEL_TOTP_SECRET")


# ============================================================
# NIFTY SPOT
# ============================================================

NIFTY_SPOT_TOKEN = os.getenv(
    "NIFTY_SPOT_TOKEN",
    "99926000"
)


# ============================================================
# TIMEZONE
# ============================================================

IST = timezone(
    timedelta(
        hours=5,
        minutes=30
    )
)


def now_ist():
    return datetime.now(IST)


# ============================================================
# ATOMIC JSON WRITE
# ============================================================

def atomic_write_json(path, payload):

    tmp = f"{path}.tmp"

    with open(
        tmp,
        "w"
    ) as f:

        json.dump(
            payload,
            f,
            separators=(",", ":")
        )

    os.replace(
        tmp,
        path
    )
# DEBUG: show latest candle volumes
try:
    if cached_candles:
        last_22 = cached_candles[-22:]

        volumes = [
            float(c[5])
            for c in last_22
            if len(c) >= 6 and c[5] is not None
        ]

        logging.info(
            "📊 VOLUME DEBUG | Last22=%s",
            volumes
        )

        if len(volumes) >= 2:
            avg_vol = sum(volumes[:-1]) / len(volumes[:-1])
            current_vol = volumes[-1]

            ratio = (
                current_vol / avg_vol
                if avg_vol > 0
                else 0
            )

            logging.info(
                "📊 VOLUME DEBUG | Current=%.0f | Avg=%.0f | Ratio=%.2fx",
                current_vol,
                avg_vol,
                ratio
            )

except Exception as debug_err:
    logging.warning(
        "Volume debug error: %s",
        debug_err
    )

# ============================================================
# EXPIRY EXTRACTION
# ============================================================

def extract_expiry(item):

    raw = str(
        item.get(
            "expiry",
            ""
        ) or ""
    ).strip()

    if raw:

        for fmt in (
            "%d%b%Y",
            "%d%b%y",
            "%d-%b-%Y",
            "%d-%b-%y",
            "%Y-%m-%d"
        ):

            try:

                return datetime.strptime(
                    raw.upper(),
                    fmt
                ).date()

            except ValueError:

                pass

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        )
    )

    m = re.search(
        r"(\d{1,2}[A-Z]{3}\d{2,4})",
        symbol.upper()
    )

    if m:

        token = m.group(1)

        for fmt in (
            "%d%b%Y",
            "%d%b%y"
        ):

            try:

                return datetime.strptime(
                    token,
                    fmt
                ).date()

            except ValueError:

                pass

    return None


# ============================================================
# OPTION TYPE
# ============================================================

def option_type(item):

    for key in (
        "optiontype",
        "optionType",
        "opttype",
        "type"
    ):

        value = str(
            item.get(
                key,
                ""
            )
        ).upper().strip()

        if value in (
            "CE",
            "PE"
        ):

            return value

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        )
    ).upper()

    if symbol.endswith("CE"):
        return "CE"

    if symbol.endswith("PE"):
        return "PE"

    return ""


# ============================================================
# STRIKE VALUE
# ============================================================

def strike_value(item):

    for key in (
        "strike",
        "strikePrice",
        "strikeprice"
    ):

        try:

            value = float(
                item.get(key)
            )

            if value > 100000:
                value /= 100.0

            return value

        except (
            TypeError,
            ValueError
        ):

            pass

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        )
    ).upper()

    m = re.search(
        r"(\d+(?:\.\d+)?)(?:CE|PE)$",
        symbol
    )

    if m:

        try:

            value = float(
                m.group(1)
            )

            if value > 100000:
                value /= 100.0

            return value

        except ValueError:

            pass

    return None


# ============================================================
# IS NIFTY FUTURE
# ============================================================

def is_nifty_future(item):

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        )
    ).upper()

    name = str(
        item.get(
            "name",
            ""
        )
    ).upper()

    instrument_type = str(
        item.get(
            "instrumenttype",
            ""
        )
    ).upper()

    exch_seg = str(
        item.get(
            "exch_seg",
            ""
        )
    ).upper()

    # Main checks
    if exch_seg and exch_seg != "NFO":
        return False

    if instrument_type in (
        "FUTIDX",
        "FUTSTK"
    ):

        if (
            name == "NIFTY"
            or symbol.startswith("NIFTY")
        ):

            return True

    # Fallback
    if (
        symbol.startswith("NIFTY")
        and symbol.endswith("FUT")
    ):

        return True

    return False


# ============================================================
# RESOLVE NIFTY FUTURES
# ============================================================

def resolve_nifty_future(
    api,
    today
):

    try:

        logging.info(
            "🔎 Resolving current NIFTY Futures contract..."
        )

        response = api.searchScrip(
            "NFO",
            "NIFTY"
        )

        if not response:

            logging.warning(
                "NIFTY futures search returned empty response"
            )

            return None

        if not response.get("status"):

            logging.warning(
                "NIFTY futures search unsuccessful: %s",
                response
            )

            return None

        items = response.get(
            "data"
        ) or []

        if not items:

            logging.warning(
                "NIFTY futures search returned no contracts"
            )

            return None

        candidates = []

        for item in items:

            if not is_nifty_future(item):
                continue

            expiry = extract_expiry(
                item
            )

            if expiry is None:
                continue

            # Ignore expired contracts
            if expiry < today:
                continue

            token = (
                item.get("symboltoken")
                or item.get("token")
            )

            symbol = (
                item.get("tradingsymbol")
                or item.get("symbol")
            )

            if not token or not symbol:
                continue

            candidates.append(
                (
                    expiry,
                    str(symbol),
                    str(token)
                )
            )

        if not candidates:

            logging.warning(
                "No active NIFTY Futures contract found"
            )

            return None

        # Nearest expiry
        candidates.sort(
            key=lambda x: (
                x[0],
                x[1]
            )
        )

        expiry, symbol, token = (
            candidates[0]
        )

        contract = {

            "exchange":
                "NFO",

            "tradingsymbol":
                symbol,

            "symboltoken":
                token,

            "expiry":
                expiry.isoformat(),

            "instrument":
                "NIFTY_FUTURES"
        }

        logging.info(
            "🟢 NIFTY FUTURES resolved: %s | token=%s | expiry=%s",
            symbol,
            token,
            expiry
        )

        return contract

    except Exception as exc:

        logging.error(
            "NIFTY futures resolution error: %s",
            exc
        )

        return None


# ============================================================
# RESOLVE OPTION
# ============================================================

def resolve_option(
    api,
    strike,
    opt_type,
    today
):

    try:

        logging.info(
            "Resolving option: NIFTY %.0f %s",
            float(strike),
            opt_type
        )

        response = api.searchScrip(
            "NFO",
            "NIFTY"
        )

        if not response:

            logging.warning(
                "searchScrip returned empty response"
            )

            return None

        if not response.get("status"):

            logging.warning(
                "searchScrip unsuccessful: %s",
                response
            )

            return None

        items = response.get(
            "data"
        ) or []

        if not items:

            logging.warning(
                "searchScrip returned no contracts"
            )

            return None

        candidates = []

        for item in items:

            if option_type(item) != opt_type:
                continue

            s = strike_value(item)

            if s is None:
                continue

            if abs(
                s - float(strike)
            ) > 0.01:

                continue

            expiry = extract_expiry(
                item
            )

            if (
                expiry is not None
                and expiry < today
            ):

                continue

            token = (
                item.get("symboltoken")
                or item.get("token")
            )

            symbol = (
                item.get("tradingsymbol")
                or item.get("symbol")
            )

            if not token or not symbol:
                continue

            candidates.append(
                (
                    expiry or today,
                    str(symbol),
                    str(token)
                )
            )

        if not candidates:

            logging.warning(
                "No valid option found: %.0f:%s",
                float(strike),
                opt_type
            )

            return None

        candidates.sort(
            key=lambda x: (
                x[0],
                x[1]
            )
        )

        expiry, symbol, token = (
            candidates[0]
        )

        contract = {

            "exchange":
                "NFO",

            "tradingsymbol":
                symbol,

            "symboltoken":
                token,

            "strike":
                float(strike),

            "option_type":
                opt_type,

            "expiry":
                expiry.isoformat()
                if expiry
                else None,
        }

        logging.info(
            "🟢 Option resolved: %s | token=%s | expiry=%s",
            symbol,
            token,
            expiry
        )

        return contract

    except Exception as exc:

        logging.error(
            "Option resolution error: %s",
            exc
        )

        return None


# ============================================================
# CANDLE KEY
# ============================================================

def candle_key(value):

    try:

        dt = datetime.fromisoformat(
            str(value)
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=IST
            )

        dt = dt.astimezone(
            IST
        )

        return dt.strftime(
            "%Y-%m-%d %H:%M"
        )

    except Exception:

        return str(value)


# ============================================================
# MERGE SPOT OHLC + FUTURES VOLUME
# ============================================================

def merge_spot_and_futures(
    spot_candles,
    futures_candles
):

    if not spot_candles:

        return []

    futures_volume = {}

    for row in futures_candles or []:

        if len(row) < 6:
            continue

        try:

            key = candle_key(
                row[0]
            )

            volume = float(
                row[5]
            )

            futures_volume[key] = volume

        except Exception:

            continue

    merged = []

    matched = 0

    for row in spot_candles:

        if len(row) < 6:
            continue

        try:

            key = candle_key(
                row[0]
            )

            if key in futures_volume:

                volume = futures_volume[key]
                matched += 1

            else:

                # If futures volume is not available
                # for this candle, preserve 0.
                volume = 0.0

            merged.append(
                [
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    volume
                ]
            )

        except Exception:

            continue

    logging.info(
        "🧩 Spot/Futures merge: %d/%d candles matched with Futures volume",
        matched,
        len(merged)
    )

    return merged


# ============================================================
# MAIN WORKER
# ============================================================

def start_backend_factory():

    from SmartApi import SmartConnect

    from SmartApi.smartWebSocketV2 import (
        SmartWebSocketV2
    )

    while True:

        sws = None

        try:

            # ------------------------------------------------
            # ENV CHECK
            # ------------------------------------------------

            if not all(
                (
                    CID,
                    AKEY,
                    PIN,
                    TKEY
                )
            ):

                raise RuntimeError(
                    "ANGEL_CLIENT_CODE/API_KEY/PIN/"
                    "TOTP_SECRET environment variables "
                    "are required"
                )

            logging.info(
                "Angel One live data worker starting..."
            )

            # ------------------------------------------------
            # API
            # ------------------------------------------------

            api = SmartConnect(
                api_key=AKEY,
                timeout=15
            )

            tok = pyotp.TOTP(
                TKEY.replace(
                    " ",
                    ""
                ).strip().upper()
            ).now()

            session = api.generateSession(
                CID,
                PIN,
                tok
            )

            if (
                not session
                or not session.get("status")
            ):

                raise RuntimeError(
                    f"API session failed: {session}"
                )

            auth_token = (
                session["data"]["jwtToken"]
            )

            feed_token = (
                api.getfeedToken()
            )

            if not feed_token:

                raise RuntimeError(
                    "Unable to obtain SmartAPI feed token"
                )

            logging.info(
                "🟢 Angel One API session ready"
            )

            # ------------------------------------------------
            # CANDLE CACHE
            # ------------------------------------------------

            cached_candles = []

            last_candle_fetch = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            candle_retry_after = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # ------------------------------------------------
            # FUTURES STATE
            # ------------------------------------------------

            futures_contract = None

            last_futures_resolve = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            futures_retry_after = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # ------------------------------------------------
            # OPTION STATE
            # ------------------------------------------------

            option_contract = None

            option_hint_key = None

            # ------------------------------------------------
            # TICKS
            # ------------------------------------------------

            tick_lock = threading.Lock()

            ticks = {

                "nifty":
                    None,

                "option":
                    None
            }

            # ------------------------------------------------
            # WEBSOCKET
            # ------------------------------------------------

            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token
            )

            websocket_connected = False

            # ------------------------------------------------
            # WEBSOCKET OPEN
            # ------------------------------------------------

            def on_open(wsapp):

                nonlocal websocket_connected

                websocket_connected = True

                logging.info(
                    "🟢 SmartWebSocketV2 CONNECTED"
                )

                try:

                    # ----------------------------------------
                    # NIFTY SPOT
                    # ----------------------------------------

                    sws.subscribe(
                        "nifty-algo",
                        1,
                        [
                            {
                                "exchangeType": 1,

                                "tokens": [
                                    str(
                                        NIFTY_SPOT_TOKEN
                                    )
                                ]
                            }
                        ]
                    )

                    logging.info(
                        "🟢 NIFTY subscription active"
                    )

                    # ----------------------------------------
                    # OPTION
                    # ----------------------------------------

                    if option_contract:

                        sws.subscribe(
                            "option-algo",
                            1,
                            [
                                {
                                    "exchangeType": 2,

                                    "tokens": [
                                        str(
                                            option_contract[
                                                "symboltoken"
                                            ]
                                        )
                                    ]
                                }
                            ]
                        )

                except Exception as exc:

                    logging.error(
                        "WebSocket subscribe error: %s",
                        exc
                    )

            # ------------------------------------------------
            # WEBSOCKET DATA
            # ------------------------------------------------

            def on_data(
                wsapp,
                message
            ):

                try:

                    if not isinstance(
                        message,
                        dict
                    ):

                        return

                    token = str(
                        message.get(
                            "token",
                            ""
                        )
                    )

                    price_raw = message.get(
                        "last_traded_price"
                    )

                    if price_raw is None:
                        return

                    price = (
                        float(price_raw)
                        / 100.0
                    )

                    ts_raw = message.get(
                        "exchange_timestamp"
                    )

                    if ts_raw:

                        try:

                            ts = (
                                datetime
                                .fromtimestamp(
                                    float(ts_raw)
                                    / 1000.0,
                                    tz=timezone.utc
                                )
                                .astimezone(
                                    IST
                                )
                            )

                        except Exception:

                            ts = now_ist()

                    else:

                        ts = now_ist()

                    with tick_lock:

                        # ------------------------------------
                        # NIFTY SPOT
                        # ------------------------------------

                        if (
                            token
                            == str(
                                NIFTY_SPOT_TOKEN
                            )
                        ):

                            ticks["nifty"] = {

                                "ltp":
                                    price,

                                "timestamp":
                                    ts.isoformat()
                            }

                            logging.info(
                                "🟢 NIFTY TICK: %.2f",
                                price
                            )

                        # ------------------------------------
                        # OPTION
                        # ------------------------------------

                        elif (
                            option_contract
                            and
                            token
                            ==
                            str(
                                option_contract[
                                    "symboltoken"
                                ]
                            )
                        ):

                            ticks["option"] = {

                                "ltp":
                                    price,

                                "timestamp":
                                    ts.isoformat()
                            }

                            logging.info(
                                "🟢 OPTION TICK %s: %.2f",
                                option_contract[
                                    "tradingsymbol"
                                ],
                                price
                            )

                except Exception as exc:

                    logging.debug(
                        "Tick parse error: %s",
                        exc
                    )

            # ------------------------------------------------
            # WEBSOCKET ERROR
            # ------------------------------------------------

            def on_error(
                wsapp,
                error
            ):

                logging.error(
                    "🔴 SmartWebSocketV2 ERROR: %s",
                    error
                )

            # ------------------------------------------------
            # WEBSOCKET CLOSE
            # ------------------------------------------------

            def on_close(wsapp):

                nonlocal websocket_connected

                websocket_connected = False

                logging.warning(
                    "🟠 SmartWebSocketV2 CLOSED"
                )

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            # ------------------------------------------------
            # START WEBSOCKET
            # ------------------------------------------------

            ws_thread = threading.Thread(
                target=sws.connect,
                daemon=True
            )

            ws_thread.start()

            logging.info(
                "🟢 Live WebSocket worker started"
            )

            # =================================================
            # MAIN LOOP
            # =================================================

            while True:

                now_dt = now_ist()

                try:

                    # -----------------------------------------
                    # READ TICKS
                    # -----------------------------------------

                    with tick_lock:

                        nifty_tick = (
                            dict(
                                ticks["nifty"]
                            )
                            if ticks["nifty"]
                            else None
                        )

                        option_tick = (
                            dict(
                                ticks["option"]
                            )
                            if ticks["option"]
                            else None
                        )

                    # -----------------------------------------
                    # WAIT FOR NIFTY WEBSOCKET
                    # -----------------------------------------

                    if nifty_tick is None:

                        time.sleep(
                            0.5
                        )

                        continue

                    spot = float(
                        nifty_tick["ltp"]
                    )

                    # =================================================
                    # RESOLVE NIFTY FUTURES
                    # =================================================
                    #
                    # Resolve initially.
                    # Re-check approximately every 30 minutes.
                    #
                    # This also handles expiry rollover.
                    # =================================================

                    futures_due = (

                        futures_contract is None

                        or (

                            (
                                now_dt
                                -
                                last_futures_resolve
                            ).total_seconds()
                            >= 1800
                        )
                    )

                    futures_retry_allowed = (

                        now_dt
                        >= futures_retry_after
                    )

                    if (
                        futures_due
                        and
                        futures_retry_allowed
                    ):

                        resolved_future = (
                            resolve_nifty_future(
                                api,
                                now_dt.date()
                            )
                        )

                        if resolved_future:

                            old_future_symbol = (

                                futures_contract[
                                    "tradingsymbol"
                                ]
                                if futures_contract
                                else None
                            )

                            futures_contract = (
                                resolved_future
                            )

                            last_futures_resolve = (
                                now_dt
                            )

                            futures_retry_after = (
                                now_dt
                            )

                            if (
                                old_future_symbol
                                !=
                                futures_contract[
                                    "tradingsymbol"
                                ]
                            ):

                                logging.info(
                                    "🔄 Active Futures changed: %s",
                                    futures_contract[
                                        "tradingsymbol"
                                    ]
                                )

                        else:

                            futures_retry_after = (
                                now_dt
                                +
                                timedelta(
                                    seconds=60
                                )
                            )

                    # =================================================
                    # HISTORICAL CANDLES
                    # =================================================

                    candle_due = (

                        not cached_candles

                        or (

                            (
                                now_dt
                                -
                                last_candle_fetch
                            ).total_seconds()
                            >= 60
                        )
                    )

                    retry_allowed = (

                        now_dt
                        >= candle_retry_after
                    )

                    if (
                        candle_due
                        and
                        retry_allowed
                    ):

                        # ---------------------------------------------
                        # 2 DAYS WINDOW
                        # ---------------------------------------------

                        from_d = (

                            now_dt
                            -
                            timedelta(
                                days=2
                            )
                        ).strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        to_d = (
                            now_dt.strftime(
                                "%Y-%m-%d %H:%M"
                            )
                        )

                        # ---------------------------------------------
                        # SPOT CANDLES
                        # ---------------------------------------------

                        spot_candles = []

                        try:

                            logging.info(
                                "Fetching NIFTY SPOT 5-min candles..."
                            )

                            spot_res = (
                                api.getCandleData(
                                    {
                                        "exchange":
                                            "NSE",

                                        "symboltoken":
                                            NIFTY_SPOT_TOKEN,

                                        "interval":
                                            "FIVE_MINUTE",

                                        "fromdate":
                                            from_d,

                                        "todate":
                                            to_d,
                                    }
                                )
                            )

                            if (
                                spot_res
                                and
                                spot_res.get(
                                    "status"
                                )
                                and
                                spot_res.get(
                                    "data"
                                )
                            ):

                                spot_candles = (
                                    spot_res["data"]
                                )

                                logging.info(
                                    "🟢 NIFTY SPOT candles: %d",
                                    len(
                                        spot_candles
                                    )
                                )

                            else:

                                logging.warning(
                                    "NIFTY SPOT candle API returned no data"
                                )

                        except Exception as spot_err:

                            logging.warning(
                                "NIFTY SPOT candle API error: %s",
                                spot_err
                            )

                        # ---------------------------------------------
                        # FUTURES CANDLES
                        # ---------------------------------------------

                        futures_candles = []

                        if futures_contract:

                            try:

                                logging.info(
                                    "Fetching NIFTY FUTURES 5-min candles: %s",
                                    futures_contract[
                                        "tradingsymbol"
                                    ]
                                )

                                future_res = (
                                    api.getCandleData(
                                        {
                                            "exchange":
                                                "NFO",

                                            "symboltoken":
                                                str(
                                                    futures_contract[
                                                        "symboltoken"
                                                    ]
                                                ),

                                            "interval":
                                                "FIVE_MINUTE",

                                            "fromdate":
                                                from_d,

                                            "todate":
                                                to_d,
                                        }
                                    )
                                )

                                if (
                                    future_res
                                    and
                                    future_res.get(
                                        "status"
                                    )
                                    and
                                    future_res.get(
                                        "data"
                                    )
                                ):

                                    futures_candles = (
                                        future_res["data"]
                                    )

                                    logging.info(
                                        "🟢 NIFTY FUTURES candles: %d",
                                        len(
                                            futures_candles
                                        )
                                    )

                                else:

                                    logging.warning(
                                        "NIFTY FUTURES candle API returned no data"
                                    )

                            except Exception as future_err:

                                logging.warning(
                                    "NIFTY FUTURES candle API error: %s",
                                    future_err
                                )

                        # ---------------------------------------------
                        # MERGE
                        # ---------------------------------------------

                        if (
                            len(spot_candles)
                            >=
                            22
                        ):

                            merged_candles = (
                                merge_spot_and_futures(
                                    spot_candles,
                                    futures_candles
                                )
                            )

                            if (
                                len(
                                    merged_candles
                                )
                                >=
                                22
                            ):

                                cached_candles = (
                                    merged_candles
                                )

                                logging.info(
                                    "🟢 Combined candles updated: %d | Volume source: NIFTY FUTURES",
                                    len(
                                        cached_candles
                                    )
                                )

                            else:

                                logging.warning(
                                    "Merged candle count too low: %d",
                                    len(
                                        merged_candles
                                    )
                                )

                        else:

                            logging.warning(
                                "Spot candle count too low: %d",
                                len(
                                    spot_candles
                                )
                            )

                        # ---------------------------------------------
                        # DO NOT DELETE OLD CACHE
                        # ---------------------------------------------

                        last_candle_fetch = (
                            now_dt
                        )

                        candle_retry_after = (
                            now_dt
                            +
                            timedelta(
                                seconds=30
                            )
                        )

                    # =================================================
                    # READ STRATEGY SIGNAL
                    # =================================================

                    desired_hint = None

                    if os.path.exists(
                        "strategy_signal.json"
                    ):

                        try:

                            with open(
                                "strategy_signal.json",
                                "r"
                            ) as sf:

                                strat = json.load(
                                    sf
                                )

                            otype = strat.get(
                                "otype"
                            )

                            strike = strat.get(
                                "option_strike"
                            )

                            if (
                                otype
                                in (
                                    "CE",
                                    "PE"
                                )
                                and
                                strike
                                is not None
                            ):

                                desired_hint = (
                                    f"{int(float(strike))}:"
                                    f"{otype}"
                                )

                        except Exception as signal_err:

                            logging.debug(
                                "Strategy signal read error: %s",
                                signal_err
                            )

                    # =================================================
                    # RESOLVE OPTION ONLY WHEN HINT CHANGES
                    # =================================================

                    if (
                        desired_hint
                        and
                        desired_hint
                        !=
                        option_hint_key
                    ):

                        strike_s, opt_type = (
                            desired_hint.split(
                                ":",
                                1
                            )
                        )

                        resolved = resolve_option(
                            api,
                            float(strike_s),
                            opt_type,
                            now_dt.date()
                        )

                        if resolved:

                            old_token = (

                                option_contract[
                                    "symboltoken"
                                ]

                                if option_contract

                                else None
                            )

                            # -----------------------------------------
                            # UNSUBSCRIBE OLD OPTION
                            # -----------------------------------------

                            if old_token:

                                try:

                                    sws.unsubscribe(
                                        "option-algo",
                                        1,
                                        [
                                            {
                                                "exchangeType": 2,

                                                "tokens": [
                                                    str(
                                                        old_token
                                                    )
                                                ]
                                            }
                                        ]
                                    )

                                except Exception as unsub_err:

                                    logging.debug(
                                        "Option unsubscribe warning: %s",
                                        unsub_err
                                    )

                            # -----------------------------------------
                            # NEW CONTRACT
                            # -----------------------------------------

                            option_contract = (
                                resolved
                            )

                            option_hint_key = (
                                desired_hint
                            )

                            with tick_lock:

                                ticks[
                                    "option"
                                ] = None

                            # -----------------------------------------
                            # SUBSCRIBE NEW OPTION
                            # -----------------------------------------

                            try:

                                sws.subscribe(
                                    "option-algo",
                                    1,
                                    [
                                        {
                                            "exchangeType": 2,

                                            "tokens": [
                                                str(
                                                    option_contract[
                                                        "symboltoken"
                                                    ]
                                                )
                                            ]
                                        }
                                    ]
                                )

                                logging.info(
                                    "🟢 OPTION subscription active: %s",
                                    option_contract[
                                        "tradingsymbol"
                                    ]
                                )

                            except Exception as sub_err:

                                logging.warning(
                                    "Option subscribe error: %s",
                                    sub_err
                                )

                    # =================================================
                    # OPTION QUOTE
                    # =================================================

                    option_quote = None

                    if (
                        option_contract
                        and
                        option_tick
                    ):

                        option_quote = {

                            **option_contract,

                            "ltp":
                                float(
                                    option_tick[
                                        "ltp"
                                    ]
                                ),

                            "timestamp":
                                option_tick[
                                    "timestamp"
                                ]
                        }

                    # =================================================
                    # PUBLISH data_raw.json
                    # =================================================

                    payload = {

                        # -----------------------------------------
                        # LIVE SPOT
                        # -----------------------------------------

                        "live_spot":
                            spot,

                        "spot_timestamp":
                            nifty_tick.get(
                                "timestamp"
                            ),

                        # -----------------------------------------
                        # SPOT OHLC + FUTURES VOLUME
                        # -----------------------------------------

                        "candles":
                            cached_candles,

                        # -----------------------------------------
                        # VOLUME SOURCE
                        # -----------------------------------------

                        "volume_source":
                            (
                                "NIFTY_FUTURES"
                                if futures_contract
                                else
                                "UNAVAILABLE"
                            ),

                        # -----------------------------------------
                        # FUTURES CONTRACT
                        # -----------------------------------------

                        "futures_contract":
                            futures_contract,

                        # -----------------------------------------
                        # LAST UPDATE
                        # -----------------------------------------

                        "last_update":
                            now_dt.strftime(
                                "%H:%M:%S"
                            ),

                        # -----------------------------------------
                        # OPTION
                        # -----------------------------------------

                        "option_quote":
                            option_quote,

                        "websocket_connected":
                            websocket_connected,

                        "option_contract":
                            option_contract
                    }

                    atomic_write_json(
                        "data_raw.json",
                        payload
                    )

                except Exception as loop_err:

                    logging.exception(
                        "Worker loop error: %s",
                        loop_err
                    )

                # -------------------------------------------------
                # FAST LOOP
                # -------------------------------------------------

                time.sleep(
                    0.25
                )

        # =====================================================
        # CONNECTION FAILURE
        # =====================================================

        except Exception as conn_err:

            logging.error(
                "Critical worker error: %s. "
                "Restarting in 10 sec...",
                conn_err
            )

            try:

                if sws:

                    sws.close_connection()

            except Exception:

                pass

            time.sleep(
                10
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    start_backend_factory()
