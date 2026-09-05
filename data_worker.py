# data_worker.py
# ============================================================
# NIFTY LIVE DATA WORKER
# ============================================================
#
# ARCHITECTURE
#   Angel One WebSocket / REST
#            |
#            v
#      data_worker.py
#            |
#            +--> data_raw.json  ---> dashboard (READ ONLY)
#            |
#            +--> indicator_calc.py (READS data_raw.json)
#
# IMPORTANT:
#   - NO strategy calculations here.
#   - NO RSI/EMA/volume/runway/signal logic here.
#   - Dashboard only reads published JSON.
#   - Paper engine can read data_raw.json + strategy_signal.json.
#   - WebSocket is the live price source.
#   - Historical REST is used only for candle backfill.
#   - Option master is loaded once after login and cached.
#   - NIFTY futures are also resolved once and used for live volume.
#
# Environment:
#   ANGEL_CLIENT_CODE
#   ANGEL_API_KEY
#   ANGEL_PIN
#   ANGEL_TOTP_SECRET
#   NIFTY_SPOT_TOKEN=99926000
#
# Files:
#   data_raw.json
#   candle_cache.json
#   option_contract_cache.json
#
# ============================================================

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone, time as dtime

import pyotp


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

IST = timezone(timedelta(hours=5, minutes=30))
CONTINUOUS_SESSION_START = dtime(9, 15)
CONTINUOUS_SESSION_END = dtime(15, 15)
CAS_SESSION_END = dtime(15, 35)

# ============================================================
# ENVIRONMENT
# ============================================================

CID = os.getenv("ANGEL_CLIENT_CODE")
AKEY = os.getenv("ANGEL_API_KEY")
PIN = os.getenv("ANGEL_PIN")
TKEY = os.getenv("ANGEL_TOTP_SECRET")

NIFTY_SPOT_TOKEN = os.getenv("NIFTY_SPOT_TOKEN", "99926000")

DATA_RAW_FILE = "data_raw.json"
CANDLE_CACHE_FILE = "candle_cache.json"
CONTRACT_CACHE_FILE = "option_contract_cache.json"
FUTURE_CANDLE_CACHE_FILE = "future_candle_cache.json"


# ============================================================
# TIME / JSON
# ============================================================

def session_type_now(dt=None):
    dt = dt or now_ist()
    if dt.weekday() >= 5:
        return "CLOSED"
    if CONTINUOUS_SESSION_START <= dt.time() < CONTINUOUS_SESSION_END:
        return "CONTINUOUS"
    if CONTINUOUS_SESSION_END <= dt.time() < CAS_SESSION_END:
        return "CAS"
    return "CLOSED"


def market_status_now(dt=None):
    return "OPEN" if session_type_now(dt) == "CONTINUOUS" else "CLOSED"


def is_continuous_timestamp(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        dt = dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)
        return dt.weekday() < 5 and CONTINUOUS_SESSION_START <= dt.time() < CONTINUOUS_SESSION_END
    except Exception:
        return False


def filter_continuous_candles(candles):
    return [row for row in (valid_candles(candles) or []) if is_continuous_timestamp(row[0])]

def now_ist():
    return datetime.now(IST)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"), default=str)
    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def valid_candles(value):
    if not isinstance(value, list):
        return None

    cleaned = []
    for row in value:
        if isinstance(row, (list, tuple)) and len(row) >= 6:
            cleaned.append(list(row[:6]))

    return cleaned or None


# ============================================================
# PERSISTED SPOT CANDLES
# ============================================================

def load_persisted_candles():
    cached = load_json(CANDLE_CACHE_FILE, None)

    if isinstance(cached, dict):
        candles = valid_candles(cached.get("candles"))
        if candles:
            return filter_continuous_candles(candles), cached.get("saved_at")

    raw = load_json(DATA_RAW_FILE, None)
    if isinstance(raw, dict):
        candles = valid_candles(raw.get("candles"))
        if candles:
            return filter_continuous_candles(candles), raw.get("candle_last_success")

    return None, None


def save_persisted_candles(candles, saved_at):
    try:
        atomic_write_json(
            CANDLE_CACHE_FILE,
            {
                "saved_at": saved_at,
                "candles": candles,
            },
        )
    except Exception as exc:
        logging.debug("Candle cache save error: %s", exc)


def load_cached_candles_file(path):
    cached = load_json(path, None)
    if isinstance(cached, dict):
        return filter_continuous_candles(cached.get("candles"))
    return []


def save_cached_candles_file(path, candles, saved_at):
    try:
        atomic_write_json(path, {"saved_at": saved_at, "candles": candles[-300:]})
    except Exception as exc:
        logging.debug("Candle cache save error (%s): %s", path, exc)


