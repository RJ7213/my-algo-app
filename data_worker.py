# ============================================================
# data_worker.py
# NIFTY 50 LIVE DATA MEDIATOR - FINAL
# ============================================================
#
# RESPONSIBILITY
# ----------------
# Angel One -> collect market data -> publish data_raw.json
#
# This file DOES NOT:
#   - calculate EMA / RSI / levels
#   - identify setups
#   - decide CE/PE
#   - generate entry/exit signals
#   - read strategy_signal.json
#
# It is the market-data mediator for the other engines.
#
# DATA SOURCES
# ------------
# 1) NIFTY spot WebSocket LTP
# 2) NIFTY current futures WebSocket SNAP_QUOTE
# 3) NIFTY option-chain WebSocket SNAP_QUOTE
# 4) Angel One historical 5-minute NIFTY candles
# 5) Angel One historical 5-minute NIFTY futures candles
# 6) Official Angel One scrip master for NIFTY contracts
#
# OUTPUT
# ------
# data_raw.json contains:
#   - direct live spot/futures/option data
#   - complete selected option-chain quotes
#   - raw 5-minute candles
#   - live day high/low
#   - connection/session status
#   - timestamps / freshness information
#
# MARKET SESSION
# --------------
# 09:15 <= IST < 15:30 : Angel processing ON
# Outside session             : no Angel login/WebSocket/API calls
# Last valid snapshot          : retained after market close
# Weekend                      : worker sleeps
#
# OPTION CHAIN
# ------------
# Current expiry only, around spot:
#   OPTION_WINDOW_POINTS = 500
#   OPTION_STRIKE_STEP   = 50
# This gives up to 21 strikes x 2 sides = 42 option contracts.
# The window recenters only after spot moves by 100 points, not every tick.
#
# IMPORTANT ANGEL SDK DETAIL
# --------------------------
# Angel's current SmartWebSocketV2 parser exposes SNAP_QUOTE mode 3 with
# LTP, volume, OI, total buy/sell quantity and best-5 data. The current SDK
# parser internally assigns the best-5 buy/sell arrays in reversed names;
# this worker corrects that mapping before publishing data_raw.json.
# ============================================================

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pyotp
import requests


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# SmartAPI uses logzero internally. Keep its per-tick informational dump
# out of Render logs; our worker logs only meaningful state changes/errors.
logging.getLogger("logzero_default").setLevel(logging.WARNING)
logging.getLogger("SmartApi").setLevel(logging.WARNING)


# ============================================================
# ENVIRONMENT / CONSTANTS
# ============================================================

CID = os.getenv("ANGEL_CLIENT_CODE")
AKEY = os.getenv("ANGEL_API_KEY")
PIN = os.getenv("ANGEL_PIN")
TKEY = os.getenv("ANGEL_TOTP_SECRET")

NIFTY_SPOT_TOKEN = os.getenv("NIFTY_SPOT_TOKEN", "99926000")

IST = timezone(timedelta(hours=5, minutes=30))

RAW_FILE = "data_raw.json"
CONTRACT_CACHE_FILE = "option_contract_cache.json"

SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Option chain: 500 points either side, 50-point strikes.
OPTION_WINDOW_POINTS = 500
OPTION_STRIKE_STEP = 50
OPTION_RECENTER_DISTANCE = 100

# Historical API pacing.
SPOT_CANDLE_INTERVAL_SEC = 60
FUTURES_CANDLE_INTERVAL_SEC = 300
MAX_SPOT_CANDLE_RETRY_SEC = 300
MAX_FUTURES_CANDLE_RETRY_SEC = 900

# Output loop. WebSocket is the real-time source; JSON is refreshed at this
# rate so the other local processes have a fresh snapshot.
PUBLISH_INTERVAL_SEC = 0.25

# Missing contract warning throttle.
MISSING_CONTRACT_WARNING_SEC = 60


# ============================================================
# TIME
# ============================================================


def now_ist() -> datetime:
    return datetime.now(IST)


def market_is_open(dt: Optional[datetime] = None) -> bool:
    dt = dt or now_ist()
    if dt.weekday() >= 5:
        return False

    start = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= dt < end


# ============================================================
# JSON HELPERS
# ============================================================


