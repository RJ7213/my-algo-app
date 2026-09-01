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
#   2. Selected option live LTP# ============================================================
# PAPER ENGINE
# ============================================================
#
# Consumes:
#   data_raw.json
#   strategy_signal.json
#
# IMPORTANT
# - Paper engine NEVER talks to Angel One
# - One active position at a time
# - Duplicate signal/candle protection
# - No fake option premium
# - Actual option LTP only
# - Realized P&L updates wallet
# - Running P&L does NOT update wallet
#
# MARKET SESSION
# - 09:15 to 15:30 IST = LIVE/PAPER MODE
# - After 15:30 = NO NEW TRADE
# - After 15:30 = NO API/data processing required here
# - Existing ACTIVE trade is NOT force-closed here
#   because exit requires a fresh option LTP.
# - Dashboard should use last closing snapshot.
# ============================================================

import json
import logging
import os
import time

from datetime import datetime, timezone, timedelta


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


IST = timezone(
    timedelta(
        hours=5,
        minutes=30
    )
)


# ============================================================
# MARKET TIME
# ============================================================

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15

MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30


def now_ist():
    return datetime.now(IST)


def market_is_open(dt=None):

    if dt is None:
        dt = now_ist()

    # Saturday = 5
    # Sunday   = 6
    if dt.weekday() >= 5:
        return False

    current_minutes = (
        dt.hour * 60
        + dt.minute
    )

    open_minutes = (
        MARKET_OPEN_HOUR * 60
        + MARKET_OPEN_MINUTE
    )

    close_minutes = (
        MARKET_CLOSE_HOUR * 60
        + MARKET_CLOSE_MINUTE
    )

    return (
        open_minutes
        <= current_minutes
        < close_minutes
    )


def market_status():

    dt = now_ist()

    if dt.weekday() >= 5:
        return "WEEKEND"

    if market_is_open(dt):
        return "OPEN"

    if (
        dt.hour * 60 + dt.minute
        >= MARKET_CLOSE_HOUR * 60
        + MARKET_CLOSE_MINUTE
    ):
        return "CLOSED"

    return "PRE_OPEN"


# ============================================================
# JSON
# ============================================================

def load_json(path, default):

    if not os.path.exists(path):
        return default

    try:

        with open(path, "r") as f:
            return json.load(f)

    except Exception as exc:

        logging.warning(
            "Could not read %s: %s",
            path,
            exc
        )

        return default


def atomic_write_json(path, payload):

    tmp = f"{path}.tmp"

    with open(tmp, "w") as f:

        json.dump(
            payload,
            f,
            separators=(",", ":")
        )

    os.replace(
        tmp,
        path
    )


# ============================================================
# LEDGER
# ============================================================

def default_ledger():

    return {
        "wallet_balance": 10000.0,
        "starting_balance": 10000.0,
        "trades": [],
        "total_trades": 0,
        "target_hits": 0,
        "sl_hits": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
    }


def recalculate_ledger(dt):

    trades = dt.get(
        "trades",
        []
    )

    dt["total_trades"] = len(
        trades
    )

    closed = [
        t
        for t in trades
        if t.get("status") != "ACTIVE"
    ]

    wins = sum(
        1
        for t in closed
        if float(
            t.get(
                "pnl_realized",
                0
            )
        ) > 0
    )

    dt["target_hits"] = sum(
        1
        for t in trades
        if t.get("status")
        == "TARGET_HIT"
    )

    dt["sl_hits"] = sum(
        1
        for t in trades
        if t.get("status")
        == "SL_HIT"
    )

    dt["win_rate"] = round(
        wins
        / len(closed)
        * 100,
        1
    ) if closed else 0.0

    starting = float(
        dt.get(
            "starting_balance",
            10000.0
        )
    )

    wallet = float(
        dt.get(
            "wallet_balance",
            starting
        )
    )

    dt["total_pnl"] = round(
        wallet - starting,
        2
    )

    return dt


