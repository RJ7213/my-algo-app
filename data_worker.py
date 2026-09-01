# data_worker.py
# ONLY component that talks to Angel One.
# WebSocket = live NIFTY + option LTP
# REST = historical candles + contract resolution only
#
# IMPORTANT:
# - No REST LTP polling while WebSocket is running.
# - searchScrip is NOT called continuously.
# - Historical candles refresh only once per minute.
# - Existing data_raw.json is preserved if a temporary API error occurs.

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import pyotp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

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

    m = re.search(
        r"(\d{1,2}[A-Z]{3}\d{2,4})",
        symbol.upper()
    )

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

            # Some SmartAPI masters represent strike in paise.
            if value > 100000:
                value /= 100.0

            return value

        except (TypeError, ValueError):
            pass

    symbol = str(item.get("tradingsymbol", ""))

    m = re.search(
        r"(\d+(?:\.\d+)?)(?:CE|PE)$",
        symbol.upper()
    )

    if m:
        try:
            value = float(m.group(1))

            # Defensive handling for unusual representations.
            if value > 100000:
                value /= 100.0

            return value

        except ValueError:
            pass

    return None


def resolve_option(api, strike, opt_type, today):
    """
    Resolve nearest valid NIFTY option.
    searchScrip is deliberately called only when the requested
    strike/type changes.
    """

    try:
        logging.info(
            "Resolving option contract: NIFTY %s %s",
            strike,
            opt_type
        )

        response = api.searchScrip("NFO", "NIFTY")

        if not response or not response.get("status"):
            logging.warning("searchScrip returned unsuccessful response")
            return None

        items = response.get("data") or []

        if not items:
            logging.warning("searchScrip returned no contracts")
            return None

        candidates = []

        for item in items:

            if option_type(item) != opt_type:
                continue

            s = strike_value(item)

            if s is None:
                continue

            if abs(s - float(strike)) > 0.01:
                continue

            expiry = extract_expiry(item)

            if expiry is not None and expiry < today:
                continue

            token = item.get("symboltoken") or item.get("token")
            symbol = item.get("tradingsymbol") or item.get("symbol")

            if not token or not symbol:
                continue

            candidates.append(
                (
                    expiry or today,
                    str(symbol),
                    str(token),
                    item,
                )
            )

        if not candidates:
            logging.warning(
                "No valid option found for %s %s",
                strike,
                opt_type
            )
            return None

        candidates.sort(key=lambda x: (x[0], x[1]))

        expiry, symbol, token, raw = candidates[0]

        contract = {
            "exchange": "NFO",
            "tradingsymbol": symbol,
            "symboltoken": token,
            "strike": float(strike),
            "option_type": opt_type,
            "expiry": expiry.isoformat() if expiry else None,
        }

        logging.info(
            "Option resolved: %s | token=%s | expiry=%s",
            symbol,
            token,
            expiry
        )

        return contract

    except Exception as exc:
        logging.error(
            "Option contract resolution failed: %s",
            exc
        )
        return None


