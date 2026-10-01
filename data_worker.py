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
#   - NIFTY futures are resolved once for live price/structure only.
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
from datetime import datetime, timedelta, timezone

import pyotp


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

IST = timezone(timedelta(hours=5, minutes=30))

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
OPTION_OI_BASELINE_FILE = "option_oi_baseline.json"
OPTION_VOLUME_CACHE_FILE = "option_volume_cache.json"


# ============================================================
# TIME / JSON
# ============================================================

def now_ist():
    return datetime.now(IST)


def market_status_ist(dt):
    """Return trading-session status using IST clock."""
    current = dt.astimezone(IST).time()
    if current >= datetime.strptime("09:15", "%H:%M").time() and current < datetime.strptime("15:30", "%H:%M").time():
        return "OPEN"
    if current >= datetime.strptime("15:30", "%H:%M").time() and current < datetime.strptime("15:35", "%H:%M").time():
        return "CAS"
    return "CLOSED"


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
            return candles, cached.get("saved_at")

    raw = load_json(DATA_RAW_FILE, None)
    if isinstance(raw, dict):
        candles = valid_candles(raw.get("candles"))
        if candles:
            return candles, raw.get("candle_last_success")

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
    """Normalize the SmartWebSocketV2 decoded packet without dropping fields."""
    if not isinstance(message, dict):
        return None

    token = str(message.get("token", ""))
    raw_price = safe_float(message.get("last_traded_price"))
    if raw_price is None:
        return None

    price = raw_price / 100.0

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

    return {
        "token": token,
        "ltp": price,
        "timestamp": ts,
        "exchange_timestamp": ts.isoformat(),
        "last_traded_quantity": safe_float(message.get("last_traded_quantity"), 0.0) or 0.0,
        "average_traded_price": (safe_float(message.get("average_traded_price"), 0.0) or 0.0) / 100.0,
        "cumulative_volume": safe_float(message.get("volume_trade_for_the_day"), 0.0) or 0.0,
        "total_buy_quantity": safe_float(message.get("total_buy_quantity"), 0.0) or 0.0,
        "total_sell_quantity": safe_float(message.get("total_sell_quantity"), 0.0) or 0.0,
        "open_interest": safe_float(message.get("open_interest"), 0.0) or 0.0,
        "best_5_buy_data": message.get("best_5_buy_data") if isinstance(message.get("best_5_buy_data"), list) else [],
        "best_5_sell_data": message.get("best_5_sell_data") if isinstance(message.get("best_5_sell_data"), list) else [],
        "subscription_mode": message.get("subscription_mode_val") or message.get("subscription_mode"),
    }


HISTORICAL_MIN_INTERVAL = 1.5
_last_historical_call = 0.0
_historical_call_lock = threading.Lock()