def load_ledger():

    default = default_ledger()

    dt = load_json(
        "trade_history.json",
        default
    )

    for key, value in default.items():

        dt.setdefault(
            key,
            value
        )

    if not isinstance(
        dt.get("trades"),
        list
    ):

        dt["trades"] = []

    return recalculate_ledger(
        dt
    )


def save_ledger(dt):

    dt = recalculate_ledger(
        dt
    )

    atomic_write_json(
        "trade_history.json",
        dt
    )

    return dt


# ============================================================
# TRADE HELPERS
# ============================================================

def next_trade_id(trades):

    max_number = 0

    for trade in trades:

        trade_id = str(
            trade.get(
                "trade_id",
                ""
            )
        )

        if trade_id.startswith("T"):

            try:

                max_number = max(
                    max_number,
                    int(
                        trade_id[1:]
                    )
                )

            except ValueError:
                pass

    return f"T{max_number + 1:06d}"


def quote_age_seconds(timestamp):

    if not timestamp:
        return 999999.0

    try:

        qt = datetime.fromisoformat(
            timestamp
        )

        if qt.tzinfo is None:

            qt = qt.replace(
                tzinfo=IST
            )

        return max(
            0,
            (
                datetime.now(
                    qt.tzinfo
                )
                - qt
            ).total_seconds()
        )

    except Exception:

        return 999999.0


def find_active_trade(ledger):

    return next(
        (
            t
            for t in ledger.get(
                "trades",
                []
            )
            if t.get("status")
            == "ACTIVE"
        ),
        None
    )


# ============================================================
# MAIN PAPER ENGINE
# ============================================================

