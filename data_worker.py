# data_worker.py
# ============================================================
# NIFTY LIVE DATA WORKER
# ============================================================
#
# Angel One REST:
#   1. Historical 5-min candles
#   2. ONE-TIME option master/searchScrip per process
#
# Angel One WebSocket:
#   1. NIFTY live LTP
#   2. Selected option live LTP
#
# IMPORTANT FIXES:
#   - NO ltpData() polling
#   - searchScrip() is NOT called whenever strike changes
#   - Option contracts are cached in memory
#   - Resolved contracts are also persisted locally
#   - NIFTY/FPI/NXT50 contracts are separated
#   - Candle API has proper backoff after rate-limit errors
#   - Existing candles are preserved during API failure
#   - Existing option contract is preserved during temporary errors
#   - WebSocket remains the live price source
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

NIFTY_SPOT_TOKEN = os.getenv(
    "NIFTY_SPOT_TOKEN",
    "99926000"
)

IST = timezone(timedelta(hours=5, minutes=30))

CONTRACT_CACHE_FILE = "option_contract_cache.json"


# ============================================================
# TIME
# ============================================================

def now_ist():
    return datetime.now(IST)


# ============================================================
# SAFE JSON
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


def load_json(path, default=None):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


# ============================================================
# EXPIRY PARSER
# ============================================================