def fetch_historical_candles(api, exchange, token, interval="FIVE_MINUTE", days=3):
    """Fetch startup history with a broker-safe request throttle. Live candles are maintained from WebSocket ticks."""
    global _last_historical_call
    if not token:
        return []

    now_dt = now_ist()
    from_d = (now_dt - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    to_d = now_dt.strftime("%Y-%m-%d %H:%M")
    params = {
        "exchange": exchange,
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": from_d,
        "todate": to_d,
    }

    # Angel One historical API is rate-limited. Serialize calls and keep
    # a safety gap so spot/futures startup requests cannot burst together.
    with _historical_call_lock:
        elapsed = time.monotonic() - _last_historical_call
        if elapsed < HISTORICAL_MIN_INTERVAL:
            time.sleep(HISTORICAL_MIN_INTERVAL - elapsed)
        _last_historical_call = time.monotonic()

    for attempt in range(2):
        try:
            res = api.getCandleData(params)
            if res and res.get("status") and res.get("data"):
                return valid_candles(res.get("data")) or []
            logging.warning(
                "Historical %s %s candle returned no data (attempt %d)",
                exchange, token, attempt + 1,
            )
        except Exception as exc:
            logging.warning(
                "Historical %s %s candle error (attempt %d): %s",
                exchange, token, attempt + 1, exc,
            )

        if attempt == 0:
            time.sleep(2.0)
            with _historical_call_lock:
                _last_historical_call = time.monotonic()

    return []


def update_future_live_candle(candles, tick, previous_cumulative_volume):
    """Build continuous 5-minute futures candles from cumulative exchange volume."""
    if not tick:
        return candles, previous_cumulative_volume
    ts = tick["timestamp"]
    price = float(tick["ltp"])
    cumulative = float(tick.get("cumulative_volume") or 0.0)
    delta = 0.0
    if previous_cumulative_volume is not None and cumulative >= previous_cumulative_volume:
        delta = cumulative - previous_cumulative_volume
    elif previous_cumulative_volume is not None and cumulative < previous_cumulative_volume:
        # New trading day / broker reset. Do not inject a huge negative or positive volume.
        delta = 0.0

    bucket = candle_bucket(ts).isoformat()
    if not candles:
        candles.append([bucket, price, price, price, price, delta])
        return candles, cumulative

    last = candles[-1]
    last_bucket = str(last[0])
    if last_bucket == bucket:
        last[2] = max(float(last[2]), price)
        last[3] = min(float(last[3]), price)
        last[4] = price
        last[5] = max(0.0, float(last[5] or 0.0)) + delta
    elif bucket > last_bucket:
        candles.append([bucket, price, price, price, price, delta])

    return candles[-300:], cumulative


def load_option_volume_state(today_str):
    cached = load_json(OPTION_VOLUME_CACHE_FILE, {}) or {}
    if not isinstance(cached, dict) or cached.get("date") != today_str:
        return {"date": today_str, "last_volume": {}, "candles": {}}
    if not isinstance(cached.get("last_volume"), dict):
        cached["last_volume"] = {}
    if not isinstance(cached.get("candles"), dict):
        cached["candles"] = {}
    return cached


def update_option_volume_state(state, key, tick):
    """Build 5-minute traded-volume candles from the broker's cumulative day volume."""
    if not isinstance(state, dict) or not key or not isinstance(tick, dict):
        return
    cumulative = safe_float(tick.get("cumulative_volume"), None)
    if cumulative is None or cumulative < 0:
        return
    ts = tick.get("timestamp")
    if not isinstance(ts, datetime):
        return
    bucket = candle_bucket(ts).isoformat()
    last_map = state.setdefault("last_volume", {})
    candles_map = state.setdefault("candles", {})
    previous = safe_float(last_map.get(key), None)
    if previous is None:
        delta = 0.0
    elif cumulative >= previous:
        delta = cumulative - previous
    else:
        # Broker day-volume reset; never inject a negative/huge volume spike.
        delta = 0.0
    last_map[key] = cumulative
    rows = candles_map.setdefault(key, [])
    if rows and str(rows[-1][0]) == bucket:
        rows[-1][1] = max(0.0, float(rows[-1][1] or 0.0)) + max(0.0, delta)
    else:
        if not rows or bucket > str(rows[-1][0]):
            rows.append([bucket, max(0.0, delta)])
    candles_map[key] = rows[-80:]


def save_option_volume_state(state):
    try:
        # Keep only recent contracts/candles so data_raw.json stays compact.
        candles = state.get("candles", {}) if isinstance(state, dict) else {}
        trimmed = {k: v[-80:] for k, v in candles.items() if isinstance(v, list)}
        payload = {
            "date": state.get("date"),
            "last_volume": state.get("last_volume", {}),
            "candles": trimmed,
            "saved_at": now_ist().isoformat(),
        }
        atomic_write_json(OPTION_VOLUME_CACHE_FILE, payload)
    except Exception as exc:
        logging.debug("Option volume cache save error: %s", exc)


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

            option_ticks = {}
            option_tick_count = 0
            last_option_diag = 0.0
            option_token_to_key = {
                str(contract["symboltoken"]): key
                for key, contract in option_master.items()
                if contract.get("symboltoken")
            }
            option_contract = None
            option_hint_key = None
            option_oi_baseline = load_json(OPTION_OI_BASELINE_FILE, {}) or {}
            baseline_date = str(now_ist().date())
            if option_oi_baseline.get("date") != baseline_date:
                option_oi_baseline = {"date": baseline_date, "values": {}}

            option_volume_state = load_option_volume_state(baseline_date)
            last_option_volume_save = 0.0

            future_candles = []
            future_last_cumulative_volume = None
            if future_contract:
                cached_future = load_json(FUTURE_CANDLE_CACHE_FILE, {}) or {}
                if (cached_future.get("token") == str(future_contract.get("symboltoken"))
                        and isinstance(cached_future.get("candles"), list)):
                    future_candles = valid_candles(cached_future.get("candles")) or []
                if not future_candles:
                    future_candles = fetch_historical_candles(
                        api, "NFO", future_contract.get("symboltoken"), "FIVE_MINUTE", days=3
                    )
                if future_candles:
                    try:
                        atomic_write_json(FUTURE_CANDLE_CACHE_FILE, {
                            "token": str(future_contract.get("symboltoken")),
                            "saved_at": now_ist().isoformat(),
                            "candles": future_candles,
                        })
                    except Exception:
                        pass

            # Current live 5-min spot candle.
            spot_live_candle = None

            # Historical spot candles.
            if cached_candles:
                spot_candles = cached_candles
            else:
                spot_candles = []

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
                        "NIFTYSPOT",
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
                            "NIFTFUT",
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
                    # FULL NIFTY OPTION CHAIN - SNAP QUOTE
                    # --------------------------------------------
                    # Subscribe once to the current NIFTY option master.
                    # SmartAPI allows up to 1000 token subscriptions per
                    # WebSocket session; the current NIFTY master is well
                    # below that limit. Chunking keeps requests manageable.
                    option_tokens = list(option_token_to_key.keys())
                    chunk_size = 200
                    for i in range(0, len(option_tokens), chunk_size):
                        chunk = option_tokens[i:i + chunk_size]
                        if not chunk:
                            continue
                        # SmartAPI correlationID is limited to 10 alphanumeric characters.
                        # Keep every option-chain subscription request within that contract.
                        sws.subscribe(
                            f"NOPT{i // chunk_size:02d}",
                            3,
                            [{"exchangeType": 2, "tokens": chunk}],
                        )
                    logging.info(
                        "NIFTY option-chain SNAP_QUOTE subscription active: %d contracts",
                        len(option_tokens),
                    )

                except Exception as exc:
                    logging.error(
                        "WebSocket subscribe error: %s",
                        exc,
                    )

            def on_data(wsapp, message):
                nonlocal option_tick_count
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

                        elif token in option_token_to_key:

                            option_ticks[token] = tick
                            option_tick_count += 1
                            update_option_volume_state(
                                option_volume_state,
                                option_token_to_key[token],
                                tick,
                            )

                            if (
                                option_contract
                                and token == str(option_contract["symboltoken"])
                            ):
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

                    spot_live_candle = [
                        candle_bucket(
                            nifty_tick["timestamp"]
                        ).isoformat(),
                        spot,
                        spot,
                        spot,
                        spot,
                        0.0,
                    ]

                    if spot_candles:

                        try:
                            last_dt = datetime.fromisoformat(
                                str(spot_candles[-1][0])
                            )

                            live_dt = datetime.fromisoformat(
                                spot_live_candle[0]
                            )

                            if last_dt == live_dt:
                                # Start from historical OHLC and update.
                                base = list(spot_candles[-1])

                                base[2] = max(
                                    float(base[2]),
                                    spot,
                                )

                                base[3] = min(
                                    float(base[3]),
                                    spot,
                                )

                                base[4] = spot

                                spot_live_candle = base

                        except Exception:
                            pass

                    # ------------------------------------------------
                    # HISTORICAL SPOT CANDLE BACKFILL
                    # ------------------------------------------------

                    seconds_since_success = (
                        now_dt - last_candle_fetch
                    ).total_seconds()

                    seconds_since_attempt = (
                        now_dt - last_candle_attempt
                    ).total_seconds()

                    candle_due = (
                        not spot_candles
                        or seconds_since_success >= 60
                    )

                    retry_allowed = (
                        seconds_since_attempt
                        >= candle_retry_delay
                    )

                    if candle_due and retry_allowed:

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

                                fresh = valid_candles(
                                    res.get("data")
                                )

                                if fresh:

                                    spot_candles = fresh

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

                                else:

                                    candle_retry_delay = min(
                                        candle_retry_delay * 2,
                                        MAX_CANDLE_RETRY,
                                    )

                            else:

                                candle_retry_delay = min(
                                    candle_retry_delay * 2,
                                    MAX_CANDLE_RETRY,
                                )

                        except Exception as exc:

                            logging.warning(
                                "Historical candle API error: %s",
                                exc,
                            )

                            candle_retry_delay = min(
                                candle_retry_delay * 2,
                                MAX_CANDLE_RETRY,
                            )

                    # ------------------------------------------------
                    # MERGED CANDLES
                    # ------------------------------------------------

                    merged_spot_candles = (
                        merge_historical_with_live(
                            spot_candles,
                            spot_live_candle,
                            max_candles=300,
                        )
                    )

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
                    # ------------------------------------------------
                    # SELECTED OPTION CONTRACT
                    # ------------------------------------------------
                    # All option contracts are already subscribed. We only
                    # select the contract needed by paper_engine; no repeated
                    # subscribe/unsubscribe is required.

                    desired_hint = None
                    strat = load_json("strategy_signal.json", {})
                    if isinstance(strat, dict) and strat.get("otype") and strat.get("option_strike") is not None:
                        desired_hint = (
                            f"{int(float(strat['option_strike']))}:"
                            f"{str(strat['otype']).upper()}"
                        )

                    if desired_hint:
                        resolved = resolve_option(
                            master, persistent_contract_cache,
                            float(desired_hint.split(":", 1)[0]),
                            desired_hint.split(":", 1)[1],
                            now_dt.date(),
                        )
                        if resolved:
                            option_contract = resolved
                            option_hint_key = desired_hint
                            selected_tick = option_ticks.get(str(resolved["symboltoken"]))
                            with tick_lock:
                                ticks["option"] = dict(selected_tick) if selected_tick else None

                    # ------------------------------------------------
                    # ------------------------------------------------
                    # NORMALIZED OPTION CHAIN
                    # ------------------------------------------------
                    option_chain = {}
                    latest_option_tick = None
                    for key, contract in option_master.items():
                        token = str(contract.get("symboltoken") or "")
                        tick = option_ticks.get(token)
                        if not tick:
                            continue
                        oi = float(tick.get("open_interest") or 0.0)
                        baseline_values = option_oi_baseline.setdefault("values", {})
                        baseline = baseline_values.get(key)
                        if baseline is None and oi > 0:
                            baseline = oi
                            baseline_values[key] = oi
                        oi_change_pct = 0.0
                        if baseline and baseline > 0:
                            oi_change_pct = ((oi - float(baseline)) / float(baseline)) * 100.0
                        option_chain[key] = {
                            **contract,
                            "symbol": contract.get("tradingsymbol"),
                            "trading_symbol": contract.get("tradingsymbol"),
                            "token": token,
                            "ltp": tick.get("ltp"),
                            "open_interest": oi,
                            "oi": oi,
                            "open_interest_change_percentage": oi_change_pct,
                            "oi_change_pct": oi_change_pct,
                            "volume_day": float(tick.get("cumulative_volume") or 0.0),
                            "volume": float(tick.get("cumulative_volume") or 0.0),
                            "total_buy_quantity": float(tick.get("total_buy_quantity") or 0.0),
                            "total_sell_quantity": float(tick.get("total_sell_quantity") or 0.0),
                            "best_5_buy_data": tick.get("best_5_buy_data") or [],
                            "best_5_sell_data": tick.get("best_5_sell_data") or [],
                            "timestamp": tick["timestamp"].isoformat() if hasattr(tick.get("timestamp"), "isoformat") else tick.get("timestamp"),
                            "exchange_timestamp": tick.get("exchange_timestamp"),
                        }
                        latest_option_tick = max(
                            latest_option_tick or "",
                            str(tick.get("timestamp")),
                        )

                    try:
                        atomic_write_json(OPTION_OI_BASELINE_FILE, option_oi_baseline)
                    except Exception:
                        pass

                    # Selected option quote for paper_engine.
                    option_quote = None
                    if option_contract:
                        key = option_hint_key or ""
                        option_quote = option_chain.get(key)

                    # ------------------------------------------------
                    # LIVE FUTURE CANDLE / VOLUME SOURCE
                    # ------------------------------------------------

                    if future_tick:
                        future_candles, future_last_cumulative_volume = update_future_live_candle(
                            future_candles, future_tick, future_last_cumulative_volume
                        )
                        try:
                            atomic_write_json(FUTURE_CANDLE_CACHE_FILE, {
                                "token": str(future_contract.get("symboltoken")) if future_contract else None,
                                "saved_at": now_dt.isoformat(),
                                "candles": future_candles[-300:],
                            })
                        except Exception:
                            pass

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
                    # OPTION VOLUME HISTORY SNAPSHOT
                    # ------------------------------------------------
                    if (now_dt.timestamp() - last_option_volume_save) >= 5.0:
                        save_option_volume_state(option_volume_state)
                        last_option_volume_save = now_dt.timestamp()

                    option_volume_candles = {
                        key: rows[-60:]
                        for key, rows in option_volume_state.get("candles", {}).items()
                        if isinstance(rows, list) and rows
                    }

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
                            option_chain,

                        "option_chain_center":
                            (int(round(spot / 50.0)) * 50) if spot else None,

                        "option_chain_latest_tick":
                            latest_option_tick,

                        "option_chain_contracts":
                            len(option_chain),

                        "option_tick_count":
                            int(option_tick_count),

                        # Completed/forming 5-minute traded-volume candles
                        # for each NIFTY option contract. Strategy volume is
                        # derived from the selected option premium, not futures.
                        "option_volume_candles":
                            option_volume_candles,

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

                        "market_status":
                            market_status_ist(now_dt),

                        "is_cas_session":
                            market_status_ist(now_dt) == "CAS",

                        "new_entries_allowed":
                            market_status_ist(now_dt) == "OPEN",

                        "websocket_connected":
                            websocket_connected,

                        "worker_status":
                            "RUNNING" if websocket_connected else "DISCONNECTED",

                        "data_epoch":
                            now_dt.isoformat(),

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