def start_paper_engine():

    state_file = (
        "paper_engine_state.json"
    )

    state = load_json(
        state_file,
        {
            "last_processed_candle": "",
            "last_signal_key": "",
        }
    )

    last_processed_candle = state.get(
        "last_processed_candle",
        ""
    )

    last_signal_key = state.get(
        "last_signal_key",
        ""
    )

    logging.info(
        "🟢 Paper trading engine started"
    )

    last_market_state = None

    while True:

        try:

            # ====================================================
            # MARKET SESSION GUARD
            # ====================================================

            current_market_state = market_status()

            if current_market_state != last_market_state:

                last_market_state = (
                    current_market_state
                )

                if current_market_state == "OPEN":

                    logging.info(
                        "🟢 MARKET OPEN | Paper engine active"
                    )

                elif current_market_state == "PRE_OPEN":

                    logging.info(
                        "⏳ MARKET PRE-OPEN | Paper engine waiting"
                    )

                elif current_market_state == "CLOSED":

                    logging.info(
                        "🔴 MARKET CLOSED | Paper engine stopped until next session"
                    )

                elif current_market_state == "WEEKEND":

                    logging.info(
                        "🔵 WEEKEND | Paper engine sleeping"
                    )

            # ----------------------------------------------------
            # IMPORTANT:
            # Paper engine does not process new signals when
            # market is closed / weekend.
            # ----------------------------------------------------

            if not market_is_open():

                time.sleep(5)

                continue

            # ====================================================
            # LOAD DATA
            # ====================================================

            strat = load_json(
                "strategy_signal.json",
                None
            )

            raw = load_json(
                "data_raw.json",
                None
            )

            if not strat or not raw:

                time.sleep(0.5)

                continue

            ledger = load_ledger()

            spot = float(
                raw.get(
                    "live_spot",
                    strat.get(
                        "live_spot",
                        0
                    )
                )
            )

            option_quote = (
                raw.get(
                    "option_quote"
                )
                or {}
            )

            candle_time = str(
                strat.get(
                    "candle_time",
                    ""
                )
            )

            trade_type = str(
                strat.get(
                    "trade_type",
                    ""
                )
            )

            option_strike = str(
                strat.get(
                    "option_strike",
                    ""
                )
            )

            signal_key = (
                f"{candle_time}|"
                f"{trade_type}|"
                f"{option_strike}"
            )

            active = find_active_trade(
                ledger
            )

            # ====================================================
            # ACTIVE TRADE MANAGEMENT
            # ====================================================

            if active:

                active_symbol = str(
                    active.get(
                        "option_symbol",
                        ""
                    )
                )

                quote_symbol = str(
                    option_quote.get(
                        "tradingsymbol",
                        ""
                    )
                )

                opt_ltp = None

                if quote_symbol == active_symbol:

                    try:

                        opt_ltp = float(
                            option_quote["ltp"]
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        opt_ltp = None

                # ------------------------------------------------
                # RUNNING P&L
                # ------------------------------------------------

                running_pnl = 0.0

                if opt_ltp is not None:

                    running_pnl = round(
                        (
                            opt_ltp
                            - float(
                                active["entry"]
                            )
                        )
                        * int(
                            active["qty"]
                        ),
                        2
                    )

                active[
                    "current_option_ltp"
                ] = opt_ltp

                active[
                    "running_pnl"
                ] = running_pnl

                active[
                    "last_quote_time"
                ] = option_quote.get(
                    "timestamp"
                )

                active[
                    "last_spot"
                ] = spot

                save_ledger(
                    ledger
                )

                # ------------------------------------------------
                # INDEX EXIT
                # ------------------------------------------------

                trade_type_active = str(
                    active.get(
                        "type",
                        ""
                    )
                )

                index_target = float(
                    active.get(
                        "index_target",
                        spot
                    )
                )

                index_sl = float(
                    active.get(
                        "index_sl",
                        spot
                    )
                )

                is_ce_target = (
                    trade_type_active
                    == "CE_BUY"
                    and spot >= index_target
                )

                is_pe_target = (
                    trade_type_active
                    == "PE_BUY"
                    and spot <= index_target
                )

                is_ce_sl = (
                    trade_type_active
                    == "CE_BUY"
                    and spot <= index_sl
                )

                is_pe_sl = (
                    trade_type_active
                    == "PE_BUY"
                    and spot >= index_sl
                )

                target_hit = (
                    is_ce_target
                    or is_pe_target
                )

                sl_hit = (
                    is_ce_sl
                    or is_pe_sl
                )

                if target_hit or sl_hit:

                    reason = (
                        "TARGET_HIT"
                        if target_hit
                        else "SL_HIT"
                    )

                    quote_time = (
                        option_quote.get(
                            "timestamp"
                        )
                    )

                    quote_age = (
                        quote_age_seconds(
                            quote_time
                        )
                    )

                    # --------------------------------------------
                    # Fresh option quote required
                    # --------------------------------------------

                    if (
                        opt_ltp is None
                        or quote_age > 5
                    ):

                        active[
                            "exit_pending"
                        ] = True

                        active[
                            "exit_trigger"
                        ] = reason

                        active[
                            "exit_trigger_spot"
                        ] = spot

                        active[
                            "exit_trigger_time"
                        ] = now_ist().isoformat()

                        save_ledger(
                            ledger
                        )

                        logging.warning(
                            "⏳ %s reached but waiting for fresh option LTP | %s",
                            reason,
                            active_symbol
                        )

                        time.sleep(0.5)

                        continue

                    # --------------------------------------------
                    # REAL OPTION EXIT
                    # --------------------------------------------

                    entry_price = float(
                        active["entry"]
                    )

                    qty = int(
                        active["qty"]
                    )

                    exit_price = float(
                        opt_ltp
                    )

                    pnl = round(
                        (
                            exit_price
                            - entry_price
                        )
                        * qty,
                        2
                    )

                    active.update(
                        {
                            "status":
                                reason,

                            "exit_time":
                                now_ist().strftime(
                                    "%H:%M:%S"
                                ),

                            "exit_price":
                                exit_price,

                            "option_exit_ltp":
                                exit_price,

                            "pnl_realized":
                                pnl,

                            "running_pnl":
                                0.0,

                            "index_exit":
                                spot,

                            "exit_reason":
                                (
                                    "INDEX_TARGET"
                                    if reason
                                    == "TARGET_HIT"
                                    else "INDEX_STOP"
                                ),

                            "exit_quote_time":
                                quote_time,

                            "exit_quote_age":
                                round(
                                    quote_age,
                                    2
                                ),
                        }
                    )

                    # --------------------------------------------
                    # WALLET UPDATE
                    # --------------------------------------------

                    ledger[
                        "wallet_balance"
                    ] = round(
                        float(
                            ledger[
                                "wallet_balance"
                            ]
                        )
                        + pnl,
                        2
                    )

                    save_ledger(
                        ledger
                    )

                    last_processed_candle = str(
                        active.get(
                            "candle_time",
                            ""
                        )
                    )

                    last_signal_key = (
                        signal_key
                    )

                    atomic_write_json(
                        state_file,
                        {
                            "last_processed_candle":
                                last_processed_candle,

                            "last_signal_key":
                                last_signal_key,
                        }
                    )

                    logging.info(
                        "🔴 TRADE CLOSED | %s | Entry %.2f | Exit %.2f | Qty %d | P&L ₹%.2f | %s",
                        active_symbol,
                        entry_price,
                        exit_price,
                        qty,
                        pnl,
                        reason
                    )

                    time.sleep(0.5)

                    continue

            # ====================================================
            # NEW TRADE
            # ====================================================

            else:

                signal_triggered = bool(
                    strat.get(
                        "signal_triggered",
                        False
                    )
                )

                new_signal = (
                    signal_triggered
                    and candle_time
                    and candle_time
                    != last_processed_candle
                    and signal_key
                    != last_signal_key
                )

                if new_signal:

                    desired_type = str(
                        strat.get(
                            "otype",
                            ""
                        )
                    ).upper()

                    desired_strike = int(
                        float(
                            strat.get(
                                "option_strike",
                                round(
                                    spot / 50
                                ) * 50
                            )
                        )
                    )

                    quote_type = str(
                        option_quote.get(
                            "option_type",
                            ""
                        )
                    ).upper()

                    try:

                        quote_strike = float(
                            option_quote.get(
                                "strike",
                                -999999
                            )
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        quote_strike = -999999

                    quote_matches = (
                        desired_type
                        in ("CE", "PE")
                        and quote_type
                        == desired_type
                        and abs(
                            quote_strike
                            - desired_strike
                        ) < 0.01
                        and bool(
                            option_quote.get(
                                "tradingsymbol"
                            )
                        )
                    )

                    if not quote_matches:

                        logging.info(
                            "🟡 Signal ready but waiting for correct option quote | wanted %s %s | got %s %s",
                            desired_strike,
                            desired_type,
                            quote_strike,
                            quote_type
                        )

                    else:

                        try:

                            p_entry = float(
                                option_quote["ltp"]
                            )

                        except (
                            TypeError,
                            ValueError
                        ):

                            p_entry = 0.0

                        quote_time = (
                            option_quote.get(
                                "timestamp"
                            )
                        )

                        quote_age = (
                            quote_age_seconds(
                                quote_time
                            )
                        )

                        if (
                            p_entry <= 0
                            or quote_age > 5
                        ):

                            logging.info(
                                "🟡 Waiting for fresh option LTP | LTP=%.2f age=%.1fs",
                                p_entry,
                                quote_age
                            )

                        else:

                            # ------------------------------------
                            # INDEX SL
                            # ------------------------------------

                            if desired_type == "CE":

                                idx_sl = float(
                                    strat.get(
                                        "c_low",
                                        spot - 15
                                    )
                                )

                            else:

                                idx_sl = float(
                                    strat.get(
                                        "c_high",
                                        spot + 15
                                    )
                                )

                            # ------------------------------------
                            # INDEX TARGET
                            # ------------------------------------

                            if desired_type == "CE":

                                idx_target = float(
                                    strat.get(
                                        "next_w",
                                        spot + 15
                                    )
                                )

                            else:

                                idx_target = float(
                                    strat.get(
                                        "next_w",
                                        spot - 15
                                    )
                                )

                            index_sl_distance = abs(
                                spot - idx_sl
                            )

                            # ------------------------------------
                            # PREMIUM RISK
                            # ------------------------------------

                            premium_sl_distance = max(
                                5.0,
                                min(
                                    index_sl_distance
                                    * 0.50,
                                    max(
                                        5.0,
                                        p_entry
                                        * 0.50
                                    )
                                )
                            )

                            premium_target_distance = max(
                                10.0,
                                abs(
                                    idx_target
                                    - spot
                                )
                                * 0.50
                            )

                            # ------------------------------------
                            # POSITION SIZE
                            # ------------------------------------

                            wallet = float(
                                ledger[
                                    "wallet_balance"
                                ]
                            )

                            max_allowed_risk = (
                                wallet * 0.15
                            )

                            lot_size = 65

                            calculated_lots = int(
                                max_allowed_risk
                                / max(
                                    premium_sl_distance,
                                    1.0
                                )
                                / lot_size
                            )

                            qty_final = max(
                                lot_size,
                                calculated_lots
                                * lot_size
                            )

                            # ------------------------------------
                            # TRADE RECORD
                            # ------------------------------------

                            trade = {

                                "trade_id":
                                    next_trade_id(
                                        ledger[
                                            "trades"
                                        ]
                                    ),

                                "time":
                                    now_ist().strftime(
                                        "%H:%M:%S"
                                    ),

                                "type":
                                    strat.get(
                                        "trade_type"
                                    ),

                                "option_symbol":
                                    option_quote[
                                        "tradingsymbol"
                                    ],

                                "option_token":
                                    option_quote.get(
                                        "symboltoken"
                                    ),

                                "option_strike":
                                    desired_strike,

                                "option_type":
                                    desired_type,

                                "option_expiry":
                                    option_quote.get(
                                        "expiry"
                                    ),

                                "qty":
                                    qty_final,

                                "entry":
                                    round(
                                        p_entry,
                                        2
                                    ),

                                "option_entry_ltp":
                                    round(
                                        p_entry,
                                        2
                                    ),

                                "sl":
                                    round(
                                        max(
                                            0.05,
                                            p_entry
                                            - premium_sl_distance
                                        ),
                                        2
                                    ),

                                "target":
                                    round(
                                        p_entry
                                        + premium_target_distance,
                                        2
                                    ),

                                "target_dist":
                                    round(
                                        premium_target_distance,
                                        2
                                    ),

                                "sl_dist":
                                    round(
                                        premium_sl_distance,
                                        2
                                    ),

                                "index_entry":
                                    spot,

                                "index_sl":
                                    idx_sl,

                                "index_target":
                                    idx_target,

                                "status":
                                    "ACTIVE",

                                "pnl_realized":
                                    0.0,

                                "running_pnl":
                                    0.0,

                                "current_option_ltp":
                                    p_entry,

                                "strategy_used":
                                    strat.get(
                                        "strategy_used",
                                        "UNKNOWN"
                                    ),

                                "candle_time":
                                    candle_time,

                                "entry_reason":
                                    strat.get(
                                        "algo_reason",
                                        ""
                                    ),

                                "rsi":
                                    strat.get(
                                        "rsi_v"
                                    ),

                                "ema9":
                                    strat.get(
                                        "ema9"
                                    ),

                                "ema20":
                                    strat.get(
                                        "ema20"
                                    ),

                                "volume_ratio":
                                    strat.get(
                                        "vol_val"
                                    ),

                                "runway":
                                    strat.get(
                                        "run_df"
                                    ),

                                "trend":
                                    strat.get(
                                        "trend",
                                        "UNKNOWN"
                                    ),

                                "option_quote_time":
                                    quote_time,

                                "entry_quote_age":
                                    round(
                                        quote_age,
                                        2
                                    ),

                                "entry_spot":
                                    spot,

                                "entry_signal_key":
                                    signal_key,

                                # --------------------------------
                                # LEVEL ENGINE DATA
                                # --------------------------------

                                "breakout_level":
                                    strat.get(
                                        "breakout_resistance"
                                    ),

                                "breakout_level_source":
                                    strat.get(
                                        "breakout_resistance_source",
                                        ""
                                    ),

                                "order_flow_bias":
                                    strat.get(
                                        "order_flow_bias",
                                        "UNKNOWN"
                                    ),
                            }

                            ledger[
                                "trades"
                            ].append(
                                trade
                            )

                            last_signal_key = (
                                signal_key
                            )

                            save_ledger(
                                ledger
                            )

                            atomic_write_json(
                                state_file,
                                {
                                    "last_processed_candle":
                                        last_processed_candle,

                                    "last_signal_key":
                                        last_signal_key,
                                }
                            )

                            logging.info(
                                "🟢 PAPER ENTRY | %s | %s | Entry ₹%.2f | Qty %d | SL ₹%.2f | Target ₹%.2f | Strategy=%s",
                                option_quote[
                                    "tradingsymbol"
                                ],
                                trade_type,
                                p_entry,
                                qty_final,
                                trade["sl"],
                                trade["target"],
                                trade[
                                    "strategy_used"
                                ]
                            )

        except Exception as exc:

            logging.exception(
                "Paper engine error: %s",
                exc
            )

        time.sleep(0.5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    start_paper_engine()
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
# NIFTY FUTURES CONTRACT
# ============================================================

def make_future_contract(item, today):
    symbol = str(item.get("tradingsymbol") or item.get("symbol") or "").upper().strip()
    if not symbol.startswith("NIFTY") or not symbol.endswith("FUT"):
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
            return {}, None

        if not response.get("status"):
            logging.warning(
                "searchScrip unsuccessful: %s",
                response
            )
            return {}, None

        items = response.get("data") or []

        if not items:
            logging.warning(
                "searchScrip returned zero contracts"
            )
            return {}, None

        cache = {}
        nearest_future = None

        for item in items:

            future_candidate = make_future_contract(item, today)
            if future_candidate:
                if (
                    nearest_future is None
                    or (future_candidate.get("expiry") or "9999-12-31")
                    < (nearest_future.get("expiry") or "9999-12-31")
                ):
                    nearest_future = future_candidate

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
        if nearest_future:
            logging.info(
                "🟢 NIFTY FUT selected from same master: %s | token=%s | expiry=%s",
                nearest_future["tradingsymbol"],
                nearest_future["symboltoken"],
                nearest_future.get("expiry"),
            )

        return cache, nearest_future

    except Exception as exc:

        logging.warning(
            "⚠️ NIFTY option master load failed: %s",
            exc
        )

        return {}, None


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
            cached_futures_candles = None

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

            # Futures candle API is slower than live ticks and is only needed
            # for completed-candle volume history. Never hammer the endpoint.
            last_futures_candle_fetch = datetime.min.replace(tzinfo=IST)
            last_futures_candle_attempt = datetime.min.replace(tzinfo=IST)
            futures_candle_retry_delay = 300.0
            MAX_FUTURES_CANDLE_RETRY = 900.0

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

            option_master, futures_contract = load_nifty_option_master(
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
                "futures": None,
            }

            # Live session statistics. These are updated from ticks, not
            # from the slow historical candle endpoint.
            session_day = now_ist().date()
            live_day_high = None
            live_day_low = None
            futures_volume_bucket = None
            futures_volume_anchor = None

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
                    # NIFTY FUTURES SUBSCRIPTION - SNAP_QUOTE/MODE 3
                    # Gives live cumulative traded volume.
                    # ------------------------------------------------
                    if futures_contract:
                        sws.subscribe(
                            "nifty-fut-algo",
                            3,
                            [
                                {
                                    "exchangeType": 2,
                                    "tokens": [
                                        str(futures_contract["symboltoken"])
                                    ],
                                }
                            ],
                        )
                        logging.info(
                            "🟢 NIFTY FUT WebSocket subscription active: %s | token=%s | mode=3",
                            futures_contract["tradingsymbol"],
                            futures_contract["symboltoken"],
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
                        # NIFTY FUTURES
                        # ------------------------------------------------

                        elif (
                            futures_contract
                            and token == str(futures_contract["symboltoken"])
                        ):
                            volume_day_raw = message.get("volume_trade_for_the_day")
                            volume_day = None
                            if volume_day_raw is not None:
                                try:
                                    volume_day = float(volume_day_raw)
                                except (TypeError, ValueError):
                                    volume_day = None

                            ticks["futures"] = {
                                "ltp": price,
                                "timestamp": ts.isoformat(),
                                "volume_day": volume_day,
                                "last_traded_quantity": message.get("last_traded_quantity"),
                            }

                            if volume_day is not None:
                                logging.info(
                                    "📊 NIFTY FUT TICK: %.2f | day_volume=%.0f",
                                    price,
                                    volume_day,
                                )
                            else:
                                logging.info(
                                    "📊 NIFTY FUT TICK: %.2f | volume field unavailable",
                                    price,
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

                        futures_tick = (
                            dict(
                                ticks["futures"]
                            )
                            if ticks["futures"]
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
                    # LIVE DAY HIGH / LOW FROM EVERY NIFTY TICK
                    # =================================================
                    if session_day != now_dt.date():
                        session_day = now_dt.date()
                        live_day_high = spot
                        live_day_low = spot
                    else:
                        live_day_high = spot if live_day_high is None else max(live_day_high, spot)
                        live_day_low = spot if live_day_low is None else min(live_day_low, spot)

                    # =================================================
                    # LIVE 5-MIN FUTURES VOLUME
                    # =================================================
                    live_futures_volume_5m = None
                    if futures_tick and futures_tick.get("volume_day") is not None:
                        try:
                            day_volume = float(futures_tick["volume_day"])
                            bucket = now_dt.replace(
                                minute=(now_dt.minute // 5) * 5,
                                second=0,
                                microsecond=0,
                            ).isoformat()
                            if bucket != futures_volume_bucket:
                                futures_volume_bucket = bucket
                                futures_volume_anchor = day_volume
                                live_futures_volume_5m = 0.0
                            else:
                                live_futures_volume_5m = max(0.0, day_volume - float(futures_volume_anchor or day_volume))
                        except (TypeError, ValueError):
                            live_futures_volume_5m = None

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
                    # NIFTY FUTURES 5-MIN CANDLES FOR VOLUME HISTORY
                    # =================================================
                    if futures_contract:
                        fut_since_success = (now_dt - last_futures_candle_fetch).total_seconds()
                        fut_since_attempt = (now_dt - last_futures_candle_attempt).total_seconds()
                        fut_due = (cached_futures_candles is None or fut_since_success >= 300)
                        fut_retry_allowed = fut_since_attempt >= futures_candle_retry_delay

                        if fut_due and fut_retry_allowed:
                            last_futures_candle_attempt = now_dt
                            try:
                                fut_from = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                                fut_to = now_dt.strftime("%Y-%m-%d %H:%M")
                                logging.info("📡 Requesting NIFTY FUTURES 5-min candles: %s", futures_contract["tradingsymbol"])
                                fut_res = api.getCandleData({
                                    "exchange": "NFO",
                                    "symboltoken": str(futures_contract["symboltoken"]),
                                    "interval": "FIVE_MINUTE",
                                    "fromdate": fut_from,
                                    "todate": fut_to,
                                })
                                if fut_res and fut_res.get("status") and fut_res.get("data"):
                                    cached_futures_candles = fut_res["data"]
                                    last_futures_candle_fetch = now_dt
                                    futures_candle_retry_delay = 300.0
                                    logging.info("🟢 NIFTY FUTURES candles updated: %d candles", len(cached_futures_candles))
                                else:
                                    futures_candle_retry_delay = min(futures_candle_retry_delay * 2, MAX_FUTURES_CANDLE_RETRY)
                                    logging.warning("⚠️ NIFTY FUTURES candle API returned no data; retry in %.0fs", futures_candle_retry_delay)
                            except Exception as fut_err:
                                futures_candle_retry_delay = min(futures_candle_retry_delay * 2, MAX_FUTURES_CANDLE_RETRY)
                                logging.warning("⚠️ NIFTY FUTURES candle API error: %s | retry in %.0fs", fut_err, futures_candle_retry_delay)

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

                        "futures_candles":
                            cached_futures_candles or [],

                        "futures_contract":
                            futures_contract,

                        "futures_tick":
                            futures_tick,

                        "live_futures_volume_5m":
                            live_futures_volume_5m,

                        "live_day_high":
                            live_day_high,

                        "live_day_low":
                            live_day_low,

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
