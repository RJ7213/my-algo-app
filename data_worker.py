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
#   -> REST historical OHLC + VOLUME
#
# COMBINED CANDLES
#   -> SPOT OHLC
#   -> FUTURES VOLUME
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
# NIFTY SPOT TOKEN
# ============================================================

NIFTY_SPOT_TOKEN = os.getenv(
    "NIFTY_SPOT_TOKEN",
    "99926000"
)


# ============================================================
# IST
# ============================================================

IST = timezone(
    timedelta(
        hours=5,
        minutes=30
    )
)


# ============================================================
# SETTINGS
# ============================================================

SPOT_FETCH_INTERVAL = 300       # 5 minutes
FUTURES_FETCH_INTERVAL = 60     # 1 minute

REST_RETRY_SECONDS = 60
OPTION_RETRY_SECONDS = 60

HISTORY_DAYS = 2

MIN_CANDLES = 22

LOOP_SLEEP = 0.25


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

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            payload,
            f,
            separators=(",", ":"),
            ensure_ascii=False
        )

    os.replace(
        tmp,
        path
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value):

    try:

        if value is None:
            return None

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return None


# ============================================================
# EXPIRY PARSER
# ============================================================
#
# IMPORTANT:
#
# NIFTY01SEP2624100PE
#       ^^^^^^^
#       01SEP26
#
# We must NOT accidentally parse:
#
# 01SEP2624
#
# ============================================================

def extract_expiry(item):

    # --------------------------------------------------------
    # 1. Angel explicit expiry field
    # --------------------------------------------------------

    raw = str(
        item.get(
            "expiry",
            ""
        ) or ""
    ).strip().upper()

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
                    raw,
                    fmt
                ).date()

            except ValueError:

                pass

    # --------------------------------------------------------
    # 2. Trading symbol
    #
    # Examples:
    #
    # NIFTY01SEP2624100PE
    # NIFTY01SEP2624100CE
    # NIFTY29SEP2624100PE
    # NIFTY29SEP26FUT
    #
    # --------------------------------------------------------

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        ) or ""
    ).upper().strip()

    if not symbol:
        return None

    # EXACTLY 2-digit year
    #
    # 01SEP26
    #
    m = re.search(
        r"(\d{1,2}[A-Z]{3}\d{2})(?=\d+(?:CE|PE)$|FUT$)",
        symbol
    )

    if m:

        expiry_text = m.group(1)

        try:

            return datetime.strptime(
                expiry_text,
                "%d%b%y"
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
            ) or ""
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
        ) or ""
    ).upper().strip()

    if symbol.endswith("CE"):
        return "CE"

    if symbol.endswith("PE"):
        return "PE"

    return ""


# ============================================================
# STRIKE
# ============================================================