# ============================================================
# EXPIRY / OPTION HELPERS
# ============================================================

def extract_expiry(item):
    raw = str(item.get("expiry", "") or "").strip()

    if raw:
        for fmt in (
            "%d%b%Y",
            "%d%b%y",
            "%d-%b-%Y",
            "%d-%b-%y",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(raw.upper(), fmt).date()
            except ValueError:
                pass

    symbol = str(item.get("tradingsymbol", ""))

    m = re.search(r"(\d{1,2}[A-Z]{3}\d{2,4})", symbol.upper())

    if m:
        token = m.group(1)

        for fmt in ("%d%b%Y", "%d%b%y"):
            try:
                return datetime.strptime(token, fmt).date()
            except ValueError:
                pass

    return None


def option_type(item):
    for key in ("optiontype", "optionType", "opttype", "type"):
        value = str(item.get(key, "") or "").upper().strip()
        if value in ("CE", "PE"):
            return value

    symbol = str(item.get("tradingsymbol", "")).upper()

    if symbol.endswith("CE"):
        return "CE"

    if symbol.endswith("PE"):
        return "PE"

    return ""


def strike_value(item):
    for key in ("strike", "strikePrice", "strikeprice"):
        try:
            value = float(item.get(key))

            # SmartAPI may return strike in paise.
            if value > 100000:
                value /= 100.0

            return value
        except (TypeError, ValueError):
            pass

    symbol = str(item.get("tradingsymbol", ""))

    m = re.search(r"(\d+(?:\.\d+)?)(?:CE|PE)$", symbol.upper())

    if m:
        try:
            value = float(m.group(1))
            if value > 100000:
                value /= 100.0
            return value
        except ValueError:
            pass

    return None


def is_real_nifty_option(item):
    symbol = str(item.get("tradingsymbol", "")).upper()

    if not symbol.startswith("NIFTY"):
        return False

    if symbol.startswith("NIFTYFPI"):
        return False

    if symbol.startswith("NIFTYNXT50"):
        return False

    return symbol.endswith("CE") or symbol.endswith("PE")


def make_option_contract(item, today):
    if not is_real_nifty_option(item):
        return None

    opt_type = option_type(item)
    strike = strike_value(item)

    if opt_type not in ("CE", "PE") or strike is None:
        return None

    expiry = extract_expiry(item)

    if expiry is not None and expiry < today:
        return None

    token = item.get("symboltoken") or item.get("token")
    symbol = item.get("tradingsymbol") or item.get("symbol")

    if not token or not symbol:
        return None

    return {
        "exchange": "NFO",
        "tradingsymbol": str(symbol),
        "symboltoken": str(token),
        "strike": float(strike),
        "option_type": opt_type,
        "expiry": expiry.isoformat() if expiry else None,
    }


def make_future_contract(item, today):
    symbol = str(
        item.get("tradingsymbol")
        or item.get("symbol")
        or ""
    ).upper()

    # Real NIFTY index futures only.
    # Exclude NIFTYFPI / NIFTYNXT50 and option contracts.
    if not symbol.startswith("NIFTY"):
        return None

    if symbol.startswith("NIFTYFPI") or symbol.startswith("NIFTYNXT50"):
        return None

    if not symbol.endswith("FUT"):
        return None

    expiry = extract_expiry(item)

    if expiry is not None and expiry < today:
        return None

    token = item.get("symboltoken") or item.get("token")

    if not token:
        return None

    return {
        "exchange": "NFO",
        "tradingsymbol": symbol,
        "symboltoken": str(token),
        "expiry": expiry.isoformat() if expiry else None,
    }


# ============================================================
# ONE-TIME NIFTY MASTER
# ============================================================

def load_nifty_master(api, today):
    """
    One searchScrip call after login.

    Returns:
        {
            "options": {"24100:CE": {...}},
            "future": {...}
        }

    No searchScrip call is made when strike changes.
    """

    try:
        logging.info("Loading NIFTY NFO master ONCE...")

        response = api.searchScrip("NFO", "NIFTY")

        if not response or not response.get("status"):
            logging.warning("NIFTY searchScrip failed: %s", response)
            return {"options": {}, "future": None}

        items = response.get("data") or []

        options = {}
        futures = []

        for item in items:
            opt = make_option_contract(item, today)

            if opt:
                key = f"{int(opt['strike'])}:{opt['option_type']}"
                old = options.get(key)

                if old is None:
                    options[key] = opt
                else:
                    old_exp = old.get("expiry")
                    new_exp = opt.get("expiry")

                    if (
                        old_exp is None
                        or (
                            new_exp is not None
                            and old_exp is not None
                            and new_exp < old_exp
                        )
                    ):
                        options[key] = opt

                continue

            fut = make_future_contract(item, today)

            if fut:
                futures.append(fut)

        futures.sort(
            key=lambda x: (
                x.get("expiry") is None,
                x.get("expiry") or "9999-12-31",
            )
        )

        future = futures[0] if futures else None

        logging.info(
            "NIFTY master loaded: %d options | FUT=%s",
            len(options),
            future.get("tradingsymbol") if future else "NOT FOUND",
        )

        return {
            "options": options,
            "future": future,
        }

    except Exception as exc:
        logging.warning("NIFTY master load failed: %s", exc)
        return {"options": {}, "future": None}


def resolve_option(master, persistent_cache, strike, opt_type, today):
    key = f"{int(float(strike))}:{str(opt_type).upper()}"

    contract = master.get("options", {}).get(key)

    if contract:
        expiry = contract.get("expiry")
        if not expiry or expiry >= today.isoformat():
            return contract

    contract = persistent_cache.get(key)

    if contract:
        expiry = contract.get("expiry")
        if not expiry or expiry >= today.isoformat():
            return contract

    return None


# ============================================================
# 5-MINUTE CANDLE HELPERS
# ============================================================

def candle_bucket(dt):
    """
    Convert any timestamp to its 5-minute candle start.
    """

    minute = (dt.minute // 5) * 5

    return dt.replace(
        minute=minute,
        second=0,
        microsecond=0,
    )


def update_live_candle(
    candles,
    timestamp,
    price,
    volume_increment=0.0,
):
    """
    Update the latest live 5-minute candle.

    This function does DATA AGGREGATION only.
    No trading logic/calculation is performed.
    """

    price = safe_float(price)

    if price is None:
        return candles

    ts = timestamp
    bucket = candle_bucket(ts)

    if not candles:
        candles.append(
            [
                bucket.isoformat(),
                price,
                price,
                price,
                price,
                max(0.0, float(volume_increment or 0.0)),
            ]
        )
        return candles

    last = candles[-1]

    try:
        last_dt = datetime.fromisoformat(str(last[0]))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=IST)
    except Exception:
        last_dt = bucket

    if bucket < last_dt:
        return candles

    if bucket > last_dt:
        candles.append(
            [
                bucket.isoformat(),
                price,
                price,
                price,
                price,
                max(0.0, float(volume_increment or 0.0)),
            ]
        )
        return candles

    # Same candle.
    last[2] = max(float(last[2]), price)
    last[3] = min(float(last[3]), price)
    last[4] = price

    old_volume = safe_float(last[5], 0.0) or 0.0
    last[5] = old_volume + max(
        0.0,
        float(volume_increment or 0.0),
    )

    return candles


def merge_historical_with_live(
    historical,
    live_candle,
    max_candles=300,
):
    """
    Merge historical candles with the currently forming live candle.
    """

    result = valid_candles(historical) or []

    if live_candle:
        if result:
            try:
                last_dt = datetime.fromisoformat(str(result[-1][0]))
                live_dt = datetime.fromisoformat(str(live_candle[0]))

                if last_dt == live_dt:
                    result[-1] = list(live_candle)
                elif live_dt > last_dt:
                    result.append(list(live_candle))
            except Exception:
                result.append(list(live_candle))
        else:
            result.append(list(live_candle))

    # Deduplicate by timestamp.
    dedup = {}

    for row in result:
        if len(row) >= 6:
            dedup[str(row[0])] = list(row[:6])

    ordered = sorted(
        dedup.values(),
        key=lambda x: str(x[0]),
    )

    return ordered[-max_candles:]


# ============================================================
# WEBSOCKET TICK PARSER
# ============================================================

def parse_tick(message):
    """
    SmartWebSocketV2 FULL mode fields are broker/API dependent.
    We read the fields safely and return only raw market data.

    No indicators or strategy calculations are performed.
    """

    if not isinstance(message, dict):
        return None

    token = str(message.get("token", ""))

    raw_price = message.get("last_traded_price")

    price = safe_float(raw_price)

    if price is None:
        return None

    # SmartAPI LTP is normally paise.
    price /= 100.0

    ts_raw = message.get("exchange_timestamp")

    if ts_raw is not None:
        try:
            ts = datetime.fromtimestamp(
                float(ts_raw) / 1000.0,
                tz=timezone.utc,
            ).astimezone(IST)
        except Exception:
            ts = now_ist()
    else:
        ts = now_ist()

    # FULL mode may provide cumulative traded volume.
    cumulative_volume = None

    for key in (
        "volume_trade_for_the_day",
        "volume_traded_today",
        "volume_trade",
    ):
        if message.get(key) is not None:
            cumulative_volume = safe_float(message.get(key))
            if cumulative_volume is not None:
                break

    def first_number(*keys):
        for key in keys:
            if message.get(key) is not None:
                value = safe_float(message.get(key))
                if value is not None:
                    return value
        return None

    return {
        "token": token,
        "ltp": price,
        "timestamp": ts,
        "exchange_timestamp": message.get("exchange_timestamp"),
        "cumulative_volume": cumulative_volume,
        "total_buy_quantity": first_number("total_buy_quantity", "buy_quantity"),
        "total_sell_quantity": first_number("total_sell_quantity", "sell_quantity"),
        "open_interest": first_number("open_interest", "oi"),
        "open_interest_change_percentage": first_number("open_interest_change_percentage", "oi_change_pct"),
        # SmartAPI's parser exposes the two best-5 arrays with the
        # historical names reversed; normalize them here.
        "best_5_buy_data": message.get("best_5_sell_data") or [],
        "best_5_sell_data": message.get("best_5_buy_data") or [],
    }


# ============================================================
# MAIN WORKER
# ============================================================

def start_backend_factory():

    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    while True:

        sws = None

        try:
            if not all((CID, AKEY, PIN, TKEY)):
                raise RuntimeError(
                    "ANGEL_CLIENT_CODE/API_KEY/PIN/"
                    "TOTP_SECRET environment variables are required"
                )

            logging.info("Angel One live data worker starting...")

            # ----------------------------------------------------
            # LOGIN
            # ----------------------------------------------------

            api = SmartConnect(
                api_key=AKEY,
                timeout=15,
            )

            totp = pyotp.TOTP(
                TKEY.replace(" ", "").strip().upper()
            ).now()

            session = api.generateSession(
                CID,
                PIN,
                totp,
            )

            if not session or not session.get("status"):
                raise RuntimeError(
                    f"API session failed: {session}"
                )

            auth_token = session["data"]["jwtToken"]
            feed_token = api.getfeedToken()

            if not feed_token:
                raise RuntimeError(
                    "Unable to obtain SmartAPI feed token"
                )

            logging.info("Angel One API session ready")

            # ----------------------------------------------------
            # CACHE / MASTER
            # ----------------------------------------------------

            cached_candles, persisted_time = (
                load_persisted_candles()
            )

            if cached_candles:
                logging.info(
                    "Recovered %d cached spot candles",
                    len(cached_candles),
                )

            persistent_contract_cache = load_json(
                CONTRACT_CACHE_FILE,
                {},
            )

            master = load_nifty_master(
                api,
                now_ist().date(),
            )

            option_master = master.get("options", {})
            future_contract = master.get("future")

            if option_master:
                persistent_contract_cache.update(
                    option_master
                )

                try:
                    atomic_write_json(
                        CONTRACT_CACHE_FILE,
                        persistent_contract_cache,
                    )
                except Exception:
                    pass

            # ----------------------------------------------------
            # TICK STATE
            # ----------------------------------------------------

            tick_lock = threading.Lock()

            ticks = {
                "nifty": None,
                "future": None,
                "option": None,
            }

            option_contract = None
            option_hint_key = None
            option_chain_live = {}
            option_token_map = {
                str(contract["symboltoken"]): contract
                for contract in option_master.values()
                if isinstance(contract, dict) and contract.get("symboltoken")
            }

            # Current live 5-min candles.
            spot_live_candle = None
            future_live_candle = None

            # Last cumulative future volume.
            future_prev_cumulative_volume = None

            # Historical/live NIFTY futures candles for the volume gate.
            future_candles = load_cached_candles_file(FUTURE_CANDLE_CACHE_FILE)

            # Historical spot candles.
            if cached_candles:
                spot_candles = cached_candles
            else:
                spot_candles = []

            historical_backfill_needed = not bool(cached_candles)
            historical_backfill_attempted = False

            last_candle_fetch = (
                datetime.min.replace(tzinfo=IST)
            )

            if persisted_time:
                try:
                    last_candle_fetch = datetime.fromisoformat(
                        persisted_time
                    )
                    if last_candle_fetch.tzinfo is None:
                        last_candle_fetch = (
                            last_candle_fetch.replace(tzinfo=IST)
                        )
                except Exception:
                    pass

            last_candle_attempt = (
                datetime.min.replace(tzinfo=IST)
            )

            candle_retry_delay = 60.0
            MAX_CANDLE_RETRY = 300.0

            # ----------------------------------------------------
            # WEBSOCKET
            # ----------------------------------------------------

            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token,
            )

            websocket_connected = False

            def on_open(wsapp):
                nonlocal websocket_connected

                websocket_connected = True

                logging.info(
                    "SmartWebSocketV2 CONNECTED"
                )

                try:
                    # --------------------------------------------
                    # SPOT - FULL MODE
                    # --------------------------------------------

                    sws.subscribe(
                        "nifty-spot",
                        3,
                        [
                            {
                                "exchangeType": 1,
                                "tokens": [
                                    str(NIFTY_SPOT_TOKEN)
                                ],
                            }
                        ],
                    )

                    logging.info(
                        "NIFTY spot WebSocket subscription active"
                    )

                    # --------------------------------------------
                    # FUTURE - FULL MODE
                    # --------------------------------------------

                    if future_contract:

                        sws.subscribe(
                            "nifty-future",
                            3,
                            [
                                {
                                    "exchangeType": 2,
                                    "tokens": [
                                        str(
                                            future_contract[
                                                "symboltoken"
                                            ]
                                        )
                                    ],
                                }
                            ],
                        )

                        logging.info(
                            "NIFTY FUT subscription active: %s | token=%s",
                            future_contract["tradingsymbol"],
                            future_contract["symboltoken"],
                        )

                    # --------------------------------------------
                    # NIFTY OPTION CHAIN - SNAP QUOTE
                    # 608 current contracts are within Angel One's
                    # 1000-token/session subscription quota.
                    # --------------------------------------------

                    option_tokens = [
                        str(contract["symboltoken"])
                        for contract in option_master.values()
                        if isinstance(contract, dict) and contract.get("symboltoken")
                    ]

                    if option_tokens:
                        sws.subscribe(
                            "nifty-options-chain",
                            3,
                            [
                                {
                                    "exchangeType": 2,
                                    "tokens": option_tokens,
                                }
                            ],
                        )
                        logging.info(
                            "NIFTY option-chain subscription active: %d tokens",
                            len(option_tokens),
                        )

                except Exception as exc:
                    logging.error(
                        "WebSocket subscribe error: %s",
                        exc,
                    )

            def on_data(wsapp, message):
                nonlocal future_prev_cumulative_volume

                try:
                    tick = parse_tick(message)

                    if not tick:
                        return

                    token = tick["token"]

                    with tick_lock:

                        if token == str(NIFTY_SPOT_TOKEN):

                            ticks["nifty"] = tick

                        elif (
                            future_contract
                            and token
                            == str(
                                future_contract[
                                    "symboltoken"
                                ]
                            )
                        ):

                            ticks["future"] = tick

                            cumulative = (
                                tick.get(
                                    "cumulative_volume"
                                )
                            )

                            if cumulative is not None:

                                if (
                                    future_prev_cumulative_volume
                                    is None
                                    or cumulative
                                    < future_prev_cumulative_volume
                                ):
                                    # First tick / day reset.
                                    increment = 0.0
                                else:
                                    increment = (
                                        cumulative
                                        - future_prev_cumulative_volume
                                    )

                                future_prev_cumulative_volume = (
                                    cumulative
                                )

                                tick[
                                    "volume_increment"
                                ] = max(
                                    0.0,
                                    increment,
                                )

                        elif token in option_token_map:
                            contract = option_token_map[token]
                            row = {
                                **contract,
                                "symbol": contract.get("tradingsymbol"),
                                "trading_symbol": contract.get("tradingsymbol"),
                                "token": token,
                                "ltp": tick.get("ltp"),
                                "timestamp": tick.get("timestamp").isoformat() if tick.get("timestamp") else None,
                                "exchange_timestamp": tick.get("exchange_timestamp"),
                                "open_interest": tick.get("open_interest"),
                                "oi": tick.get("open_interest"),
                                "open_interest_change_percentage": tick.get("open_interest_change_percentage"),
                                "oi_change_pct": tick.get("open_interest_change_percentage"),
                                "volume_day": tick.get("cumulative_volume"),
                                "volume": tick.get("cumulative_volume"),
                                "total_buy_quantity": tick.get("total_buy_quantity") or 0.0,
                                "total_sell_quantity": tick.get("total_sell_quantity") or 0.0,
                                "best_5_buy_data": tick.get("best_5_buy_data") or [],
                                "best_5_sell_data": tick.get("best_5_sell_data") or [],
                            }
                            option_chain_live[f"{int(float(contract['strike']))}:{contract['option_type']}"] = row

                            if option_contract and token == str(option_contract["symboltoken"]):
                                ticks["option"] = tick

                except Exception as exc:
                    logging.debug(
                        "Tick parse error: %s",
                        exc,
                    )

            def on_error(wsapp, error):
                logging.error(
                    "SmartWebSocketV2 ERROR: %s",
                    error,
                )

            def on_close(wsapp):
                nonlocal websocket_connected

                websocket_connected = False

                logging.warning(
                    "SmartWebSocketV2 CLOSED"
                )

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            ws_thread = threading.Thread(
                target=sws.connect,
                daemon=True,
            )

            ws_thread.start()

            logging.info(
                "Live WebSocket worker started"
            )

            # ====================================================
            # MAIN LOOP
            # ====================================================

            while True:

                try:

                    now_dt = now_ist()

                    with tick_lock:
                        nifty_tick = (
                            dict(ticks["nifty"])
                            if ticks["nifty"]
                            else None
                        )

                        future_tick = (
                            dict(ticks["future"])
                            if ticks["future"]
                            else None
                        )

                        option_tick = (
                            dict(ticks["option"])
                            if ticks["option"]
                            else None
                        )

                    # ------------------------------------------------
                    # Need first NIFTY tick.
                    # ------------------------------------------------

                    if nifty_tick is None:
                        time.sleep(0.25)
                        continue

                    spot = float(
                        nifty_tick["ltp"]
                    )

                    # ------------------------------------------------
                    # LIVE SPOT 5-MIN CANDLE
                    # ------------------------------------------------

                    if is_continuous_timestamp(nifty_tick["timestamp"]):
                        spot_candles = update_live_candle(
                            spot_candles, nifty_tick["timestamp"], spot, 0.0,
                        )[-300:]
                        spot_live_candle = spot_candles[-1] if spot_candles else None
                    else:
                        spot_live_candle = None

                    # ------------------------------------------------
                    # LIVE FUTURES 5-MIN CANDLE
                    # ------------------------------------------------
                    # Futures volume is available as a cumulative exchange
                    # value. on_data converts it to a non-negative increment.
                    # Maintain the live futures candle here so downstream
                    # engines can use completed futures volume consistently.
                    if future_tick is not None and is_continuous_timestamp(future_tick.get("timestamp")):
                        future_price = safe_float(future_tick.get("ltp"))
                        if future_price is not None:
                            future_candles = update_live_candle(
                                future_candles,
                                future_tick["timestamp"],
                                future_price,
                                future_tick.get("volume_increment", 0.0),
                            )[-300:]
                            future_live_candle = (
                                future_candles[-1]
                                if future_candles
                                else None
                            )
                            save_cached_candles_file(
                                FUTURE_CANDLE_CACHE_FILE,
                                future_candles,
                                now_dt.isoformat(),
                            )

                    # ------------------------------------------------
                    # HISTORICAL SPOT CANDLE BACKFILL
                    # ------------------------------------------------

                    seconds_since_success = (
                        now_dt - last_candle_fetch
                    ).total_seconds()

                    seconds_since_attempt = (
                        now_dt - last_candle_attempt
                    ).total_seconds()

                    # REST candle backfill is attempted once when the process
                    # starts without a usable cache. Live candles are then
                    # maintained from the WebSocket without repeated REST calls.
                    candle_due = historical_backfill_needed and not historical_backfill_attempted

                    retry_allowed = (
                        seconds_since_attempt
                        >= candle_retry_delay
                    )

                    if candle_due and retry_allowed:

                        historical_backfill_attempted = True
                        last_candle_attempt = now_dt

                        from_d = (
                            now_dt - timedelta(days=2)
                        ).strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        to_d = now_dt.strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        try:

                            logging.info(
                                "Requesting historical 5-min spot candles..."
                            )

                            res = api.getCandleData(
                                {
                                    "exchange": "NSE",
                                    "symboltoken":
                                        NIFTY_SPOT_TOKEN,
                                    "interval":
                                        "FIVE_MINUTE",
                                    "fromdate": from_d,
                                    "todate": to_d,
                                }
                            )

                            if (
                                res
                                and res.get("status")
                                and res.get("data")
                            ):

                                fresh = filter_continuous_candles(
                                    res.get("data")
                                )

                                if fresh:

                                    spot_candles = fresh
                                    historical_backfill_needed = False
                                    if spot_live_candle:
                                        spot_candles = update_live_candle(
                                            spot_candles,
                                            nifty_tick["timestamp"],
                                            spot,
                                            0.0,
                                        )[-300:]

                                    last_candle_fetch = now_dt

                                    save_persisted_candles(
                                        spot_candles,
                                        now_dt.isoformat(),
                                    )

                                    candle_retry_delay = 60.0

                                    logging.info(
                                        "Spot candles updated: %d",
                                        len(spot_candles),
                                    )

                                    if future_contract and not future_candles:
                                        try:
                                            fres = api.getCandleData({
                                                "exchange": "NFO",
                                                "symboltoken": str(future_contract["symboltoken"]),
                                                "interval": "FIVE_MINUTE",
                                                "fromdate": from_d,
                                                "todate": to_d,
                                            })
                                            if fres and fres.get("status") and fres.get("data"):
                                                fh = filter_continuous_candles(fres.get("data"))
                                                if fh:
                                                    future_candles = fh[-300:]
                                                    save_cached_candles_file(FUTURE_CANDLE_CACHE_FILE, future_candles, now_dt.isoformat())
                                                    logging.info("NIFTY futures candles updated: %d", len(future_candles))
                                        except Exception as exc:
                                            logging.warning("Historical NIFTY futures candle API error: %s", exc)

                                else:
                                    historical_backfill_attempted = False
                                    candle_retry_delay = min(
                                        candle_retry_delay * 2,
                                        MAX_CANDLE_RETRY,
                                    )

                            else:
                                historical_backfill_attempted = False
                                candle_retry_delay = min(
                                    candle_retry_delay * 2,
                                    MAX_CANDLE_RETRY,
                                )

                        except Exception as exc:

                            logging.warning(
                                "Historical candle API error: %s",
                                exc,
                            )
                            historical_backfill_attempted = False

                            candle_retry_delay = min(
                                candle_retry_delay * 2,
                                MAX_CANDLE_RETRY,
                            )

                    # ------------------------------------------------
                    # MERGED CANDLES
                    # ------------------------------------------------

                    merged_spot_candles = filter_continuous_candles(
                        merge_historical_with_live(
                            spot_candles, spot_live_candle, max_candles=300,
                        )
                    )[-300:]

                    # ------------------------------------------------
                    # READ DESIRED OPTION FROM INDICATOR OUTPUT
                    #
                    # This is not strategy logic.
                    # Worker only resolves the contract requested
                    # by the backend indicator engine.
                    # ------------------------------------------------

                    desired_hint = None

                    strat = load_json(
                        "strategy_signal.json",
                        {},
                    )

                    if isinstance(strat, dict):

                        if (
                            strat.get("otype")
                            and strat.get("option_strike")
                            is not None
                        ):

                            desired_hint = (
                                f"{int(float(strat['option_strike']))}:"
                                f"{str(strat['otype']).upper()}"
                            )

                    # ------------------------------------------------
                    # OPTION CONTRACT CHANGE
                    # ------------------------------------------------

                    if (
                        desired_hint
                        and desired_hint != option_hint_key
                    ):

                        strike_s, opt_type = (
                            desired_hint.split(":", 1)
                        )

                        resolved = resolve_option(
                            master,
                            persistent_contract_cache,
                            float(strike_s),
                            opt_type,
                            now_dt.date(),
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
                                resolved["symboltoken"]
                            )

                            if old_token != new_token:

                                if old_token:

                                    try:
                                        sws.unsubscribe(
                                            "nifty-option",
                                            3,
                                            [
                                                {
                                                    "exchangeType": 2,
                                                    "tokens": [
                                                        str(old_token)
                                                    ],
                                                }
                                            ],
                                        )
                                    except Exception:
                                        pass

                                option_contract = resolved
                                option_hint_key = desired_hint

                                with tick_lock:
                                    ticks["option"] = None

                                try:

                                    sws.subscribe(
                                        "nifty-option",
                                        3,
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
                                        "Option subscription active: %s",
                                        option_contract[
                                            "tradingsymbol"
                                        ],
                                    )

                                except Exception as exc:
                                    logging.warning(
                                        "Option subscribe error: %s",
                                        exc,
                                    )

                            else:

                                option_contract = resolved
                                option_hint_key = desired_hint

                    # ------------------------------------------------
                    # OPTION QUOTE
                    # ------------------------------------------------

                    option_quote = None

                    desired_row = option_chain_live.get(option_hint_key) if option_hint_key else None
                    if isinstance(desired_row, dict) and desired_row.get("ltp") is not None:
                        option_quote = dict(desired_row)
                    elif option_contract and option_tick:
                        option_quote = {
                            **option_contract,
                            "symbol": option_contract.get("tradingsymbol"),
                            "ltp": float(option_tick["ltp"]),
                            "timestamp": option_tick["timestamp"].isoformat(),
                            "token": option_contract.get("symboltoken"),
                        }

                    # ------------------------------------------------
                    # RAW FUTURE QUOTE
                    # ------------------------------------------------

                    future_quote = None

                    if (
                        future_contract
                        and future_tick
                    ):

                        future_quote = {
                            **future_contract,
                            "ltp": float(
                                future_tick["ltp"]
                            ),
                            "timestamp":
                                future_tick[
                                    "timestamp"
                                ].isoformat(),
                            "cumulative_volume":
                                future_tick.get(
                                    "cumulative_volume"
                                ),
                            "volume_increment":
                                future_tick.get(
                                    "volume_increment",
                                    0.0,
                                ),
                            "volume_day":
                                future_tick.get(
                                    "cumulative_volume"
                                ),
                            "total_buy_quantity":
                                future_tick.get(
                                    "total_buy_quantity"
                                ),
                            "total_sell_quantity":
                                future_tick.get(
                                    "total_sell_quantity"
                                ),
                            "open_interest":
                                future_tick.get(
                                    "open_interest"
                                ),
                            "oi":
                                future_tick.get(
                                    "open_interest"
                                ),
                            "open_interest_change_percentage":
                                future_tick.get(
                                    "open_interest_change_percentage"
                                ),
                            "oi_change_pct":
                                future_tick.get(
                                    "open_interest_change_percentage"
                                ),
                            "exchange_timestamp":
                                future_tick.get(
                                    "exchange_timestamp"
                                ),
                            "best_5_buy_data":
                                future_tick.get(
                                    "best_5_buy_data"
                                ) or [],
                            "best_5_sell_data":
                                future_tick.get(
                                    "best_5_sell_data"
                                ) or [],
                        }

                    # ------------------------------------------------
                    # DAY HIGH / LOW ARE RAW DATA AGGREGATION.
                    #
                    # Dashboard may display them directly.
                    # Indicator engine may also use them.
                    # ------------------------------------------------

                    today_str = now_dt.strftime(
                        "%Y-%m-%d"
                    )

                    today_rows = []

                    for row in merged_spot_candles:

                        try:
                            dt = datetime.fromisoformat(
                                str(row[0])
                            )

                            if dt.strftime(
                                "%Y-%m-%d"
                            ) == today_str:

                                today_rows.append(row)

                        except Exception:
                            continue

                    if today_rows:

                        day_high = max(
                            float(row[2])
                            for row in today_rows
                        )

                        day_low = min(
                            float(row[3])
                            for row in today_rows
                        )

                    else:

                        day_high = spot
                        day_low = spot

                    # ------------------------------------------------
                    # PUBLISH DATA ONLY
                    # ------------------------------------------------

                    payload = {

                        # ------------------------------
                        # LIVE SPOT
                        # ------------------------------

                        "live_spot": spot,

                        "spot_timestamp":
                            nifty_tick[
                                "timestamp"
                            ].isoformat(),

                        # ------------------------------
                        # SPOT CANDLES
                        # ------------------------------

                        "candles":
                            merged_spot_candles,

                        "live_spot_candle":
                            spot_live_candle,

                        "candle_last_success":
                            (
                                last_candle_fetch.isoformat()
                                if spot_candles
                                else None
                            ),

                        "candle_count":
                            len(merged_spot_candles),

                        # ------------------------------
                        # RAW LIVE FUTURE
                        # ------------------------------

                        "future_quote":
                            future_quote,

                        "future_contract":
                            future_contract,

                        "future_live_candle":
                            future_live_candle,
                        "future_candles":
                            future_candles[-300:],

                        # ------------------------------
                        # RAW OPTION
                        # ------------------------------

                        "option_quote":
                            option_quote,

                        "option_contract":
                            option_contract,

                        "option_hint":
                            option_hint_key,
                        "option_chain":
                            dict(option_chain_live),
                        "option_chain_latest_tick":
                            now_dt.isoformat() if option_chain_live else None,

                        # ------------------------------
                        # RAW DAY RANGE
                        # ------------------------------

                        "intraday_high":
                            day_high,

                        "intraday_low":
                            day_low,

                        # ------------------------------
                        # CONNECTION / STATUS
                        # ------------------------------

                        "websocket_connected":
                            websocket_connected,

                        # Market status is clock-based, not WebSocket-based.
                        # A connected socket after 15:30 must still show CLOSED.
                        "market_status": market_status_now(now_dt),
                        "session_type": session_type_now(now_dt),
                        "new_entries_allowed": session_type_now(now_dt) == "CONTINUOUS",
                        "is_cas_session": session_type_now(now_dt) == "CAS",
                        "worker_status":
                            "RUNNING" if websocket_connected else "DISCONNECTED",

                        "last_update":
                            now_dt.strftime(
                                "%H:%M:%S"
                            ),

                        "worker_timestamp":
                            now_dt.isoformat(),

                        "candle_retry_delay":
                            candle_retry_delay,

                        "data_source":
                            "Angel One WebSocket + REST",

                    }

                    atomic_write_json(
                        DATA_RAW_FILE,
                        payload,
                    )

                except Exception as loop_err:

                    logging.exception(
                        "Worker loop error: %s",
                        loop_err,
                    )

                # Dashboard gets fast live updates.
                time.sleep(0.25)

        except Exception as conn_err:

            logging.error(
                "Critical worker error: %s. Restarting in 10 sec...",
                conn_err,
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
