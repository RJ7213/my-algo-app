# ============================================================
# data_worker.py
#
# Angel One ONLY data worker
#
# DATA SOURCES
# ------------------------------------------------------------
# NIFTY SPOT
#   -> WebSocket live LTP
#   -> REST historical OHLC
#
# NIFTY FUTURES
#   -> REST historical volume
#
# COMBINED CANDLES
#   -> SPOT OHLC
#   -> FUTURES VOLUME
#
# IMPORTANT
# ------------------------------------------------------------
# 1. No REST LTP polling.
# 2. NIFTY live LTP comes only from WebSocket.
# 3. Futures contract is resolved ONLY ONCE.
# 4. Option contract is resolved ONLY when strike/type changes.
# 5. Failed option resolution has cooldown.
# 6. Spot candle API failure NEVER clears old candles.
# 7. Futures volume is used as the volume source.
# 8. data_raw.json contains diagnostic volume information.
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


# NSE NIFTY SPOT
NIFTY_SPOT_TOKEN = os.getenv(
    "NIFTY_SPOT_TOKEN",
    "99926000"
)


IST = timezone(
    timedelta(
        hours=5,
        minutes=30
    )
)


# ============================================================
# SETTINGS
# ============================================================

# Historical candles
SPOT_FETCH_INTERVAL = 300       # 5 minutes
FUTURES_FETCH_INTERVAL = 60     # 1 minute

# Retry after REST failure
REST_RETRY_SECONDS = 60

# Option resolution retry
OPTION_RETRY_SECONDS = 60

# Historical lookback
HISTORY_DAYS = 2

# Minimum candles
MIN_CANDLES = 22


# ============================================================
# TIME
# ============================================================

def now_ist():
    return datetime.now(IST)


# ============================================================
# ATOMIC JSON WRITE
# ============================================================

def atomic_write_json(path, payload):

    tmp = f"{path}.tmp"

    with open(tmp, "w") as f:

        json.dump(
            payload,
            f,
            separators=(",", ":")
        )

    os.replace(tmp, path)


# ============================================================
# EXPIRY
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
# STRIKE
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

            # Angel sometimes gives strike * 100
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
# FIND NIFTY FUTURES
# ============================================================

def resolve_nifty_future(
    api,
    today
):

    try:

        logging.info(
            "Resolving NIFTY FUTURES contract..."
        )

        response = api.searchScrip(
            "NFO",
            "NIFTY"
        )

        if not response:

            logging.warning(
                "Futures search returned empty response"
            )

            return None

        if not response.get("status"):

            logging.warning(
                "Futures search unsuccessful: %s",
                response
            )

            return None

        items = response.get(
            "data"
        ) or []

        candidates = []

        for item in items:

            symbol = str(
                item.get(
                    "tradingsymbol",
                    ""
                )
            ).upper()

            # Only NIFTY FUT
            if not symbol.startswith("NIFTY"):
                continue

            if not symbol.endswith("FUT"):
                continue

            # Avoid NIFTYNXT50 / FPI etc.
            if symbol.startswith("NIFTYNXT50"):
                continue

            if symbol.startswith("NIFTYFPI"):
                continue

            expiry = extract_expiry(
                item
            )

            if expiry is None:
                continue

            if expiry < today:
                continue

            token = (
                item.get("symboltoken")
                or item.get("token")
            )

            if not token:
                continue

            candidates.append(
                (
                    expiry,
                    symbol,
                    str(token)
                )
            )

        if not candidates:

            logging.warning(
                "No valid NIFTY FUTURES contract found"
            )

            return None

        candidates.sort(
            key=lambda x: (
                x[0],
                x[1]
            )
        )

        expiry, symbol, token = candidates[0]

        contract = {

            "exchange":
                "NFO",

            "tradingsymbol":
                symbol,

            "symboltoken":
                token,

            "expiry":
                expiry.isoformat()
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
            "Futures resolution error: %s",
            exc
        )

        return None