def extract_expiry(item):
    raw = str(
        item.get("expiry", "") or ""
    ).strip()

    if raw:
        for fmt in (
            "%d%b%Y",
            "%d%b%y",
            "%d-%b-%Y",
            "%d-%b-%y",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(
                    raw.upper(),
                    fmt
                ).date()
            except ValueError:
                pass

    symbol = str(
        item.get("tradingsymbol", "")
    )

    m = re.search(
        r"(\d{1,2}[A-Z]{3}\d{2,4})",
        symbol.upper()
    )

    if m:
        token = m.group(1)

        for fmt in (
            "%d%b%Y",
            "%d%b%y",
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
        "type",
    ):
        value = str(
            item.get(key, "")
        ).upper().strip()

        if value in ("CE", "PE"):
            return value

    symbol = str(
        item.get("tradingsymbol", "")
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
        "strikeprice",
    ):
        try:

            value = float(
                item.get(key)
            )

            # Some SmartAPI data represents
            # strike in paise.
            if value > 100000:
                value /= 100.0

            return value

        except (
            TypeError,
            ValueError,
        ):
            pass

    symbol = str(
        item.get("tradingsymbol", "")
    )

    m = re.search(
        r"(\d+(?:\.\d+)?)(?:CE|PE)$",
        symbol.upper()
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
# VALID NIFTY OPTION FILTER
# ============================================================

def is_real_nifty_option(item):

    symbol = str(
        item.get("tradingsymbol", "")
    ).upper()

    # We want NIFTY index options only.
    #
    # Exclude:
    #   NIFTYFPI
    #   NIFTYNXT50
    #
    # because searchScrip("NFO","NIFTY") can return
    # those products too.

    if not symbol.startswith("NIFTY"):
        return False

    if symbol.startswith("NIFTYFPI"):
        return False

    if symbol.startswith("NIFTYNXT50"):
        return False

    return (
        symbol.endswith("CE")
        or symbol.endswith("PE")
    )


# ============================================================
# BUILD CONTRACT FROM MASTER ITEM
# ============================================================

def make_contract(item, today):

    if not is_real_nifty_option(item):
        return None

    opt_type = option_type(item)

    if opt_type not in ("CE", "PE"):
        return None

    strike = strike_value(item)

    if strike is None:
        return None

    expiry = extract_expiry(item)

    if expiry is not None and expiry < today:
        return None

    token = (
        item.get("symboltoken")
        or item.get("token")
    )

    symbol = (
        item.get("tradingsymbol")
        or item.get("symbol")
    )

    if not token or not symbol:
        return None

    return {
        "exchange": "NFO",
        "tradingsymbol": str(symbol),
        "symboltoken": str(token),
        "strike": float(strike),
        "option_type": opt_type,
        "expiry": (
            expiry.isoformat()
            if expiry
            else None
        ),
    }


# ============================================================
# LOAD PERSISTENT CONTRACT CACHE
# ============================================================

def load_contract_cache():

    data = load_json(
        CONTRACT_CACHE_FILE,
        {}
    )

    if not isinstance(data, dict):
        return {}

    return data


def save_contract_cache(cache):

    try:

        atomic_write_json(
            CONTRACT_CACHE_FILE,
            cache
        )

    except Exception as exc:

        logging.debug(
            "Contract cache save error: %s",
            exc
        )


# ============================================================
# ONE-TIME MASTER LOAD
# ============================================================

def load_nifty_option_master(api, today):

    """
    IMPORTANT:
    searchScrip() is called ONLY ONCE after login.

    The returned NIFTY contracts are converted into an
    in-memory lookup table.

    Therefore changing:
        24100 CE -> 24050 CE -> 24150 PE

    does NOT call searchScrip() again.
    """

    try:

        logging.info(
            "📥 Loading NIFTY option master ONCE..."
        )

        response = api.searchScrip(
            "NFO",
            "NIFTY"
        )

        if not response:
            logging.warning(
                "searchScrip returned empty response"
            )
            return {}

        if not response.get("status"):
            logging.warning(
                "searchScrip unsuccessful: %s",
                response
            )
            return {}

        items = response.get("data") or []

        if not items:
            logging.warning(
                "searchScrip returned zero contracts"
            )
            return {}

        cache = {}

        for item in items:

            contract = make_contract(
                item,
                today
            )

            if not contract:
                continue

            key = (
                f"{int(contract['strike'])}:"
                f"{contract['option_type']}"
            )

            # Multiple expiries can exist.
            # Keep the nearest expiry.
            existing = cache.get(key)

            if existing is None:

                cache[key] = contract

            else:

                old_expiry = existing.get(
                    "expiry"
                )

                new_expiry = contract.get(
                    "expiry"
                )

                if old_expiry is None:
                    cache[key] = contract

                elif (
                    new_expiry is not None
                    and new_expiry < old_expiry
                ):
                    cache[key] = contract

        logging.info(
            "🟢 NIFTY option master loaded: %d contracts",
            len(cache)
        )

        return cache

    except Exception as exc:

        logging.warning(
            "⚠️ NIFTY option master load failed: %s",
            exc
        )

        return {}


# ============================================================
# RESOLVE FROM LOCAL MASTER
# ============================================================

def resolve_option_from_cache(
    option_master,
    persistent_cache,
    strike,
    opt_type,
    today,
):
    """
    ZERO REST CALLS.
    """

    key = (
        f"{int(float(strike))}:"
        f"{str(opt_type).upper()}"
    )

    # --------------------------------------------------------
    # 1. Current process master
    # --------------------------------------------------------

    contract = option_master.get(key)

    if contract:

        expiry = contract.get("expiry")

        if (
            not expiry
            or expiry >= today.isoformat()
        ):
            return contract

    # --------------------------------------------------------
    # 2. Persistent cache fallback
    # --------------------------------------------------------

    contract = persistent_cache.get(key)

    if contract:

        expiry = contract.get("expiry")

        if (
            not expiry
            or expiry >= today.isoformat()
        ):

            logging.info(
                "🟡 Using persistent cached option: %s",
                contract.get(
                    "tradingsymbol"
                )
            )

            return contract

    return None


# ============================================================
# MAIN BACKEND
# ============================================================

def start_backend_factory():

    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    while True:

        sws = None

        try:

            # ====================================================
            # ENV CHECK
            # ====================================================

            if not all(
                (
                    CID,
                    AKEY,
                    PIN,
                    TKEY,
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

            # ====================================================
            # LOGIN
            # ====================================================

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

            auth_token = session["data"]["jwtToken"]

            feed_token = api.getfeedToken()

            if not feed_token:
                raise RuntimeError(
                    "Unable to obtain SmartAPI feed token"
                )

            logging.info(
                "🟢 Angel One API session ready"
            )

            # ====================================================
            # LOCAL STATE
            # ====================================================

            cached_candles = None

            # Last successful candle update
            last_candle_fetch = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # Last candle API attempt
            last_candle_attempt = (
                datetime.min.replace(
                    tzinfo=IST
                )
            )

            # Dynamic retry delay.
            # Starts at 60 sec.
            # On rate-limit/error it increases.
            candle_retry_delay = 60.0

            # Maximum retry delay = 5 minutes.
            MAX_CANDLE_RETRY = 300.0

            # Option contract state
            option_contract = None
            option_hint_key = None

            # ----------------------------------------------------
            # Load persistent contract cache
            # ----------------------------------------------------

            persistent_contract_cache = (
                load_contract_cache()
            )

            # ----------------------------------------------------
            # Load option master ONCE
            # ----------------------------------------------------

            option_master = load_nifty_option_master(
                api,
                now_ist().date()
            )

            # Merge loaded contracts into persistent cache.
            if option_master:

                persistent_contract_cache.update(
                    option_master
                )

                save_contract_cache(
                    persistent_contract_cache
                )

            # ====================================================
            # TICK STATE
            # ====================================================

            tick_lock = threading.Lock()

            ticks = {
                "nifty": None,
                "option": None,
            }

            # ====================================================
            # WEBSOCKET
            # ====================================================

            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token
            )

            websocket_connected = False

            # ====================================================
            # WEBSOCKET OPEN
            # ====================================================

            def on_open(wsapp):

                nonlocal websocket_connected

                websocket_connected = True

                logging.info(
                    "🟢 SmartWebSocketV2 CONNECTED"
                )

                try:

                    # ------------------------------------------------
                    # NIFTY SUBSCRIPTION
                    # ------------------------------------------------

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
                                ],
                            }
                        ],
                    )

                    logging.info(
                        "🟢 NIFTY WebSocket subscription active"
                    )

                    # ------------------------------------------------
                    # OPTION SUBSCRIPTION
                    # ------------------------------------------------

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
                                    ],
                                }
                            ],
                        )

                        logging.info(
                            "🟢 Existing option subscription restored: %s",
                            option_contract[
                                "tradingsymbol"
                            ]
                        )

                except Exception as exc:

                    logging.error(
                        "WebSocket subscribe error: %s",
                        exc
                    )

            # ====================================================
            # WEBSOCKET DATA
            # ====================================================

            def on_data(wsapp, message):

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
                                datetime.fromtimestamp(
                                    float(ts_raw)
                                    / 1000.0,
                                    tz=timezone.utc,
                                ).astimezone(IST)
                            )

                        except Exception:

                            ts = now_ist()

                    else:

                        ts = now_ist()

                    with tick_lock:

                        # ------------------------------------------------
                        # NIFTY
                        # ------------------------------------------------

                        if token == str(
                            NIFTY_SPOT_TOKEN
                        ):

                            ticks["nifty"] = {
                                "ltp": price,
                                "timestamp":
                                    ts.isoformat(),
                            }

                            logging.info(
                                "🟢 NIFTY TICK: %.2f",
                                price
                            )

                        # ------------------------------------------------
                        # OPTION
                        # ------------------------------------------------

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
                                "ltp": price,
                                "timestamp":
                                    ts.isoformat(),
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

            # ====================================================
            # WEBSOCKET ERROR
            # ====================================================

            def on_error(wsapp, error):

                logging.error(
                    "🔴 SmartWebSocketV2 ERROR: %s",
                    error
                )

            # ====================================================
            # WEBSOCKET CLOSE
            # ====================================================

            def on_close(wsapp):

                nonlocal websocket_connected

                websocket_connected = False

                logging.warning(
                    "🟠 SmartWebSocketV2 CLOSED"
                )

            # ====================================================
            # ASSIGN CALLBACKS
            # ====================================================

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            # ====================================================
            # START WEBSOCKET
            # ====================================================

            ws_thread = threading.Thread(
                target=sws.connect,
                daemon=True
            )

            ws_thread.start()

            logging.info(
                "🟢 Live WebSocket worker started"
            )

            # ====================================================
            # MAIN LOOP
            # ====================================================

            while True:

                now_dt = now_ist()

                try:

                    # =================================================
                    # COPY TICKS SAFELY
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
                    # NIFTY MUST COME FROM WEBSOCKET
                    # =================================================

                    if nifty_tick is None:

                        logging.info(
                            "Waiting for first NIFTY WebSocket tick..."
                        )

                        time.sleep(0.5)

                        continue

                    spot = float(
                        nifty_tick["ltp"]
                    )

                    # =================================================
                    # HISTORICAL CANDLES
                    # =================================================
                    #
                    # Normal:
                    #   once per 60 sec
                    #
                    # Error:
                    #   retry after increasing backoff
                    #
                    # IMPORTANT:
                    #   Existing cached candles are NEVER erased.
                    # =================================================

                    seconds_since_success = (
                        now_dt
                        - last_candle_fetch
                    ).total_seconds()

                    seconds_since_attempt = (
                        now_dt
                        - last_candle_attempt
                    ).total_seconds()

                    candle_due = (
                        cached_candles is None
                        or seconds_since_success >= 60
                    )

                    retry_allowed = (
                        seconds_since_attempt
                        >= candle_retry_delay
                    )

                    if (
                        candle_due
                        and retry_allowed
                    ):

                        last_candle_attempt = now_dt

                        from_d = (
                            now_dt
                            - timedelta(days=2)
                        ).strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        to_d = now_dt.strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        try:

                            logging.info(
                                "📡 Requesting 5-min candle data..."
                            )

                            res = api.getCandleData(
                                {
                                    "exchange": "NSE",
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

                            if (
                                res
                                and res.get("status")
                                and res.get("data")
                            ):

                                cached_candles = (
                                    res["data"]
                                )

                                last_candle_fetch = (
                                    now_dt
                                )

                                # Reset backoff after success.
                                candle_retry_delay = 60.0

                                logging.info(
                                    "🟢 5-min candles updated: %d candles",
                                    len(
                                        cached_candles
                                    )
                                )

                            else:

                                logging.warning(
                                    "⚠️ 5-min candle API returned no data"
                                )

                                candle_retry_delay = min(
                                    candle_retry_delay * 2,
                                    MAX_CANDLE_RETRY
                                )

                        except Exception as candle_err:

                            error_text = str(
                                candle_err
                            )

                            logging.warning(
                                "⚠️ Candle API error: %s",
                                error_text
                            )

                            # ------------------------------------------------
                            # IMPORTANT RATE-LIMIT FIX
                            # ------------------------------------------------
                            #
                            # If Angel One says:
                            # "Access denied because of exceeding access rate"
                            #
                            # DO NOT immediately retry.
                            #
                            # Backoff:
                            # 60 sec -> 120 sec -> 240 sec -> 300 sec
                            # ------------------------------------------------

                            candle_retry_delay = min(
                                candle_retry_delay * 2,
                                MAX_CANDLE_RETRY
                            )

                            logging.warning(
                                "⏳ Next candle API retry in %.0f seconds",
                                candle_retry_delay
                            )

                    # =================================================
                    # READ STRATEGY SIGNAL
                    # =================================================

                    desired_hint = None

                    if os.path.exists(
                        "strategy_signal.json"
                    ):

                        try:

                            strat = load_json(
                                "strategy_signal.json",
                                {}
                            )

                            if (
                                strat.get("otype")
                                and
                                strat.get(
                                    "option_strike"
                                ) is not None
                            ):

                                desired_hint = (
                                    f"{int(float(strat['option_strike']))}:"
                                    f"{str(strat['otype']).upper()}"
                                )

                        except Exception as signal_err:

                            logging.debug(
                                "Strategy signal read error: %s",
                                signal_err
                            )

                    # =================================================
                    # OPTION CONTRACT CHANGE
                    # =================================================
                    #
                    # NO searchScrip here.
                    #
                    # Resolve directly from option_master/cache.
                    # =================================================

                    if (
                        desired_hint
                        and desired_hint
                        != option_hint_key
                    ):

                        strike_s, opt_type = (
                            desired_hint.split(
                                ":",
                                1
                            )
                        )

                        strike_value_requested = (
                            float(strike_s)
                        )

                        resolved = (
                            resolve_option_from_cache(
                                option_master,
                                persistent_contract_cache,
                                strike_value_requested,
                                opt_type,
                                now_dt.date(),
                            )
                        )

                        if resolved:

                            old_token = (
                                option_contract[
                                    "symboltoken"
                                ]
                                if option_contract
                                else None
                            )

                            new_token = str(
                                resolved[
                                    "symboltoken"
                                ]
                            )

                            # ------------------------------------------------
                            # Don't resubscribe to same token.
                            # ------------------------------------------------

                            if old_token != new_token:

                                # --------------------------------------------
                                # Unsubscribe old option
                                # --------------------------------------------

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
                                                    ],
                                                }
                                            ],
                                        )

                                    except Exception as unsub_err:

                                        logging.debug(
                                            "Option unsubscribe warning: %s",
                                            unsub_err
                                        )

                                # --------------------------------------------
                                # Set new contract
                                # --------------------------------------------

                                option_contract = resolved

                                option_hint_key = (
                                    desired_hint
                                )

                                with tick_lock:

                                    ticks["option"] = None

                                # --------------------------------------------
                                # Subscribe new option
                                # --------------------------------------------

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
                                                ],
                                            }
                                        ],
                                    )

                                    logging.info(
                                        "🟢 OPTION WebSocket subscription active: %s | token=%s | expiry=%s",
                                        option_contract[
                                            "tradingsymbol"
                                        ],
                                        option_contract[
                                            "symboltoken"
                                        ],
                                        option_contract.get(
                                            "expiry"
                                        )
                                    )

                                except Exception as sub_err:

                                    logging.warning(
                                        "Option subscribe error: %s",
                                        sub_err
                                    )

                            else:

                                option_contract = resolved
                                option_hint_key = (
                                    desired_hint
                                )

                        else:

                            # ------------------------------------------------
                            # IMPORTANT:
                            # Don't destroy a working option contract just
                            # because a new strike isn't available.
                            # ------------------------------------------------

                            logging.warning(
                                "⚠️ Option not found in local master/cache: %s",
                                desired_hint
                            )

                    # =================================================
                    # BUILD OPTION QUOTE
                    # =================================================

                    option_quote = None

                    if (
                        option_contract
                        and option_tick
                    ):

                        option_quote = {
                            **option_contract,
                            "ltp": float(
                                option_tick["ltp"]
                            ),
                            "timestamp":
                                option_tick[
                                    "timestamp"
                                ],
                        }

                    # =================================================
                    # PUBLISH data_raw.json
                    # =================================================

                    payload = {
                        "live_spot":
                            spot,

                        "spot_timestamp":
                            nifty_tick.get(
                                "timestamp"
                            ),

                        "candles":
                            cached_candles or [],

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

                        "option_hint":
                            option_hint_key,

                        "candle_last_success":
                            (
                                last_candle_fetch.isoformat()
                                if cached_candles
                                else None
                            ),

                        "candle_retry_delay":
                            candle_retry_delay,
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

                # =================================================
                # LIVE PUBLISH FREQUENCY
                # =================================================

                time.sleep(0.25)

        # ========================================================
        # CONNECTION FAILURE / RESTART
        # ========================================================

        except Exception as conn_err:

            logging.error(
                "🔴 Critical worker error: %s. "
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
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    start_backend_factory()