def strike_value(item):

    # --------------------------------------------------------
    # 1. Angel strike field
    # --------------------------------------------------------

    for key in (
        "strike",
        "strikePrice",
        "strikeprice"
    ):

        raw = item.get(key)

        if raw in (
            None,
            "",
            "-"
        ):

            continue

        try:

            value = float(raw)

            # Angel sometimes gives strike * 100
            if value > 100000:
                value /= 100.0

            return value

        except (
            TypeError,
            ValueError
        ):

            pass

    # --------------------------------------------------------
    # 2. Parse directly from trading symbol
    #
    # NIFTY01SEP2624100PE
    #
    # expiry = 01SEP26
    # strike = 24100
    #
    # --------------------------------------------------------

    symbol = str(
        item.get(
            "tradingsymbol",
            ""
        ) or ""
    ).upper().strip()

    m = re.search(
        r"\d{1,2}[A-Z]{3}\d{2}(\d+(?:\.\d+)?)(?:CE|PE)$",
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
# NORMALIZE SYMBOL
# ============================================================

def normalize_symbol(symbol):

    return str(
        symbol or ""
    ).upper().strip()


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
                "Futures search unsuccessful"
            )

            return None

        items = response.get(
            "data"
        ) or []

        candidates = []

        for item in items:

            symbol = normalize_symbol(
                item.get(
                    "tradingsymbol"
                )
            )

            # ------------------------------------------------
            # ONLY NIFTY FUT
            # ------------------------------------------------

            if not symbol.startswith("NIFTY"):
                continue

            if not symbol.endswith("FUT"):
                continue

            # Reject NIFTYNXT50
            if symbol.startswith("NIFTYNXT50"):
                continue

            # Reject FPI
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

        # ----------------------------------------------------
        # NEAREST EXPIRY
        # ----------------------------------------------------

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

        strike = float(strike)

        opt_type = str(
            opt_type
        ).upper().strip()

        if opt_type not in (
            "CE",
            "PE"
        ):

            logging.warning(
                "Invalid option type: %s",
                opt_type
            )

            return None

        logging.info(
            "Resolving option: NIFTY %.0f %s",
            strike,
            opt_type
        )

        # ----------------------------------------------------
        # SEARCH
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # FILTER
        # ----------------------------------------------------

        for item in items:

            symbol = normalize_symbol(
                item.get(
                    "tradingsymbol"
                )
            )

            if not symbol:
                continue

            # ------------------------------------------------
            # NIFTY ONLY
            # ------------------------------------------------

            if not symbol.startswith("NIFTY"):
                continue

            # ------------------------------------------------
            # REJECT OTHER INDEX / PRODUCTS
            # ------------------------------------------------

            if symbol.startswith(
                "NIFTYNXT50"
            ):

                continue

            if symbol.startswith(
                "NIFTYFPI"
            ):

                continue

            # ------------------------------------------------
            # MUST BE OPTION
            # ------------------------------------------------

            if not symbol.endswith(
                opt_type
            ):

                continue

            # ------------------------------------------------
            # OPTION TYPE
            # ------------------------------------------------

            if option_type(item) != opt_type:
                continue

            # ------------------------------------------------
            # EXPIRY
            # ------------------------------------------------

            expiry = extract_expiry(
                item
            )

            if expiry is None:
                continue

            if expiry < today:
                continue

            # ------------------------------------------------
            # STRIKE
            # ------------------------------------------------

            parsed_strike = strike_value(
                item
            )

            if parsed_strike is None:
                continue

            if abs(
                parsed_strike - strike
            ) > 0.01:

                continue

            # ------------------------------------------------
            # TOKEN
            # ------------------------------------------------

            token = (
                item.get(
                    "symboltoken"
                )
                or item.get(
                    "token"
                )
            )

            if not token:
                continue

            # ------------------------------------------------
            # EXTRA DIRECT SYMBOL CHECK
            # ------------------------------------------------

            # Example:
            #
            # NIFTY01SEP2624100PE
            #
            # We extract strike again from the symbol.
            #

            symbol_match = re.search(
                r"\d{1,2}[A-Z]{3}\d{2}(\d+(?:\.\d+)?)(CE|PE)$",
                symbol
            )

            if not symbol_match:
                continue

            try:

                symbol_strike = float(
                    symbol_match.group(1)
                )

            except ValueError:

                continue

            if abs(
                symbol_strike - strike
            ) > 0.01:

                continue

            candidates.append(
                {
                    "expiry":
                        expiry,

                    "tradingsymbol":
                        symbol,

                    "symboltoken":
                        str(token)
                }
            )

        # ----------------------------------------------------
        # NO MATCH
        # ----------------------------------------------------

        if not candidates:

            logging.warning(
                "No valid option found: %.0f:%s",
                strike,
                opt_type
            )

            return None

        # ----------------------------------------------------
        # NEAREST EXPIRY
        # ----------------------------------------------------

        candidates.sort(
            key=lambda x: (
                x["expiry"],
                x["tradingsymbol"]
            )
        )

        selected = candidates[0]

        contract = {

            "exchange":
                "NFO",

            "tradingsymbol":
                selected[
                    "tradingsymbol"
                ],

            "symboltoken":
                selected[
                    "symboltoken"
                ],

            "strike":
                strike,

            "option_type":
                opt_type,

            "expiry":
                selected[
                    "expiry"
                ].isoformat()
        }

        logging.info(
            "🟢 OPTION resolved: %s | token=%s | expiry=%s",
            contract["tradingsymbol"],
            contract["symboltoken"],
            contract["expiry"]
        )

        return contract

    except Exception as exc:

        logging.error(
            "Option resolution error: %s",
            exc
        )

        return None


