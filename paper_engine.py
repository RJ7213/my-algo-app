# paper_engine.py
#
# Paper engine NEVER talks to Angel One.
# It consumes:
#   data_raw.json
#   strategy_signal.json
#
# IMPORTANT:
# - No daily trade limit for observation phase.
# - No fake ₹100 option premium.
# - Actual option LTP is used.
# - Existing trade history is preserved.
# - One active position at a time.
# - Duplicate signal/candle protection.
# - Running P&L does NOT alter wallet.
# - Realized P&L alters wallet only after exit.

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    return datetime.now(IST)


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

    os.replace(tmp, path)


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
        (
            wins
            / len(closed)
            * 100
        ),
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
            0.0,
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

    for trade in ledger.get(
        "trades",
        []
    ):

        if trade.get(
            "status"
        ) == "ACTIVE":

            return trade

    return None


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

    while True:

        try:

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

            # =====================================================
            # ACTIVE TRADE MANAGEMENT
            # =====================================================

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

                if (
                    quote_symbol
                    == active_symbol
                ):

                    try:

                        opt_ltp = float(
                            option_quote[
                                "ltp"
                            ]
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        opt_ltp = None

                # -------------------------------------------------
                # RUNNING P&L
                # -------------------------------------------------

                running_pnl = 0.0

                if opt_ltp is not None:

                    running_pnl = round(
                        (
                            opt_ltp
                            - float(
                                active[
                                    "entry"
                                ]
                            )
                        )
                        * int(
                            active[
                                "qty"
                            ]
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

                # Running state only.
                # Wallet remains unchanged.
                save_ledger(
                    ledger
                )

                # -------------------------------------------------
                # INDEX EXIT CONDITIONS
                # -------------------------------------------------

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
                    and spot
                    >= index_target
                )

                is_pe_target = (
                    trade_type_active
                    == "PE_BUY"
                    and spot
                    <= index_target
                )

                is_ce_sl = (
                    trade_type_active
                    == "CE_BUY"
                    and spot
                    <= index_sl
                )

                is_pe_sl = (
                    trade_type_active
                    == "PE_BUY"
                    and spot
                    >= index_sl
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

                    exit_reason = (
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

                    # Never invent exit LTP.
                    if (
                        opt_ltp is None
                        or quote_age > 5
                    ):

                        active[
                            "exit_pending"
                        ] = True

                        active[
                            "exit_trigger"
                        ] = exit_reason

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
                            exit_reason,
                            active_symbol
                        )

                        time.sleep(0.5)
                        continue

                    # -------------------------------------------------
                    # REAL OPTION EXIT
                    # -------------------------------------------------

                    exit_price = float(
                        opt_ltp
                    )

                    entry_price = float(
                        active[
                            "entry"
                        ]
                    )

                    qty = int(
                        active[
                            "qty"
                        ]
                    )

                    pnl = round(
                        (
                            exit_price
                            - entry_price
                        )
                        * qty,
                        2
                    )

                    active[
                        "status"
                    ] = exit_reason

                    active[
                        "exit_time"
                    ] = now_ist().strftime(
                        "%H:%M:%S"
                    )

                    active[
                        "exit_price"
                    ] = exit_price

                    active[
                        "option_exit_ltp"
                    ] = exit_price

                    active[
                        "pnl_realized"
                    ] = pnl

                    active[
                        "running_pnl"
                    ] = 0.0

                    active[
                        "index_exit"
                    ] = spot

                    active[
                        "exit_reason"
                    ] = (
                        "INDEX_TARGET"
                        if exit_reason
                        == "TARGET_HIT"
                        else "INDEX_STOP"
                    )

                    active[
                        "exit_quote_time"
                    ] = quote_time

                    active[
                        "exit_quote_age"
                    ] = round(
                        quote_age,
                        2
                    )

                    # -------------------------------------------------
                    # WALLET UPDATED ONLY HERE
                    # -------------------------------------------------

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

                    logging.info(
                        "🔴 TRADE CLOSED | %s | Entry %.2f | Exit %.2f | Qty %d | P&L ₹%.2f | %s",
                        active_symbol,
                        entry_price,
                        exit_price,
                        qty,
                        pnl,
                        exit_reason
                    )

                    last_processed_candle = str(
                        active.get(
                            "candle_time",
                            ""
                        )
                    )

                    last_signal_key = signal_key

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

                    time.sleep(0.5)
                    continue

            # =====================================================
            # NEW TRADE
            # =====================================================

            else:

                signal_triggered = bool(
                    strat.get(
                        "signal_triggered",
                        False
                    )
                )

                # Observation phase:
                # NO DAILY LIMIT.
                #
                # Still prevent the same signal/candle
                # from generating duplicate trades.

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
                                    spot / 50.0
                                )
                                * 50
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
                                option_quote[
                                    "ltp"
                                ]
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

                            # -------------------------------------------------
                            # INDEX SL
                            # -------------------------------------------------

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

                            # -------------------------------------------------
                            # INDEX TARGET
                            # -------------------------------------------------

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

                            # -------------------------------------------------
                            # PREMIUM RISK MODEL
                            #
                            # Current observation phase.
                            # No daily trade-count restriction.
                            # Position size remains risk based.
                            # -------------------------------------------------

                            premium_sl_distance = max(
                                5.0,
                                min(
                                    index_sl_distance
                                    * 0.50,
                                    max(
                                        5.0,
                                        p_entry * 0.50
                                    )
                                )
                            )

                            # Target based on available
                            # index runway.
                            premium_target_distance = max(
                                10.0,
                                abs(
                                    idx_target
                                    - spot
                                )
                                * 0.50
                            )

                            # -------------------------------------------------
                            # MAX RISK = 15% WALLET
                            #
                            # This is NOT a daily trade limit.
                            # It only controls quantity.
                            # -------------------------------------------------

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

                            # -------------------------------------------------
                            # TRADE RECORD
                            # -------------------------------------------------

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
                            }

                            ledger[
                                "trades"
                            ].append(
                                trade
                            )

                            # IMPORTANT:
                            # Do not mark the candle processed yet.
                            # The active trade itself prevents duplicate entry.
                            #
                            # last_signal_key is saved to protect
                            # against restart/repeated signal.

                            last_signal_key = signal_key

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
                                trade[
                                    "option_symbol"
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


if __name__ == "__main__":
    start_paper_engine()
 