# ============================================================
# OPTION RESOLUTION
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
                "searchScrip unsuccessful"
            )

            return None

        items = response.get(
            "data"
        ) or []

        candidates = []

        for item in items:

            symbol = str(
                item.get(
                    "tradingsymbol",
                    ""
                )
            ).upper()

            # Only NIFTY options
            if not symbol.startswith("NIFTY"):
                continue

            if symbol.startswith("NIFTYNXT50"):
                continue

            if symbol.startswith("NIFTYFPI"):
                continue

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

            if expiry is not None:

                if expiry < today:
                    continue

            token = (
                item.get("symboltoken")
                or item.get("token")
            )

            symbol_name = (
                item.get("tradingsymbol")
                or item.get("symbol")
            )

            if not token or not symbol_name:
                continue

            candidates.append(
                (
                    expiry or today,
                    str(symbol_name),
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

        expiry, symbol, token = candidates[0]

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
                else None
        }

        logging.info(
            "🟢 OPTION resolved: %s | token=%s | expiry=%s",
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
# NORMALIZE CANDLE
# ============================================================

def normalize_candle(row):

    try:

        if not row or len(row) < 6:
            return None

        return [

            str(row[0]),

            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),

            float(row[5])
            if row[5] is not None
            else 0.0
        ]

    except Exception:

        return None


# ============================================================
# MERGE SPOT OHLC + FUTURES VOLUME
# ============================================================

def merge_candles(
    spot_candles,
    futures_candles
):

    if not spot_candles:
        return []

    if not futures_candles:
        return []

    futures_map = {}

    for row in futures_candles:

        c = normalize_candle(row)

        if not c:
            continue

        timestamp = str(c[0])

        futures_map[timestamp] = c[5]

    combined = []

    matched = 0

    for row in spot_candles:

        c = normalize_candle(row)

        if not c:
            continue

        timestamp = str(c[0])

        if timestamp not in futures_map:
            continue

        combined.append(
            [
                timestamp,
                c[1],       # spot open
                c[2],       # spot high
                c[3],       # spot low
                c[4],       # spot close
                futures_map[timestamp]
            ]
        )

        matched += 1

    logging.info(
        "🧩 Spot/Futures merge: %d/%d candles matched with Futures volume",
        matched,
        len(spot_candles)
    )

    return combined


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
                    "TOTP_SECRET environment variables required"
                )

            logging.info(
                "Angel One live data worker starting..."
            )

            # ------------------------------------------------
            # LOGIN
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
                    "Unable to obtain feed token"
                )

            logging.info(
                "🟢 Angel One API session ready"
            )

            # ------------------------------------------------
            # CANDLE CACHE
            # ------------------------------------------------

            spot_candles_cache = []

            futures_candles_cache = []

            combined_candles_cache = []

            last_spot_fetch = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            last_futures_fetch = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            spot_retry_after = (
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
            # FUTURES CONTRACT
            # ------------------------------------------------

            futures_contract = None

            # ------------------------------------------------
            # OPTION STATE
            # ------------------------------------------------

            option_contract = None

            option_hint_key = None

            option_retry_after = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # ------------------------------------------------
            # TICKS
            # ------------------------------------------------

            tick_lock = threading.Lock()

            ticks = {

                "nifty": None,

                "option": None
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

            # =================================================
            # ON OPEN
            # =================================================

            def on_open(wsapp):

                nonlocal websocket_connected

                websocket_connected = True

                logging.info(
                    "🟢 SmartWebSocketV2 CONNECTED"
                )

                try:

                    # -----------------------------------------
                    # NIFTY SPOT
                    # -----------------------------------------

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

                    # -----------------------------------------
                    # OPTION
                    # -----------------------------------------

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

            # =================================================
            # ON DATA
            # =================================================

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
                                .astimezone(IST)
                            )

                        except Exception:

                            ts = now_ist()

                    else:

                        ts = now_ist()

                    with tick_lock:

                        # ------------------------------------
                        # NIFTY
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
                            and token
                            == str(
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

            # =================================================
            # ON ERROR
            # =================================================

            def on_error(
                wsapp,
                error
            ):

                logging.error(
                    "🔴 SmartWebSocketV2 ERROR: %s",
                    error
                )

            # =================================================
            # ON CLOSE
            # =================================================

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
            # START WS
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

                # ------------------------------------------------
                # READ TICKS
                # ------------------------------------------------

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

                # ------------------------------------------------
                # WAIT NIFTY WS
                # ------------------------------------------------

                if nifty_tick is None:

                    time.sleep(0.5)

                    continue

                spot = float(
                    nifty_tick["ltp"]
                )

                # =================================================
                # RESOLVE FUTURES ONLY ONCE
                # =================================================

                if futures_contract is None:

                    futures_contract = (
                        resolve_nifty_future(
                            api,
                            now_dt.date()
                        )
                    )

                    if futures_contract:

                        logging.info(
                            "🟢 Futures volume source active: %s",
                            futures_contract[
                                "tradingsymbol"
                            ]
                        )

                    else:

                        logging.warning(
                            "⚠️ Futures contract not resolved yet"
                        )

                # =================================================
                # DATE RANGE
                # =================================================

                from_d = (
                    now_dt
                    - timedelta(
                        days=HISTORY_DAYS
                    )
                ).strftime(
                    "%Y-%m-%d %H:%M"
                )

                to_d = (
                    now_dt.strftime(
                        "%Y-%m-%d %H:%M"
                    )
                )

                # =================================================
                # SPOT CANDLE FETCH
                #
                # ONLY EVERY 5 MINUTES
                #
                # If rate-limited:
                # KEEP OLD CACHE
                # =================================================

                spot_due = (

                    not spot_candles_cache

                    or (
                        now_dt
                        - last_spot_fetch
                    ).total_seconds()
                    >= SPOT_FETCH_INTERVAL
                )

                spot_retry_allowed = (
                    now_dt
                    >= spot_retry_after
                )

                if (
                    spot_due
                    and spot_retry_allowed
                ):

                    try:

                        logging.info(
                            "Fetching NIFTY SPOT 5-min candles..."
                        )

                        res = api.getCandleData(
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
                                    to_d
                            }
                        )

                        if (
                            res
                            and res.get("status")
                            and res.get("data")
                        ):

                            new_spot = (
                                res["data"]
                            )

                            if len(
                                new_spot
                            ) >= MIN_CANDLES:

                                spot_candles_cache = (
                                    new_spot
                                )

                                logging.info(
                                    "🟢 NIFTY SPOT candles: %d",
                                    len(
                                        spot_candles_cache
                                    )
                                )

                            else:

                                logging.warning(
                                    "Spot candle count too low: %d",
                                    len(new_spot)
                                )

                        else:

                            logging.warning(
                                "NIFTY SPOT candle API returned no data"
                            )

                        last_spot_fetch = now_dt

                        spot_retry_after = (
                            now_dt
                            + timedelta(
                                seconds=REST_RETRY_SECONDS
                            )
                        )

                    except Exception as spot_err:

                        logging.warning(
                            "NIFTY SPOT candle API error: %s",
                            spot_err
                        )

                        # IMPORTANT:
                        # NEVER erase old spot cache

                        last_spot_fetch = now_dt

                        spot_retry_after = (
                            now_dt
                            + timedelta(
                                seconds=REST_RETRY_SECONDS
                            )
                        )

                # =================================================
                # FUTURES CANDLE FETCH
                #
                # VOLUME SOURCE
                # =================================================

                futures_due = (

                    futures_contract is not None

                    and (
                        not futures_candles_cache

                        or (
                            now_dt
                            - last_futures_fetch
                        ).total_seconds()
                        >= FUTURES_FETCH_INTERVAL
                    )
                )

                futures_retry_allowed = (
                    now_dt
                    >= futures_retry_after
                )

                if (
                    futures_due
                    and futures_retry_allowed
                ):

                    try:

                        logging.info(
                            "Fetching NIFTY FUTURES 5-min candles: %s",
                            futures_contract[
                                "tradingsymbol"
                            ]
                        )

                        res = api.getCandleData(
                            {
                                "exchange":
                                    "NFO",

                                "symboltoken":
                                    futures_contract[
                                        "symboltoken"
                                    ],

                                "interval":
                                    "FIVE_MINUTE",

                                "fromdate":
                                    from_d,

                                "todate":
                                    to_d
                            }
                        )

                        if (
                            res
                            and res.get("status")
                            and res.get("data")
                        ):

                            new_futures = (
                                res["data"]
                            )

                            if len(
                                new_futures
                            ) >= MIN_CANDLES:

                                futures_candles_cache = (
                                    new_futures
                                )

                                logging.info(
                                    "🟢 NIFTY FUTURES candles: %d",
                                    len(
                                        futures_candles_cache
                                    )
                                )

                            else:

                                logging.warning(
                                    "Futures candle count too low: %d",
                                    len(new_futures)
                                )

                        else:

                            logging.warning(
                                "NIFTY FUTURES candle API returned no data"
                            )

                        last_futures_fetch = now_dt

                        futures_retry_after = (
                            now_dt
                            + timedelta(
                                seconds=REST_RETRY_SECONDS
                            )
                        )

                    except Exception as futures_err:

                        logging.warning(
                            "NIFTY FUTURES candle API error: %s",
                            futures_err
                        )

                        # NEVER clear old futures cache

                        last_futures_fetch = now_dt

                        futures_retry_after = (
                            now_dt
                            + timedelta(
                                seconds=REST_RETRY_SECONDS
                            )
                        )

                # =================================================
                # BUILD COMBINED CANDLES
                # =================================================

                if (
                    len(spot_candles_cache)
                    >= MIN_CANDLES

                    and len(futures_candles_cache)
                    >= MIN_CANDLES
                ):

                    try:

                        merged = merge_candles(
                            spot_candles_cache,
                            futures_candles_cache
                        )

                        if len(merged) >= MIN_CANDLES:

                            combined_candles_cache = (
                                merged
                            )

                            logging.info(
                                "🟢 Combined candles updated: %d | Volume source: NIFTY FUTURES",
                                len(
                                    combined_candles_cache
                                )
                            )

                    except Exception as merge_err:

                        logging.warning(
                            "Candle merge error: %s",
                            merge_err
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
                            otype in (
                                "CE",
                                "PE"
                            )
                            and strike is not None
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
                # OPTION RESOLUTION
                #
                # ONLY WHEN:
                #     desired_hint changes
                #
                # OR previous resolution failed and cooldown passed
                # =================================================

                if desired_hint:

                    should_resolve = False

                    # New strike/type
                    if desired_hint != option_hint_key:

                        should_resolve = True

                    # Same failed hint -> retry only after cooldown
                    elif (
                        option_contract is None
                        and now_dt >= option_retry_after
                    ):

                        should_resolve = True

                    if should_resolve:

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

                            # --------------------------------
                            # Unsubscribe old option
                            # --------------------------------

                            if (
                                old_token
                                and str(old_token)
                                != str(
                                    resolved[
                                        "symboltoken"
                                    ]
                                )
                            ):

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

                                except Exception:

                                    pass

                            option_contract = (
                                resolved
                            )

                            option_hint_key = (
                                desired_hint
                            )

                            option_retry_after = (
                                now_dt
                                + timedelta(
                                    seconds=OPTION_RETRY_SECONDS
                                )
                            )

                            with tick_lock:

                                ticks["option"] = None

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

                        else:

                            # IMPORTANT:
                            # Keep desired hint but don't hammer searchScrip

                            option_retry_after = (
                                now_dt
                                + timedelta(
                                    seconds=OPTION_RETRY_SECONDS
                                )
                            )

                            logging.warning(
                                "⚠️ Option resolution failed. "
                                "Retry after %d sec.",
                                OPTION_RETRY_SECONDS
                            )

                # =================================================
                # OPTION QUOTE
                # =================================================

                option_quote = None

                if (
                    option_contract
                    and option_tick
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
                # VOLUME DIAGNOSTICS
                # =================================================

                volume_source = (
                    "NIFTY FUTURES"
                    if combined_candles_cache
                    else "NONE"
                )

                current_volume = 0.0

                volume_average = 0.0

                volume_ratio = 0.0

                volume_candle_time = None

                if (
                    len(
                        combined_candles_cache
                    ) >= 22
                ):

                    # Last completed candle = -2
                    signal_index = -2

                    current_volume = float(
                        combined_candles_cache[
                            signal_index
                        ][5]
                    )

                    volume_candle_time = (
                        combined_candles_cache[
                            signal_index
                        ][0]
                    )

                    # Previous 20 completed candles
                    volume_window = [

                        float(row[5])

                        for row in
                        combined_candles_cache[
                            -22:-2
                        ]

                        if row[5] is not None
                    ]

                    if volume_window:

                        volume_average = (
                            sum(volume_window)
                            / len(volume_window)
                        )

                    if volume_average > 0:

                        volume_ratio = (
                            current_volume
                            / volume_average
                        )

                # =================================================
                # PUBLISH
                # =================================================

                payload = {

                    "live_spot":
                        spot,

                    "spot_timestamp":
                        nifty_tick.get(
                            "timestamp"
                        ),

                    "candles":
                        combined_candles_cache,

                    "last_update":
                        now_dt.strftime(
                            "%H:%M:%S"
                        ),

                    "option_quote":
                        option_quote,

                    "websocket_connected":
                        websocket_connected,

                    "option_contract":
                        option_contract,

                    # -----------------------------------------
                    # FUTURES
                    # -----------------------------------------

                    "futures_contract":
                        futures_contract,

                    "volume_source":
                        volume_source,

                    "current_volume":
                        current_volume,

                    "volume_average":
                        round(
                            volume_average,
                            2
                        ),

                    "volume_ratio":
                        round(
                            volume_ratio,
                            2
                        ),

                    "volume_candle_time":
                        volume_candle_time,

                    # -----------------------------------------
                    # CACHE STATUS
                    # -----------------------------------------

                    "spot_candles_count":
                        len(
                            spot_candles_cache
                        ),

                    "futures_candles_count":
                        len(
                            futures_candles_cache
                        ),

                    "combined_candles_count":
                        len(
                            combined_candles_cache
                        )
                }

                atomic_write_json(
                    "data_raw.json",
                    payload
                )

                time.sleep(0.25)

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

            time.sleep(10)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    start_backend_factory()