# ============================================================
# CANDLE TIMESTAMP NORMALIZATION
# ============================================================

def normalize_timestamp(value):

    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    # --------------------------------------------------------
    # ISO format
    # --------------------------------------------------------

    try:

        dt = datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00"
            )
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=IST
            )

        else:

            dt = dt.astimezone(
                IST
            )

        # 5-minute candle key
        dt = dt.replace(
            second=0,
            microsecond=0
        )

        return dt.strftime(
            "%Y-%m-%d %H:%M"
        )

    except Exception:

        pass

    # --------------------------------------------------------
    # Angel formats
    # --------------------------------------------------------

    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%d-%m-%Y %H:%M:%S"
    ):

        try:

            dt = datetime.strptime(
                text,
                fmt
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=IST
                )

            else:

                dt = dt.astimezone(
                    IST
                )

            dt = dt.replace(
                second=0,
                microsecond=0
            )

            return dt.strftime(
                "%Y-%m-%d %H:%M"
            )

        except ValueError:

            pass

    return text


# ============================================================
# NORMALIZE CANDLE
# ============================================================

def normalize_candle(row):

    try:

        if not row or len(row) < 6:
            return None

        timestamp = normalize_timestamp(
            row[0]
        )

        if timestamp is None:
            return None

        return [

            timestamp,

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
# CLEAN CANDLE LIST
# ============================================================

def clean_candles(rows):

    result = []

    seen = set()

    for row in rows or []:

        candle = normalize_candle(
            row
        )

        if not candle:
            continue

        ts = candle[0]

        if ts in seen:
            continue

        seen.add(ts)

        result.append(
            candle
        )

    result.sort(
        key=lambda x: x[0]
    )

    return result


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

    # --------------------------------------------------------
    # Normalize both sides
    # --------------------------------------------------------

    spot_clean = clean_candles(
        spot_candles
    )

    futures_clean = clean_candles(
        futures_candles
    )

    # --------------------------------------------------------
    # Futures volume map
    # --------------------------------------------------------

    futures_map = {}

    for row in futures_clean:

        timestamp = row[0]

        futures_map[
            timestamp
        ] = row[5]

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------

    combined = []

    for row in spot_clean:

        timestamp = row[0]

        if timestamp not in futures_map:
            continue

        combined.append(
            [
                timestamp,

                row[1],       # Spot Open
                row[2],       # Spot High
                row[3],       # Spot Low
                row[4],       # Spot Close

                futures_map[
                    timestamp
                ]
            ]
        )

    logging.info(
        "🧩 Spot/Futures merge: %d/%d candles matched with Futures volume",
        len(combined),
        len(spot_clean)
    )

    return combined


# ============================================================
# READ STRATEGY SIGNAL
# ============================================================

def read_strategy_signal():

    path = "strategy_signal.json"

    if not os.path.exists(
        path
    ):

        return None

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as sf:

            strat = json.load(
                sf
            )

        otype = str(
            strat.get(
                "otype",
                ""
            )
        ).upper().strip()

        strike = strat.get(
            "option_strike"
        )

        if (
            otype not in (
                "CE",
                "PE"
            )
            or strike is None
        ):

            return None

        strike = float(
            strike
        )

        return (
            int(strike),
            otype
        )

    except Exception as exc:

        logging.debug(
            "Strategy signal read error: %s",
            exc
        )

        return None


# ============================================================
# SUBSCRIBE OPTION
# ============================================================

def subscribe_option(
    sws,
    contract
):

    try:

        sws.subscribe(
            "option-algo",
            1,
            [
                {
                    "exchangeType":
                        2,

                    "tokens": [
                        str(
                            contract[
                                "symboltoken"
                            ]
                        )
                    ]
                }
            ]
        )

        logging.info(
            "🟢 OPTION subscription active: %s | token=%s",
            contract[
                "tradingsymbol"
            ],
            contract[
                "symboltoken"
            ]
        )

        return True

    except Exception as exc:

        logging.warning(
            "Option subscribe error: %s",
            exc
        )

        return False


# ============================================================
# UNSUBSCRIBE OPTION
# ============================================================

def unsubscribe_option(
    sws,
    token
):

    if not token:
        return

    try:

        sws.unsubscribe(
            "option-algo",
            1,
            [
                {
                    "exchangeType":
                        2,

                    "tokens": [
                        str(token)
                    ]
                }
            ]
        )

        logging.info(
            "🟠 Old option unsubscribed: %s",
            token
        )

    except Exception as exc:

        logging.debug(
            "Option unsubscribe error: %s",
            exc
        )


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

            # =================================================
            # ENV CHECK
            # =================================================

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

            # =================================================
            # LOGIN
            # =================================================

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
                session[
                    "data"
                ][
                    "jwtToken"
                ]
            )

            feed_token = api.getfeedToken()

            if not feed_token:

                raise RuntimeError(
                    "Unable to obtain feed token"
                )

            logging.info(
                "🟢 Angel One API session ready"
            )

            # =================================================
            # CANDLE CACHE
            # =================================================

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

            # =================================================
            # FUTURES
            # =================================================

            futures_contract = None

            # =================================================
            # OPTION
            # =================================================

            option_contract = None

            option_hint_key = None

            option_retry_after = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # =================================================
            # TICKS
            # =================================================

            tick_lock = threading.Lock()

            ticks = {

                "nifty":
                    None,

                "option":
                    None
            }

            # =================================================
            # WEBSOCKET
            # =================================================

            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token
            )

            websocket_connected = False

            # -------------------------------------------------
            # Track subscribed option token
            # -------------------------------------------------

            subscribed_option_token = None

            # =================================================
            # ON OPEN
            # =================================================

            def on_open(wsapp):

                nonlocal websocket_connected
                nonlocal subscribed_option_token

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
                                "exchangeType":
                                    1,

                                "tokens": [
                                    str(
                                        NIFTY_SPOT_TOKEN
                                    )
                                ]
                            }
                        ]
                    )

                    logging.info(
                        "🟢 NIFTY subscription active | token=%s",
                        NIFTY_SPOT_TOKEN
                    )

                    # -----------------------------------------
                    # OPTION
                    # -----------------------------------------

                    if option_contract:

                        ok = subscribe_option(
                            sws,
                            option_contract
                        )

                        if ok:

                            subscribed_option_token = str(
                                option_contract[
                                    "symboltoken"
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
                        float(
                            price_raw
                        )
                        / 100.0
                    )

                    # ------------------------------------------------
                    # Timestamp
                    # ------------------------------------------------

                    ts_raw = message.get(
                        "exchange_timestamp"
                    )

                    if ts_raw:

                        try:

                            ts = (
                                datetime
                                .fromtimestamp(
                                    float(
                                        ts_raw
                                    ) / 1000.0,
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

                    # ------------------------------------------------
                    # NIFTY
                    # ------------------------------------------------

                    if token == str(
                        NIFTY_SPOT_TOKEN
                    ):

                        with tick_lock:

                            ticks[
                                "nifty"
                            ] = {

                                "ltp":
                                    price,

                                "timestamp":
                                    ts.isoformat()
                            }

                        logging.info(
                            "🟢 NIFTY TICK: %.2f",
                            price
                        )

                        return

                    # ------------------------------------------------
                    # OPTION
                    # ------------------------------------------------

                    current_option_token = None

                    if option_contract:

                        current_option_token = str(
                            option_contract[
                                "symboltoken"
                            ]
                        )

                    if (
                        current_option_token
                        and token
                        == current_option_token
                    ):

                        with tick_lock:

                            ticks[
                                "option"
                            ] = {

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
                nonlocal subscribed_option_token

                websocket_connected = False

                subscribed_option_token = None

                logging.warning(
                    "🟠 SmartWebSocketV2 CLOSED"
                )

            # =================================================
            # ASSIGN CALLBACKS
            # =================================================

            sws.on_open = on_open

            sws.on_data = on_data

            sws.on_error = on_error

            sws.on_close = on_close

            # =================================================
            # START WEBSOCKET
            # =================================================

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

                # =================================================
                # READ TICKS
                # =================================================

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

                # =================================================
                # WAIT FOR NIFTY WEBSOCKET
                # =================================================

                if nifty_tick is None:

                    time.sleep(
                        0.5
                    )

                    continue

                spot = float(
                    nifty_tick[
                        "ltp"
                    ]
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
                # SPOT REST CANDLES
                #
                # ONLY EVERY 5 MINUTES
                #
                # OLD CACHE NEVER CLEARED
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

                            new_spot_clean = (
                                clean_candles(
                                    new_spot
                                )
                            )

                            if len(
                                new_spot_clean
                            ) >= MIN_CANDLES:

                                spot_candles_cache = (
                                    new_spot_clean
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
                                    len(
                                        new_spot_clean
                                    )
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
                        # Do NOT clear old cache

                        last_spot_fetch = now_dt

                        spot_retry_after = (
                            now_dt
                            + timedelta(
                                seconds=REST_RETRY_SECONDS
                            )
                        )

                # =================================================
                # FUTURES REST CANDLES
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

                            new_futures_clean = (
                                clean_candles(
                                    new_futures
                                )
                            )

                            if len(
                                new_futures_clean
                            ) >= MIN_CANDLES:

                                futures_candles_cache = (
                                    new_futures_clean
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
                                    len(
                                        new_futures_clean
                                    )
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
                    len(
                        spot_candles_cache
                    ) >= MIN_CANDLES

                    and len(
                        futures_candles_cache
                    ) >= MIN_CANDLES
                ):

                    try:

                        merged = merge_candles(
                            spot_candles_cache,
                            futures_candles_cache
                        )

                        if len(
                            merged
                        ) >= MIN_CANDLES:

                            combined_candles_cache = (
                                merged
                            )

                            logging.info(
                                "🟢 Combined candles updated: %d | Volume source: NIFTY FUTURES",
                                len(
                                    combined_candles_cache
                                )
                            )

                        else:

                            logging.warning(
                                "⚠️ Combined candles below minimum: %d/%d",
                                len(merged),
                                MIN_CANDLES
                            )

                    except Exception as merge_err:

                        logging.warning(
                            "Candle merge error: %s",
                            merge_err
                        )

                # =================================================
                # READ STRATEGY SIGNAL
                # =================================================

                desired = (
                    read_strategy_signal()
                )

                desired_hint = None

                if desired:

                    strike, otype = desired

                    desired_hint = (
                        f"{strike}:{otype}"
                    )

                # =================================================
                # OPTION RESOLUTION
                #
                # ONLY:
                #
                # 1. New strike/type
                #
                # OR
                #
                # 2. Previous resolution failed
                #    AND cooldown finished
                #
                # =================================================

                if desired_hint:

                    should_resolve = False

                    # ------------------------------------------------
                    # New strike/type
                    # ------------------------------------------------

                    if (
                        desired_hint
                        != option_hint_key
                    ):

                        should_resolve = True

                    # ------------------------------------------------
                    # Same failed hint
                    # ------------------------------------------------

                    elif (
                        option_contract is None
                        and now_dt
                        >= option_retry_after
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

                            old_token = None

                            if option_contract:

                                old_token = str(
                                    option_contract[
                                        "symboltoken"
                                    ]
                                )

                            new_token = str(
                                resolved[
                                    "symboltoken"
                                ]
                            )

                            # ------------------------------------------------
                            # Unsubscribe old option only if token changed
                            # ------------------------------------------------

                            if (
                                old_token
                                and old_token
                                != new_token
                            ):

                                unsubscribe_option(
                                    sws,
                                    old_token
                                )

                            # ------------------------------------------------
                            # Save contract
                            # ------------------------------------------------

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

                            # ------------------------------------------------
                            # Clear old option tick
                            # ------------------------------------------------

                            with tick_lock:

                                ticks[
                                    "option"
                                ] = None

                            # ------------------------------------------------
                            # Subscribe only if WS connected
                            # ------------------------------------------------

                            if websocket_connected:

                                # Avoid duplicate subscription

                                if (
                                    subscribed_option_token
                                    != new_token
                                ):

                                    ok = (
                                        subscribe_option(
                                            sws,
                                            option_contract
                                        )
                                    )

                                    if ok:

                                        subscribed_option_token = (
                                            new_token
                                        )

                            logging.info(
                                "🟢 Option contract active: %s",
                                option_contract[
                                    "tradingsymbol"
                                ]
                            )

                        else:

                            # ------------------------------------------------
                            # FAILED RESOLUTION
                            #
                            # Keep hint.
                            # Do NOT hammer searchScrip.
                            # ------------------------------------------------

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

                # ------------------------------------------------
                # Need at least 22 candles
                # ------------------------------------------------

                if len(
                    combined_candles_cache
                ) >= MIN_CANDLES:

                    # Last completed candle
                    #
                    # -1 may be current/incomplete candle.
                    # Therefore -2 is used.
                    #

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

                    # ------------------------------------------------
                    # Previous 20 completed candles
                    # ------------------------------------------------

                    volume_window = [

                        float(
                            row[5]
                        )

                        for row in
                        combined_candles_cache[
                            -22:-2
                        ]

                        if row[5] is not None
                    ]

                    if volume_window:

                        volume_average = (
                            sum(
                                volume_window
                            )
                            /
                            len(
                                volume_window
                            )
                        )

                    if volume_average > 0:

                        volume_ratio = (
                            current_volume
                            /
                            volume_average
                        )

                # =================================================
                # PUBLISH DATA
                # =================================================

                payload = {

                    # ---------------------------------------------
                    # LIVE SPOT
                    # ---------------------------------------------

                    "live_spot":
                        spot,

                    "spot_timestamp":
                        nifty_tick.get(
                            "timestamp"
                        ),

                    # ---------------------------------------------
                    # COMBINED CANDLES
                    # ---------------------------------------------

                    "candles":
                        combined_candles_cache,

                    "last_update":
                        now_dt.strftime(
                            "%H:%M:%S"
                        ),

                    # ---------------------------------------------
                    # OPTION
                    # ---------------------------------------------

                    "option_quote":
                        option_quote,

                    "option_contract":
                        option_contract,

                    # ---------------------------------------------
                    # WEBSOCKET
                    # ---------------------------------------------

                    "websocket_connected":
                        websocket_connected,

                    # ---------------------------------------------
                    # FUTURES
                    # ---------------------------------------------

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

                    # ---------------------------------------------
                    # CACHE STATUS
                    # ---------------------------------------------

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
                        ),

                    # ---------------------------------------------
                    # DEBUG
                    # ---------------------------------------------

                    "option_hint":
                        option_hint_key,

                    "option_retry_after":
                        option_retry_after.isoformat()
                        if option_retry_after
                        else None,

                    "spot_retry_after":
                        spot_retry_after.isoformat()
                        if spot_retry_after
                        else None,

                    "futures_retry_after":
                        futures_retry_after.isoformat()
                        if futures_retry_after
                        else None
                }

                # =================================================
                # WRITE
                # =================================================

                atomic_write_json(
                    "data_raw.json",
                    payload
                )

                # =================================================
                # LOOP
                # =================================================

                time.sleep(
                    LOOP_SLEEP
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
# ENTRY
# ============================================================

if __name__ == "__main__":

    start_backend_factory()