def start_backend_factory():

    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2

    while True:

        sws = None

        try:

            if not all((CID, AKEY, PIN, TKEY)):
                raise RuntimeError(
                    "ANGEL_CLIENT_CODE/API_KEY/PIN/TOTP_SECRET "
                    "environment variables are required"
                )

            logging.info("Angel One live data worker starting...")

            api = SmartConnect(
                api_key=AKEY,
                timeout=15
            )

            tok = pyotp.TOTP(
                TKEY.replace(" ", "").strip().upper()
            ).now()

            session = api.generateSession(
                CID,
                PIN,
                tok
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

            cached_candles = None
            last_candle_fetch = datetime.min.replace(tzinfo=IST)

            option_contract = None
            option_hint_key = None

            tick_lock = threading.Lock()

            ticks = {
                "nifty": None,
                "option": None,
            }

            sws = SmartWebSocketV2(
                auth_token,
                AKEY,
                CID,
                feed_token
            )

            websocket_connected = False

            def on_open(wsapp):

                nonlocal websocket_connected

                websocket_connected = True

                logging.info(
                    "🟢 SmartWebSocketV2 CONNECTED"
                )

                try:

                    sws.subscribe(
                        "nifty-algo",
                        1,
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
                        "🟢 NIFTY WebSocket subscription active"
                    )

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

                except Exception as exc:

                    logging.error(
                        "WebSocket subscribe error: %s",
                        exc
                    )

            def on_data(wsapp, message):

                try:

                    if not isinstance(message, dict):
                        return

                    token = str(
                        message.get("token", "")
                    )

                    price_raw = message.get(
                        "last_traded_price"
                    )

                    if price_raw is None:
                        return

                    price = float(price_raw) / 100.0

                    ts_raw = message.get(
                        "exchange_timestamp"
                    )

                    if ts_raw:

                        try:
                            ts = (
                                datetime.fromtimestamp(
                                    float(ts_raw) / 1000.0,
                                    tz=timezone.utc,
                                )
                                .astimezone(IST)
                            )

                        except Exception:
                            ts = now_ist()

                    else:
                        ts = now_ist()

                    with tick_lock:

                        if token == str(NIFTY_SPOT_TOKEN):

                            ticks["nifty"] = {
                                "ltp": price,
                                "timestamp": ts.isoformat(),
                            }

                            logging.info(
                                "🟢 NIFTY TICK: %.2f",
                                price
                            )

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
                                "timestamp": ts.isoformat(),
                            }

                            logging.info(
                                "🟢 OPTION TICK %s: %.2f",
                                option_contract[
                                    "tradingsymbol"
                                ],
                                price,
                            )

                except Exception as exc:

                    logging.debug(
                        "Tick parse error: %s",
                        exc
                    )

            def on_error(wsapp, error):

                logging.error(
                    "🔴 SmartWebSocketV2 ERROR: %s",
                    error
                )

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

            ws_thread = threading.Thread(
                target=sws.connect,
                daemon=True
            )

            ws_thread.start()

            logging.info(
                "Live WebSocket worker started"
            )

            # -------------------------------------------------
            # MAIN DATA LOOP
            # -------------------------------------------------

            while True:

                now_dt = now_ist()

                try:

                    with tick_lock:

                        nifty_tick = (
                            dict(ticks["nifty"])
                            if ticks["nifty"]
                            else None
                        )

                        option_tick = (
                            dict(ticks["option"])
                            if ticks["option"]
                            else None
                        )

                    # -------------------------------------------------
                    # IMPORTANT:
                    # DO NOT repeatedly call ltpData().
                    #
                    # WebSocket is the live source.
                    # If no tick yet, wait.
                    # This prevents API rate-limit errors.
                    # -------------------------------------------------

                    if nifty_tick is None:

                        logging.info(
                            "Waiting for first NIFTY WebSocket tick..."
                        )

                        time.sleep(0.5)
                        continue

                    spot = float(
                        nifty_tick["ltp"]
                    )

                    # -------------------------------------------------
                    # HISTORICAL 5-MIN CANDLES
                    # REST call maximum roughly once/minute.
                    # -------------------------------------------------

                    candle_due = (
                        cached_candles is None
                        or (
                            now_dt - last_candle_fetch
                        ).total_seconds() >= 60
                    )

                    if candle_due:

                        from_d = (
                            now_dt - timedelta(days=2)
                        ).strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        to_d = now_dt.strftime(
                            "%Y-%m-%d %H:%M"
                        )

                        try:

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

                                cached_candles = res["data"]

                                last_candle_fetch = now_dt

                                logging.info(
                                    "🟢 5-min candle data updated: %d candles",
                                    len(cached_candles)
                                )

                            else:

                                logging.warning(
                                    "5-min candle API returned no data"
                                )

                                # Move retry to future instead of
                                # hammering the API.
                                last_candle_fetch = (
                                    now_dt
                                    - timedelta(seconds=45)
                                )

                        except Exception as candle_err:

                            logging.warning(
                                "Candle API error: %s",
                                candle_err
                            )

                            # Prevent immediate repeated retries.
                            last_candle_fetch = now_dt

                    # -------------------------------------------------
                    # READ OPTION CONTRACT HINT
                    # -------------------------------------------------

                    desired_hint = None

                    if os.path.exists(
                        "strategy_signal.json"
                    ):

                        try:

                            with open(
                                "strategy_signal.json",
                                "r"
                            ) as sf:

                                strat = json.load(sf)

                            if (
                                strat.get("otype")
                                and strat.get(
                                    "option_strike"
                                ) is not None
                            ):

                                desired_hint = (
                                    f"{int(float(strat['option_strike']))}:"
                                    f"{strat['otype']}"
                                )

                        except Exception as signal_err:

                            logging.debug(
                                "Strategy signal read error: %s",
                                signal_err
                            )

                    # -------------------------------------------------
                    # RESOLVE OPTION ONLY WHEN HINT CHANGES
                    # -------------------------------------------------

                    if (
                        desired_hint
                        and desired_hint != option_hint_key
                    ):

                        strike_s, opt_type = (
                            desired_hint.split(":", 1)
                        )

                        resolved = resolve_option(
                            api,
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

                            try:

                                if old_token:

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

                            option_contract = resolved
                            option_hint_key = desired_hint

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
                                            ],
                                        }
                                    ],
                                )

                                logging.info(
                                    "🟢 OPTION WebSocket subscription active: %s",
                                    option_contract[
                                        "tradingsymbol"
                                    ]
                                )

                            except Exception as sub_err:

                                logging.warning(
                                    "Option subscribe error: %s",
                                    sub_err
                                )

                    # -------------------------------------------------
                    # BUILD OPTION QUOTE
                    # -------------------------------------------------

                    option_quote = None

                    if option_contract and option_tick:

                        option_quote = {
                            **option_contract,
                            "ltp": float(
                                option_tick["ltp"]
                            ),
                            "timestamp":
                                option_tick["timestamp"],
                        }

                    # -------------------------------------------------
                    # PUBLISH DATA
                    # -------------------------------------------------

                    payload = {
                        "live_spot": spot,
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
                    }

                    atomic_write_json(
                        "data_raw.json",
                        payload
                    )

                except Exception as loop_err:

                    logging.error(
                        "Worker loop error: %s",
                        loop_err
                    )

                # Live tick publishing.
                time.sleep(0.25)

        except Exception as conn_err:

            logging.error(
                "Critical worker error: %s. Restarting in 10 sec...",
                conn_err
            )

            try:

                if sws:
                    sws.close_connection()

            except Exception:
                pass

            time.sleep(10)


if __name__ == "__main__":
    start_backend_factory()
