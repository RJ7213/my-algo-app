# data_worker.py
# Data Worker is the ONLY component that talks to Angel One.
# It publishes NIFTY spot/candles and the currently requested option LTP.

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pyotp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CID = os.getenv("ANGEL_CLIENT_CODE")
AKEY = os.getenv("ANGEL_API_KEY")
PIN = os.getenv("ANGEL_PIN")
TKEY = os.getenv("ANGEL_TOTP_SECRET")
NIFTY_SPOT_TOKEN = os.getenv("NIFTY_SPOT_TOKEN", "99926000")

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)


def extract_expiry(item):
    """Best-effort expiry extraction from SmartAPI searchScrip response."""
    raw = str(item.get("expiry", "") or "").strip()
    if raw:
        for fmt in ("%d%b%Y", "%d%b%y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.upper(), fmt).date()
            except ValueError:
                pass

    symbol = str(item.get("tradingsymbol", ""))
    # Common NIFTY derivative formats contain DDMMMYY / DDMMMYYYY.
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
        value = str(item.get(key, "")).upper().strip()
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
            # Some scrip masters represent strike in paise.
            if value > 100000:
                value /= 100.0
            return value
        except (TypeError, ValueError):
            pass
    symbol = str(item.get("tradingsymbol", ""))
    # Fallback: last numeric run before CE/PE.
    m = re.search(r"(\d+(?:\.\d+)?)(?:CE|PE)$", symbol.upper())
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def resolve_option(api, strike, opt_type, today):
    """Resolve nearest valid NIFTY option contract for requested strike/type."""
    try:
        response = api.searchScrip("NFO", "NIFTY")
        items = response.get("data") if response and response.get("status") else []
        if not items:
            return None

        candidates = []
        for item in items:
            if option_type(item) != opt_type:
                continue
            s = strike_value(item)
            if s is None or abs(s - float(strike)) > 0.01:
                continue
            expiry = extract_expiry(item)
            if expiry is not None and expiry < today:
                continue
            token = item.get("symboltoken") or item.get("token")
            symbol = item.get("tradingsymbol") or item.get("symbol")
            if token and symbol:
                candidates.append((expiry or today, str(symbol), str(token), item))

        if not candidates:
            return None

        # Nearest future expiry first; lexical symbol is only a deterministic fallback.
        candidates.sort(key=lambda x: (x[0], x[1]))
        expiry, symbol, token, raw = candidates[0]
        return {
            "exchange": "NFO",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "strike": float(strike),
            "option_type": opt_type,
            "expiry": expiry.isoformat() if expiry else None,
        }
    except Exception as exc:
        logging.warning("Option contract resolution failed: %s", exc)
        return None


def start_backend_factory():
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    while True:
        sws = None
        try:
            if not all((CID, AKEY, PIN, TKEY)):
                raise RuntimeError("ANGEL_CLIENT_CODE/API_KEY/PIN/TOTP_SECRET environment variables are required")

            logging.info("Angel One live data worker starting...")
            api = SmartConnect(api_key=AKEY, timeout=15)
            tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
            session = api.generateSession(CID, PIN, tok)
            if not session or not session.get("status"):
                raise RuntimeError(f"API session failed: {session}")

            auth_token = session["data"]["jwtToken"]
            feed_token = api.getfeedToken()
            if not feed_token:
                raise RuntimeError("Unable to obtain SmartAPI feed token")

            cached_candles = None
            last_candle_fetch = datetime.min.replace(tzinfo=IST)
            option_contract = None
            option_hint_key = None
            tick_lock = threading.Lock()
            ticks = {"nifty": None, "option": None}

            sws = SmartWebSocketV2(auth_token, AKEY, CID, feed_token)

            def on_open(wsapp):
                logging.info("SmartWebSocketV2 connected")
                try:
                    sws.subscribe("nifty-algo", 1, [{"exchangeType": 1, "tokens": [str(NIFTY_SPOT_TOKEN)]}])
                    if option_contract:
                        sws.subscribe("option-algo", 1, [{"exchangeType": 2, "tokens": [str(option_contract["symboltoken"])]}])
                except Exception as exc:
                    logging.error("WebSocket subscribe error: %s", exc)

            def on_data(wsapp, message):
                try:
                    if not isinstance(message, dict):
                        return
                    token = str(message.get("token", ""))
                    price_raw = message.get("last_traded_price")
                    if price_raw is None:
                        return
                    price = float(price_raw) / 100.0
                    ts_raw = message.get("exchange_timestamp")
                    ts = datetime.fromtimestamp(float(ts_raw) / 1000.0, tz=timezone.utc).astimezone(IST) if ts_raw else now_ist()
                    with tick_lock:
                        if token == str(NIFTY_SPOT_TOKEN):
                            ticks["nifty"] = {"ltp": price, "timestamp": ts.isoformat()}
                        elif option_contract and token == str(option_contract["symboltoken"]):
                            ticks["option"] = {"ltp": price, "timestamp": ts.isoformat()}
                except Exception as exc:
                    logging.debug("Tick parse error: %s", exc)

            def on_error(wsapp, error):
                logging.error("SmartWebSocketV2 error: %s", error)

            def on_close(wsapp):
                logging.warning("SmartWebSocketV2 closed")

            sws.on_open = on_open
            sws.on_data = on_data
            sws.on_error = on_error
            sws.on_close = on_close

            ws_thread = threading.Thread(target=sws.connect, daemon=True)
            ws_thread.start()

            logging.info("Live WebSocket worker started")

            while True:
                now_dt = now_ist()
                try:
                    # Read latest NIFTY tick. REST is only a safety fallback if the socket has not delivered a tick yet.
                    with tick_lock:
                        nifty_tick = dict(ticks["nifty"]) if ticks["nifty"] else None
                        option_tick = dict(ticks["option"]) if ticks["option"] else None

                    if nifty_tick is None:
                        ltp = api.ltpData("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
                        if ltp and ltp.get("status") and ltp.get("data"):
                            nifty_tick = {"ltp": float(ltp["data"]["ltp"]), "timestamp": now_dt.isoformat()}

                    if not nifty_tick:
                        time.sleep(0.5)
                        continue

                    spot = float(nifty_tick["ltp"])

                    # Refresh historical 5-min candles roughly once per minute.
                    if cached_candles is None or (now_dt - last_candle_fetch).total_seconds() > 60:
                        from_d = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                        to_d = now_dt.strftime("%Y-%m-%d %H:%M")
                        res = api.getCandleData({
                            "exchange": "NSE",
                            "symboltoken": NIFTY_SPOT_TOKEN,
                            "interval": "FIVE_MINUTE",
                            "fromdate": from_d,
                            "todate": to_d,
                        })
                        if res and res.get("status") and res.get("data"):
                            cached_candles = res["data"]
                            last_candle_fetch = now_dt

                    # The indicator engine publishes the desired contract hint. Resolve it here so ONLY Data Worker talks to API.
                    desired_hint = None
                    if os.path.exists("strategy_signal.json"):
                        try:
                            with open("strategy_signal.json", "r") as sf:
                                strat = json.load(sf)
                            if strat.get("otype") and strat.get("option_strike"):
                                desired_hint = f"{int(float(strat['option_strike']))}:{strat['otype']}"
                        except Exception:
                            pass

                    if desired_hint and desired_hint != option_hint_key:
                        strike_s, opt_type = desired_hint.split(":", 1)
                        resolved = resolve_option(api, float(strike_s), opt_type, now_dt.date())
                        if resolved:
                            try:
                                if option_contract:
                                    sws.unsubscribe("option-algo", 1, [{"exchangeType": 2, "tokens": [str(option_contract["symboltoken"])]}])
                            except Exception:
                                pass
                            option_contract = resolved
                            option_hint_key = desired_hint
                            option_tick = None
                            with tick_lock:
                                ticks["option"] = None
                            try:
                                sws.subscribe("option-algo", 1, [{"exchangeType": 2, "tokens": [str(option_contract["symboltoken"])]}])
                            except Exception as exc:
                                logging.warning("Option subscribe error: %s", exc)

                    option_quote = None
                    if option_contract and option_tick:
                        option_quote = {
                            **option_contract,
                            "ltp": float(option_tick["ltp"]),
                            "timestamp": option_tick["timestamp"],
                        }

                    payload = {
                        "live_spot": spot,
                        "spot_timestamp": nifty_tick.get("timestamp"),
                        "candles": cached_candles or [],
                        "last_update": now_dt.strftime("%H:%M:%S"),
                        "option_quote": option_quote,
                    }
                    atomic_write_json("data_raw.json", payload)
                except Exception as loop_err:
                    logging.error("Worker loop error: %s", loop_err)
                time.sleep(0.5)
        except Exception as conn_err:
            logging.error("Critical worker error: %s. Restarting in 10 sec...", conn_err)
            try:
                if sws:
                    sws.close_connection()
            except Exception:
                pass
            time.sleep(10)


if __name__ == "__main__":
    start_backend_factory()