def atomic_write_json(path: str, payload: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ============================================================
# NORMALIZATION HELPERS
# ============================================================


def as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_ws_price(value: Any) -> Optional[float]:
    """Angel WebSocket prices are supplied in paise."""
    raw = as_float(value)
    if raw is None:
        return None
    return raw / 100.0


# ============================================================
# EXPIRY / CONTRACT PARSING
# ============================================================


def extract_expiry(item: Dict[str, Any]) -> Optional[datetime.date]:
    raw = str(item.get("expiry", "") or "").strip().upper()

    if raw:
        for fmt in (
            "%d%b%Y",
            "%d%b%y",
            "%d-%b-%Y",
            "%d-%b-%y",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue

    symbol = str(
        item.get("tradingsymbol") or item.get("symbol") or ""
    ).upper()

    # Exact two-digit year. This avoids the old greedy parsing problem where
    # NIFTY01SEP2624100CE could accidentally be read as 01SEP2624.
    m = re.search(
        r"(\d{1,2}[A-Z]{3}\d{2})(?=\d+(?:CE|PE|FUT)$)",
        symbol,
    )
    if not m:
        return None

    try:
        return datetime.strptime(m.group(1), "%d%b%y").date()
    except ValueError:
        return None


def option_type(item: Dict[str, Any]) -> str:
    for key in ("optiontype", "optionType", "opttype", "type"):
        value = str(item.get(key, "") or "").upper().strip()
        if value in ("CE", "PE"):
            return value

    symbol = str(
        item.get("tradingsymbol") or item.get("symbol") or ""
    ).upper()
    if symbol.endswith("CE"):
        return "CE"
    if symbol.endswith("PE"):
        return "PE"
    return ""


def strike_value(item: Dict[str, Any]) -> Optional[float]:
    for key in ("strike", "strikePrice", "strikeprice"):
        value = as_float(item.get(key))
        if value is None:
            continue

        # Angel scrip master stores option strikes in paise in many records.
        if value > 100000:
            value /= 100.0
        return value

    symbol = str(
        item.get("tradingsymbol") or item.get("symbol") or ""
    ).upper()
    m = re.search(r"(\d+(?:\.\d+)?)(?:CE|PE)$", symbol)
    if not m:
        return None

    value = as_float(m.group(1))
    if value is not None and value > 100000:
        value /= 100.0
    return value


def is_real_nifty_option(item: Dict[str, Any]) -> bool:
    symbol = str(
        item.get("tradingsymbol") or item.get("symbol") or ""
    ).upper().strip()
    name = str(item.get("name", "") or "").upper().strip()

    # Prefer exact master name when available. This prevents NIFTYNXT50,
    # NIFTYFPI and other NIFTY-prefixed products from entering the cache.
    if name and name != "NIFTY":
        return False

    if not symbol.startswith("NIFTY"):
        return False
    if symbol.startswith("NIFTYNXT50"):
        return False
    if symbol.startswith("NIFTYFPI"):
        return False

    return symbol.endswith("CE") or symbol.endswith("PE")


def make_option_contract(
    item: Dict[str, Any],
    today,
) -> Optional[Dict[str, Any]]:
    if not is_real_nifty_option(item):
        return None

    opt_type = option_type(item)
    strike = strike_value(item)
    expiry = extract_expiry(item)

    if opt_type not in ("CE", "PE") or strike is None:
        return None
    if expiry is not None and expiry < today:
        return None

    token = item.get("symboltoken") or item.get("token")
    symbol = item.get("tradingsymbol") or item.get("symbol")
    if not token or not symbol:
        return None

    return {
        "exchange": "NFO",
        "tradingsymbol": str(symbol).upper(),
        "symboltoken": str(token),
        "strike": float(strike),
        "option_type": opt_type,
        "expiry": expiry.isoformat() if expiry else None,
        "lotsize": as_int(item.get("lotsize") or item.get("lotSize")),
        "tick_size": as_float(item.get("tick_size") or item.get("tickSize")),
    }


def make_future_contract(
    item: Dict[str, Any],
    today,
) -> Optional[Dict[str, Any]]:
    symbol = str(
        item.get("tradingsymbol") or item.get("symbol") or ""
    ).upper().strip()
    name = str(item.get("name", "") or "").upper().strip()
    instrument = str(item.get("instrumenttype", "") or "").upper().strip()

    if name and name != "NIFTY":
        return None
    if not symbol.startswith("NIFTY"):
        return None
    if symbol.startswith("NIFTYNXT50") or symbol.startswith("NIFTYFPI"):
        return None
    if not (symbol.endswith("FUT") or instrument == "FUTIDX"):
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
        "lotsize": as_int(item.get("lotsize") or item.get("lotSize")),
        "tick_size": as_float(item.get("tick_size") or item.get("tickSize")),
    }


# ============================================================
# CONTRACT CACHE
# ============================================================


def load_contract_cache() -> Dict[str, Any]:
    data = load_json(CONTRACT_CACHE_FILE, {})
    if not isinstance(data, dict):
        return {}
    return data


def save_contract_cache(
    contracts: Dict[str, Dict[str, Any]],
    future: Optional[Dict[str, Any]],
    cache_date: str,
) -> None:
    payload = {
        "date": cache_date,
        "contracts": contracts,
        "futures_contract": future,
    }
    try:
        atomic_write_json(CONTRACT_CACHE_FILE, payload)
    except Exception as exc:
        logging.debug("Contract cache save error: %s", exc)


def unpack_contract_cache(data: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Optional[Dict[str, Any]]]:
    # New format.
    if isinstance(data.get("contracts"), dict):
        return data.get("contracts", {}), data.get("futures_contract")

    # Backward compatibility with the previous flat cache format.
    flat = {
        str(k): v
        for k, v in data.items()
        if isinstance(v, dict)
    }
    return flat, None


# ============================================================
# OFFICIAL MASTER LOAD
# ============================================================


def build_contract_maps(
    items: List[Dict[str, Any]],
    today,
) -> Tuple[Dict[str, Dict[str, Any]], Optional[Dict[str, Any]]]:
    option_map: Dict[str, Dict[str, Any]] = {}
    nearest_future: Optional[Dict[str, Any]] = None

    for item in items:
        if not isinstance(item, dict):
            continue

        contract = make_option_contract(item, today)
        if contract:
            key = f"{int(round(contract['strike']))}:{contract['option_type']}"
            old = option_map.get(key)
            old_expiry = old.get("expiry") if old else None
            new_expiry = contract.get("expiry")

            if (
                old is None
                or (
                    new_expiry is not None
                    and (old_expiry is None or new_expiry < old_expiry)
                )
            ):
                option_map[key] = contract

        future = make_future_contract(item, today)
        if future:
            old_expiry = nearest_future.get("expiry") if nearest_future else None
            new_expiry = future.get("expiry")
            if (
                nearest_future is None
                or (
                    new_expiry is not None
                    and (old_expiry is None or new_expiry < old_expiry)
                )
            ):
                nearest_future = future

    return option_map, nearest_future


def load_nifty_master(
    api,
    today,
) -> Tuple[Dict[str, Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load NIFTY contracts once. No REST contract lookup during live ticks."""

    # 1) Official public master is the primary source.
    try:
        logging.info("📥 Loading official Angel One scrip master ONCE...")
        response = requests.get(SCRIP_MASTER_URL, timeout=25)
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            raise ValueError("Scrip master response is not a list")

        filtered: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            exchange = str(
                item.get("exch_seg", item.get("exchange", "")) or ""
            ).upper().strip()
            name = str(item.get("name", "") or "").upper().strip()
            symbol = str(
                item.get("symbol", item.get("tradingsymbol", "")) or ""
            ).upper().strip()
            instrument = str(
                item.get("instrumenttype", "") or ""
            ).upper().strip()

            if exchange != "NFO":
                continue
            if name != "NIFTY" and not symbol.startswith("NIFTY"):
                continue
            if symbol.startswith("NIFTYNXT50") or symbol.startswith("NIFTYFPI"):
                continue
            if not (
                symbol.endswith("CE")
                or symbol.endswith("PE")
                or symbol.endswith("FUT")
                or instrument == "FUTIDX"
            ):
                continue

            filtered.append(item)

        option_map, future = build_contract_maps(filtered, today)

        if option_map:
            logging.info(
                "🟢 NIFTY contracts loaded: %d strikes (CE/PE combined)",
                len(option_map),
            )
            if future:
                logging.info(
                    "🟢 NIFTY FUT: %s | token=%s | expiry=%s",
                    future["tradingsymbol"],
                    future["symboltoken"],
                    future.get("expiry"),
                )
            return option_map, future

        logging.warning("⚠️ Official master returned no usable NIFTY contracts")

    except Exception as exc:
        logging.warning("⚠️ Official scrip master failed: %s", exc)

    # 2) One-time SmartAPI fallback. Never called for strike changes.
    try:
        logging.info("📥 Falling back to Angel searchScrip ONCE...")
        response = api.searchScrip("NFO", "NIFTY")
        if response and response.get("status"):
            items = response.get("data") or []
            option_map, future = build_contract_maps(items, today)
            if option_map:
                logging.info(
                    "🟢 NIFTY fallback contracts loaded: %d",
                    len(option_map),
                )
                return option_map, future
    except Exception as exc:
        logging.warning("⚠️ searchScrip fallback failed: %s", exc)

    # 3) Persistent cache fallback.
    cached = load_contract_cache()
    cached_contracts, cached_future = unpack_contract_cache(cached)
    valid_contracts: Dict[str, Dict[str, Any]] = {}

    for key, contract in cached_contracts.items():
        if not isinstance(contract, dict):
            continue
        expiry = contract.get("expiry")
        if not expiry or expiry >= today.isoformat():
            valid_contracts[str(key)] = contract

    if valid_contracts:
        logging.info(
            "🟡 Using persistent NIFTY contract cache: %d contracts",
            len(valid_contracts),
        )
        return valid_contracts, cached_future

    return {}, None


# ============================================================
# OPTION WINDOW
# ============================================================


def nearest_option_strike(spot: float) -> int:
    return int(round(spot / OPTION_STRIKE_STEP) * OPTION_STRIKE_STEP)


def option_window_keys(spot: float) -> List[str]:
    center = nearest_option_strike(spot)
    count = int(OPTION_WINDOW_POINTS / OPTION_STRIKE_STEP)
    return [
        f"{strike}:{otype}"
        for strike in range(
            center - count * OPTION_STRIKE_STEP,
            center + count * OPTION_STRIKE_STEP + OPTION_STRIKE_STEP,
            OPTION_STRIKE_STEP,
        )
        for otype in ("CE", "PE")
    ]


def get_window_contracts(
    option_master: Dict[str, Dict[str, Any]],
    spot: float,
) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for key in option_window_keys(spot):
        contract = option_master.get(key)
        if contract:
            result[key] = contract
    return result


def make_subscription_groups(
    contracts: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    token_list = [
        {
            "exchangeType": 2,
            "tokens": [str(c["symboltoken"]) for c in contracts.values()],
        }
    ] if contracts else []

    by_token = {
        str(c["symboltoken"]): c
        for c in contracts.values()
    }
    return token_list, by_token


# ============================================================
# WEBSOCKET QUOTE NORMALIZATION
# ============================================================


def normalize_best5_from_sdk(message: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Current Angel SmartWebSocketV2 source assigns the parsed best-5 arrays
    under reversed field names. Correct that here so downstream engines get
    actual buy and actual sell sides.
    """
    sdk_buy_named = message.get("best_5_buy_data") or []
    sdk_sell_named = message.get("best_5_sell_data") or []

    # SDK parser currently does:
    #   parsed buy_data  = parser sell_data
    #   parsed sell_data = parser buy_data
    # Therefore actual buy = sdk_sell_named and actual sell = sdk_buy_named.
    actual_buy = sdk_sell_named
    actual_sell = sdk_buy_named

    def clean(rows: Any) -> List[Dict[str, Any]]:
        out = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "flag": row.get("flag"),
                    "quantity": as_int(row.get("quantity"), 0) or 0,
                    "price": (
                        as_float(row.get("price"), 0.0) or 0.0
                    ) / 100.0,
                    "no_of_orders": as_int(
                        row.get("no of orders", row.get("no_of_orders")),
                        0,
                    ) or 0,
                }
            )
        return out

    return clean(actual_buy), clean(actual_sell)


def normalize_option_tick(
    message: Dict[str, Any],
    contract: Dict[str, Any],
    timestamp: str,
) -> Dict[str, Any]:
    actual_buy, actual_sell = normalize_best5_from_sdk(message)

    return {
        **contract,
        "ltp": normalize_ws_price(message.get("last_traded_price")),
        "timestamp": timestamp,
        "exchange_timestamp": message.get("exchange_timestamp"),
        "sequence_number": message.get("sequence_number"),
        "last_traded_quantity": as_int(message.get("last_traded_quantity")),
        "average_traded_price": normalize_ws_price(
            message.get("average_traded_price")
        ),
        "volume_day": as_int(message.get("volume_trade_for_the_day")),
        "total_buy_quantity": as_float(message.get("total_buy_quantity")),
        "total_sell_quantity": as_float(message.get("total_sell_quantity")),
        "open_interest": as_int(message.get("open_interest")),
        "open_interest_change_percentage": as_float(
            message.get("open_interest_change_percentage")
        ),
        "open_price": normalize_ws_price(message.get("open_price_of_the_day")),
        "high_price": normalize_ws_price(message.get("high_price_of_the_day")),
        "low_price": normalize_ws_price(message.get("low_price_of_the_day")),
        "closed_price": normalize_ws_price(message.get("closed_price")),
        "upper_circuit": normalize_ws_price(message.get("upper_circuit_limit")),
        "lower_circuit": normalize_ws_price(message.get("lower_circuit_limit")),
        "best_5_buy_data": actual_buy,
        "best_5_sell_data": actual_sell,
    }


def normalize_futures_tick(
    message: Dict[str, Any],
    contract: Dict[str, Any],
    timestamp: str,
) -> Dict[str, Any]:
    return {
        **contract,
        "ltp": normalize_ws_price(message.get("last_traded_price")),
        "timestamp": timestamp,
        "exchange_timestamp": message.get("exchange_timestamp"),
        "sequence_number": message.get("sequence_number"),
        "last_traded_quantity": as_int(message.get("last_traded_quantity")),
        "average_traded_price": normalize_ws_price(
            message.get("average_traded_price")
        ),
        "volume_day": as_int(message.get("volume_trade_for_the_day")),
        "total_buy_quantity": as_float(message.get("total_buy_quantity")),
        "total_sell_quantity": as_float(message.get("total_sell_quantity")),
        "open_price": normalize_ws_price(message.get("open_price_of_the_day")),
        "high_price": normalize_ws_price(message.get("high_price_of_the_day")),
        "low_price": normalize_ws_price(message.get("low_price_of_the_day")),
        "closed_price": normalize_ws_price(message.get("closed_price")),
    }


# ============================================================
# HISTORICAL CANDLE FETCH
# ============================================================


def fetch_candles(
    api,
    exchange: str,
    symbol_token: str,
    from_dt: datetime,
    to_dt: datetime,
):
    return api.getCandleData(
        {
            "exchange": exchange,
            "symboltoken": str(symbol_token),
            "interval": "FIVE_MINUTE",
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
        }
    )


# ============================================================
# SESSION
# ============================================================


def start_backend_factory():
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    # Prevent accidental duplicate execution in the same Render instance.
    # Advisory file lock is deliberately not required here; Render process
    # supervision is handled outside this worker. This marker is only useful
    # for log visibility.
    logging.info("🟢 NIFTY data worker process started")

    last_closed_write_day = None

    while True:
        current = now_ist()

        # ------------------------------------------------------------
        # MARKET CLOSED: do not login, do not call Angel, retain snapshot.
        # ------------------------------------------------------------
        if not market_is_open(current):
            previous = load_json(RAW_FILE, {})
            if not isinstance(previous, dict):
                previous = {}

            # Do not destroy market data. Only update status metadata.
            previous["market_status"] = "CLOSED"
            previous["worker_status"] = "Market closed - last snapshot retained"
            previous["market_closed_at"] = current.isoformat()
            previous["last_update_ist"] = current.isoformat()
            previous.setdefault("data_source", "Angel One SmartWebSocketV2")

            try:
                atomic_write_json(RAW_FILE, previous)
            except Exception as exc:
                logging.debug("Closed-state snapshot write failed: %s", exc)

            if last_closed_write_day != current.date():
                logging.info(
                    "⏸️ Market CLOSED | %s IST | last snapshot retained",
                    current.strftime("%Y-%m-%d %H:%M:%S"),
                )
                last_closed_write_day = current.date()

            # Next possible session check.
            time.sleep(20 if current.weekday() < 5 else 60)
            continue

        # ------------------------------------------------------------
        # MARKET OPEN SESSION
        # ------------------------------------------------------------
        api = None
        sws = None
        ws_thread = None

        try:
            if not all((CID, AKEY, PIN, TKEY)):
                raise RuntimeError(
                    "ANGEL_CLIENT_CODE / ANGEL_API_KEY / ANGEL_PIN / "
                    "ANGEL_TOTP_SECRET environment variables are required"
                )

            session_day = current.date()
            logging.info(
                "🚀 Starting Angel One data session | %s IST",
                current.strftime("%Y-%m-%d %H:%M:%S"),
            )

            # --------------------------------------------------------
            # LOGIN
            # --------------------------------------------------------
            api = SmartConnect(api_key=AKEY, timeout=15)
            totp = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
            session = api.generateSession(CID, PIN, totp)

            if not session or not session.get("status"):
                raise RuntimeError(f"API session failed: {session}")

            auth_token = session["data"]["jwtToken"]
            feed_token = api.getfeedToken()
            if not feed_token:
                raise RuntimeError("Unable to obtain SmartAPI feed token")

            logging.info("🟢 Angel One API session ready")

            # --------------------------------------------------------
            # CONTRACT MASTER
            # --------------------------------------------------------
            option_master, futures_contract = load_nifty_master(
                api,
                session_day,
            )

            if option_master:
                save_contract_cache(
                    option_master,
                    futures_contract,
                    session_day.isoformat(),
                )

            if not option_master:
                raise RuntimeError(
                    "No usable NIFTY option contracts available from official "
                    "master, searchScrip, or persistent cache"
                )

            # --------------------------------------------------------
            # STATE
            # --------------------------------------------------------
            tick_lock = threading.Lock()

            state: Dict[str, Any] = {
                "nifty": None,
                "futures": None,
                "options": {},
                "option_window": {},
            }

            websocket_connected = False
            websocket_open_at = None

            live_day_high = None
            live_day_low = None

            # Futures live 5-minute volume derived from cumulative day volume.
            futures_volume_bucket = None
            futures_volume_anchor = None
            live_futures_volume_5m = None

            # Historical candle cache.
            cached_candles = None
            cached_futures_candles = None

            last_candle_fetch = datetime.min.replace(tzinfo=IST)
            last_candle_attempt = datetime.min.replace(tzinfo=IST)
            candle_retry_delay = 1.0

            last_futures_candle_fetch = datetime.min.replace(tzinfo=IST)
            last_futures_candle_attempt = datetime.min.replace(tzinfo=IST)
            futures_candle_retry_delay = 5.0

            # Option-chain subscription state.
            subscribed_option_tokens: Dict[str, Dict[str, Any]] = {}
            option_window_center = None
            missing_contract_last_logged: Dict[str, float] = {}

            # --------------------------------------------------------
            # WEBSOCKET
            # --------------------------------------------------------
            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token,
                max_retry_attempt=2,
                retry_strategy=1,
                retry_delay=5,
                retry_multiplier=2,
                retry_duration=10,
            )

            def subscribe_option_window(ws) -> None:
                nonlocal option_window_center, subscribed_option_tokens

                with tick_lock:
                    nifty = state.get("nifty")
                    spot = as_float(nifty.get("ltp")) if nifty else None

                if spot is None:
                    return

                center = nearest_option_strike(spot)
                if (
                    option_window_center is not None
                    and abs(center - option_window_center) < OPTION_RECENTER_DISTANCE
                ):
                    return

                desired_contracts = get_window_contracts(option_master, spot)
                desired_by_token = {
                    str(c["symboltoken"]): c
                    for c in desired_contracts.values()
                }

                old_tokens = set(subscribed_option_tokens)
                new_tokens = set(desired_by_token)

                remove_tokens = sorted(old_tokens - new_tokens)
                add_tokens = sorted(new_tokens - old_tokens)

                if remove_tokens:
                    try:
                        ws.unsubscribe(
                            "nifty-opt",
                            3,
                            [{"exchangeType": 2, "tokens": remove_tokens}],
                        )
                    except Exception as exc:
                        logging.debug("Option unsubscribe warning: %s", exc)

                if add_tokens:
                    try:
                        ws.subscribe(
                            "nifty-opt",
                            3,
                            [{"exchangeType": 2, "tokens": add_tokens}],
                        )
                    except Exception as exc:
                        logging.warning("Option subscribe error: %s", exc)
                        return

                subscribed_option_tokens = desired_by_token
                option_window_center = center

                with tick_lock:
                    state["option_window"] = desired_contracts

                logging.info(
                    "🟢 NIFTY option window: center=%d | contracts=%d | added=%d | removed=%d",
                    center,
                    len(desired_contracts),
                    len(add_tokens),
                    len(remove_tokens),
                )

            def on_open(wsapp):
                nonlocal websocket_connected, websocket_open_at
                websocket_connected = True
                websocket_open_at = now_ist().isoformat()

                logging.info("🟢 SmartWebSocketV2 CONNECTED")

                try:
                    # NIFTY spot: LTP mode is enough and lowest payload.
                    sws.subscribe(
                        "nifty-spot",
                        1,
                        [{
                            "exchangeType": 1,
                            "tokens": [str(NIFTY_SPOT_TOKEN)],
                        }],
                    )

                    # Futures: SNAP_QUOTE supplies volume/OHLC/buy-sell/OI fields.
                    if futures_contract:
                        sws.subscribe(
                            "nifty-fut",
                            3,
                            [{
                                "exchangeType": 2,
                                "tokens": [str(futures_contract["symboltoken"])],
                            }],
                        )

                    # Initial option window is based on the latest known spot.
                    # If spot has not arrived yet, the main loop will subscribe
                    # immediately after the first spot tick.
                    with tick_lock:
                        spot = as_float(
                            state["nifty"].get("ltp")
                        ) if state["nifty"] else None

                    if spot is not None:
                        subscribe_option_window(sws)

                    logging.info("🟢 Base NIFTY/FUT subscriptions active")

                except Exception as exc:
                    logging.error("WebSocket subscription error: %s", exc)

            def on_data(wsapp, message):
                try:
                    if not isinstance(message, dict):
                        return

                    token = str(message.get("token", ""))
                    ltp = normalize_ws_price(message.get("last_traded_price"))
                    if ltp is None:
                        return

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

                    timestamp = ts.isoformat()

                    with tick_lock:
                        # NIFTY spot.
                        if token == str(NIFTY_SPOT_TOKEN):
                            state["nifty"] = {
                                "ltp": ltp,
                                "timestamp": timestamp,
                                "exchange_timestamp": message.get("exchange_timestamp"),
                            }
                            return

                        # NIFTY futures.
                        if futures_contract and token == str(futures_contract["symboltoken"]):
                            state["futures"] = normalize_futures_tick(
                                message,
                                futures_contract,
                                timestamp,
                            )
                            return

                        # NIFTY option chain.
                        contract = subscribed_option_tokens.get(token)
                        if contract:
                            state["options"][token] = normalize_option_tick(
                                message,
                                contract,
                                timestamp,
                            )

                except Exception as exc:
                    logging.debug("Tick parse error: %s", exc)

            def on_error(wsapp, error):
                logging.error("🔴 SmartWebSocketV2 ERROR: %s", error)

            def on_close(wsapp):
                nonlocal websocket_connected
                websocket_connected = False
                logging.warning("🟠 SmartWebSocketV2 CLOSED")

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            ws_thread = threading.Thread(
                target=sws.connect,
                name="AngelWS",
                daemon=True,
            )
            ws_thread.start()
            logging.info("🟢 Live WebSocket thread started")

            # --------------------------------------------------------
            # MAIN SESSION LOOP
            # --------------------------------------------------------
            while market_is_open():
                now_dt = now_ist()

                with tick_lock:
                    nifty_tick = dict(state["nifty"]) if state["nifty"] else None
                    futures_tick = dict(state["futures"]) if state["futures"] else None
                    option_quotes = {
                        token: dict(quote)
                        for token, quote in state["options"].items()
                    }
                    option_window = {
                        key: dict(contract)
                        for key, contract in state["option_window"].items()
                    }

                # ----------------------------------------------------
                # Wait for first NIFTY tick without calling REST LTP.
                # ----------------------------------------------------
                if not nifty_tick:
                    payload = load_json(RAW_FILE, {})
                    if not isinstance(payload, dict):
                        payload = {}
                    payload.update({
                        "market_status": "OPEN",
                        "worker_status": "WAITING_FOR_NIFTY_WEBSOCKET",
                        "websocket_connected": websocket_connected,
                        "last_update_ist": now_dt.isoformat(),
                    })
                    try:
                        atomic_write_json(RAW_FILE, payload)
                    except Exception:
                        pass
                    time.sleep(PUBLISH_INTERVAL_SEC)
                    continue

                spot = float(nifty_tick["ltp"])

                # ----------------------------------------------------
                # Live day H/L from spot ticks.
                # ----------------------------------------------------
                if live_day_high is None or live_day_low is None:
                    live_day_high = spot
                    live_day_low = spot
                else:
                    live_day_high = max(live_day_high, spot)
                    live_day_low = min(live_day_low, spot)

                # ----------------------------------------------------
                # Recenter option window only when necessary.
                # ----------------------------------------------------
                try:
                    subscribe_option_window(sws)
                except Exception as exc:
                    logging.debug("Option window update warning: %s", exc)

                # ----------------------------------------------------
                # Live futures 5-minute volume.
                # ----------------------------------------------------
                live_futures_volume_5m = None
                if futures_tick and futures_tick.get("volume_day") is not None:
                    day_volume = as_float(futures_tick.get("volume_day"))
                    if day_volume is not None:
                        bucket = now_dt.replace(
                            minute=(now_dt.minute // 5) * 5,
                            second=0,
                            microsecond=0,
                        ).isoformat()

                        if bucket != futures_volume_bucket:
                            futures_volume_bucket = bucket
                            futures_volume_anchor = day_volume
                            live_futures_volume_5m = 0.0
                        elif futures_volume_anchor is not None:
                            live_futures_volume_5m = max(
                                0.0,
                                day_volume - futures_volume_anchor,
                            )

                # ----------------------------------------------------
                # Historical NIFTY 5-min candles.
                # ----------------------------------------------------
                since_success = (
                    now_dt - last_candle_fetch
                ).total_seconds()
                since_attempt = (
                    now_dt - last_candle_attempt
                ).total_seconds()

                if (
                    cached_candles is None
                    or since_success >= SPOT_CANDLE_INTERVAL_SEC
                ) and since_attempt >= candle_retry_delay:
                    last_candle_attempt = now_dt
                    try:
                        res = fetch_candles(
                            api,
                            "NSE",
                            NIFTY_SPOT_TOKEN,
                            now_dt - timedelta(days=2),
                            now_dt,
                        )

                        if res and res.get("status") and res.get("data"):
                            cached_candles = res["data"]
                            last_candle_fetch = now_dt
                            candle_retry_delay = SPOT_CANDLE_INTERVAL_SEC
                            logging.info(
                                "🟢 NIFTY 5-min candles updated: %d",
                                len(cached_candles),
                            )
                        else:
                            candle_retry_delay = min(
                                max(candle_retry_delay * 2, 2.0),
                                MAX_SPOT_CANDLE_RETRY_SEC,
                            )
                            logging.warning(
                                "⚠️ NIFTY candle API returned no data; retry %.0fs",
                                candle_retry_delay,
                            )
                    except Exception as exc:
                        candle_retry_delay = min(
                            max(candle_retry_delay * 2, 2.0),
                            MAX_SPOT_CANDLE_RETRY_SEC,
                        )
                        logging.warning(
                            "⚠️ NIFTY candle API error: %s | retry %.0fs",
                            exc,
                            candle_retry_delay,
                        )

                # ----------------------------------------------------
                # Historical NIFTY futures 5-min candles.
                # ----------------------------------------------------
                if futures_contract:
                    fut_since_success = (
                        now_dt - last_futures_candle_fetch
                    ).total_seconds()
                    fut_since_attempt = (
                        now_dt - last_futures_candle_attempt
                    ).total_seconds()

                    if (
                        cached_futures_candles is None
                        or fut_since_success >= FUTURES_CANDLE_INTERVAL_SEC
                    ) and fut_since_attempt >= futures_candle_retry_delay:
                        last_futures_candle_attempt = now_dt
                        try:
                            res = fetch_candles(
                                api,
                                "NFO",
                                futures_contract["symboltoken"],
                                now_dt - timedelta(days=2),
                                now_dt,
                            )

                            if res and res.get("status") and res.get("data"):
                                cached_futures_candles = res["data"]
                                last_futures_candle_fetch = now_dt
                                futures_candle_retry_delay = FUTURES_CANDLE_INTERVAL_SEC
                                logging.info(
                                    "🟢 NIFTY futures 5-min candles updated: %d",
                                    len(cached_futures_candles),
                                )
                            else:
                                futures_candle_retry_delay = min(
                                    max(futures_candle_retry_delay * 2, 5.0),
                                    MAX_FUTURES_CANDLE_RETRY_SEC,
                                )
                                logging.warning(
                                    "⚠️ Futures candle API returned no data; retry %.0fs",
                                    futures_candle_retry_delay,
                                )
                        except Exception as exc:
                            futures_candle_retry_delay = min(
                                max(futures_candle_retry_delay * 2, 5.0),
                                MAX_FUTURES_CANDLE_RETRY_SEC,
                            )
                            logging.warning(
                                "⚠️ Futures candle API error: %s | retry %.0fs",
                                exc,
                                futures_candle_retry_delay,
                            )

                # ----------------------------------------------------
                # Build option-chain output in strike/type order.
                # ----------------------------------------------------
                option_chain: Dict[str, Dict[str, Any]] = {}
                for key, contract in option_window.items():
                    token = str(contract["symboltoken"])
                    quote = option_quotes.get(token)
                    if quote:
                        option_chain[key] = quote
                    else:
                        # Contract exists but no tick yet. Keep contract metadata
                        # so downstream engines know the contract/token is valid.
                        option_chain[key] = dict(contract)
                        option_chain[key]["ltp"] = None
                        option_chain[key]["timestamp"] = None
                        option_chain[key]["data_status"] = "WAITING_FOR_TICK"

                # ----------------------------------------------------
                # Direct-data aliases for paper engine.
                # Paper engine will select its required strike itself from
                # option_chain. No strategy signal is read here.
                # ----------------------------------------------------
                direct_data = {
                    "spot": spot,
                    "spot_timestamp": nifty_tick.get("timestamp"),
                    "futures": futures_tick,
                    "option_chain": option_chain,
                }

                # ----------------------------------------------------
                # Freshness metadata.
                # ----------------------------------------------------
                latest_option_ts = None
                option_ts_values = [
                    q.get("timestamp")
                    for q in option_quotes.values()
                    if q.get("timestamp")
                ]
                if option_ts_values:
                    latest_option_ts = max(option_ts_values)

                # ----------------------------------------------------
                # PUBLISH RAW MEDIATOR SNAPSHOT.
                # ----------------------------------------------------
                payload = {
                    "schema_version": 2,
                    "data_source": "Angel One SmartWebSocketV2 + Historical API",
                    "market_status": "OPEN",
                    "worker_status": "LIVE" if websocket_connected else "WEBSOCKET_DISCONNECTED",
                    "session_day": session_day.isoformat(),
                    "session_start": "09:15",
                    "session_end": "15:30",
                    "last_update_ist": now_dt.isoformat(),

                    # Direct live market data.
                    "live_spot": spot,
                    "spot_timestamp": nifty_tick.get("timestamp"),
                    "direct": direct_data,

                    # Historical raw data for indicator_calc.
                    "candles": cached_candles or [],
                    "futures_candles": cached_futures_candles or [],

                    # Futures raw/live data.
                    "futures_contract": futures_contract,
                    "futures_tick": futures_tick,
                    "live_futures_volume_5m": live_futures_volume_5m,

                    # Spot session stats.
                    "live_day_high": live_day_high,
                    "live_day_low": live_day_low,

                    # Full selected option chain.
                    "option_chain": option_chain,
                    "option_chain_center": nearest_option_strike(spot),
                    "option_chain_window_points": OPTION_WINDOW_POINTS,
                    "option_chain_strike_step": OPTION_STRIKE_STEP,
                    "option_chain_latest_tick": latest_option_ts,

                    # Connection status.
                    "websocket_connected": websocket_connected,
                    "websocket_open_at": websocket_open_at,

                    # Historical API health.
                    "candle_last_success": (
                        last_candle_fetch.isoformat()
                        if cached_candles is not None
                        else None
                    ),
                    "candle_retry_delay": candle_retry_delay,
                    "futures_candle_last_success": (
                        last_futures_candle_fetch.isoformat()
                        if cached_futures_candles is not None
                        else None
                    ),
                    "futures_candle_retry_delay": futures_candle_retry_delay,
                }

                atomic_write_json(RAW_FILE, payload)
                time.sleep(PUBLISH_INTERVAL_SEC)

            # --------------------------------------------------------
            # MARKET CLOSE / SESSION END
            # --------------------------------------------------------
            logging.info(
                "⏹️ Market session ended | %s IST",
                now_ist().strftime("%H:%M:%S"),
            )

            try:
                if sws:
                    sws.close_connection()
            except Exception:
                pass

            # Preserve the last complete market snapshot but mark it closed.
            final_snapshot = load_json(RAW_FILE, {})
            if not isinstance(final_snapshot, dict):
                final_snapshot = {}
            final_snapshot["market_status"] = "CLOSED"
            final_snapshot["worker_status"] = "Market closed - last snapshot retained"
            final_snapshot["market_closed_at"] = now_ist().isoformat()
            final_snapshot["websocket_connected"] = False
            try:
                atomic_write_json(RAW_FILE, final_snapshot)
            except Exception:
                pass

            # No need to terminate the session aggressively if the SDK/server
            # is already closing. A new session is created on next market day.
            time.sleep(20)

        except Exception as exc:
            logging.exception(
                "🔴 Data worker session error: %s",
                exc,
            )

            try:
                if sws:
                    sws.close_connection()
            except Exception:
                pass

            # Never hammer login/API during an outage or rate-limit event.
            time.sleep(15)


# ============================================================
# ENTRY POINT
# ============================================================


if __name__ == "__main__":
    start_backend_factory()
