import json
import math
from datetime import datetime, timezone, timedelta

import streamlit as st


# ============================================================
# NIFTY PAPER - FINAL MOBILE DASHBOARD
# READ-ONLY
# No strategy calculations
# No orders
# No dashboard-side trading decisions
# ============================================================

st.set_page_config(
    page_title="NIFTY Paper",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

IST = timezone(timedelta(hours=5, minutes=30))


FILES = {
    "raw": "data_raw.json",
    "ind": "processed_indicators.json",
    "structure": "processed_market_structure.json",
    "paper": "paper_engine_output.json",
    "journal": "trade_history.json",
}


# ============================================================
# MOBILE UI
# ============================================================

st.markdown(
    """
<style>
#MainMenu, footer, header {
    visibility:hidden;
}

[data-testid="stAppViewContainer"] {
    background:#f4f7f9;
}

.main .block-container {
    max-width:560px;
    padding:.35rem .35rem 1rem;
}

[data-testid="stTabs"] button {
    font-size:12px;
    font-weight:800;
    padding:7px 3px;
}

[data-testid="stTabs"] [role="tablist"] {
    gap:1px;
}

.section {
    font-size:11px;
    font-weight:900;
    color:#334155;
    margin:8px 2px 4px;
}

.grid2, .grid3 {
    display:grid;
    gap:5px;
    width:100%;
    margin:3px 0;
}

.grid2 {
    grid-template-columns:repeat(2,minmax(0,1fr));
}

.grid3 {
    grid-template-columns:repeat(3,minmax(0,1fr));
}

.card {
    background:#ffffff;
    border:1px solid #d9e1e8;
    border-radius:9px;
    padding:7px 8px;
    min-width:0;
    box-shadow:0 1px 2px rgba(15,23,42,.04);
}

.card.main {
    padding:9px 10px;
}

.lbl {
    font-size:8px;
    color:#64748b;
    text-transform:uppercase;
    letter-spacing:.4px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.val {
    font-size:15px;
    font-weight:900;
    color:#0f172a;
    line-height:1.1;
    margin-top:2px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.main .val {
    font-size:19px;
}

.sub {
    font-size:7px;
    color:#94a3b8;
    margin-top:2px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.trade {
    background:#ffffff;
    border:1px solid #cbd8e5;
    border-radius:10px;
    padding:9px 10px;
    margin:4px 0;
    box-shadow:0 1px 2px rgba(15,23,42,.04);
}

.status {
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:5px;
    background:#ffffff;
    border:1px solid #d9e1e8;
    border-radius:8px;
    padding:6px 8px;
    min-width:0;
}

.status .left {
    min-width:0;
}

.status b {
    color:#1e293b;
    font-size:10px;
}

.status .detail {
    font-size:7px;
    color:#94a3b8;
    display:block;
    margin-top:1px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.green {
    color:#159447 !important;
}

.red {
    color:#dc3545 !important;
}

.yellow {
    color:#b77900 !important;
}

.muted {
    color:#64748b !important;
}

.big {
    font-size:21px;
    font-weight:950;
    line-height:1.05;
}

.header {
    display:flex;
    justify-content:space-between;
    align-items:center;
    padding:2px 3px 5px;
}

.header-title {
    font-size:16px;
    font-weight:950;
    color:#0f172a;
}

.header-sub {
    font-size:7px;
    color:#64748b;
    margin-top:1px;
}

.header-status {
    text-align:right;
    font-size:10px;
    font-weight:900;
}

.last-data {
    text-align:center;
    font-size:7px;
    color:#64748b;
    margin:6px 0 2px;
}

.reason {
    font-size:8px;
    color:#64748b;
    line-height:1.25;
    margin:3px 2px 5px;
}

@media(max-width:600px) {
    .main .block-container {
        padding:.25rem .28rem .75rem;
    }

    .grid2, .grid3 {
        gap:4px;
    }

    .card {
        padding:6px 7px;
    }

    .val {
        font-size:14px;
    }

    .main .val {
        font-size:18px;
    }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SAFE HELPERS
# ============================================================

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def d(value):
    return value if isinstance(value, dict) else {}


def lst(value):
    return value if isinstance(value, list) else []


def val(obj, *keys, default=None):
    """
    Return first non-empty/non-None value from dictionary.

    Supports fallback key names.
    """
    if not isinstance(obj, dict):
        return default

    for key in keys:
        if key in obj:
            value = obj[key]

            if value is not None and value != "":
                return value

    return default


def first_value(*values, default=None):
    """
    Generic fallback helper.

    Example:
        first_value(ind_value, raw_value, paper_value)
    """
    for value in values:
        if value is not None and value != "":
            return value

    return default


def number(value, decimals=2, fallback="—"):
    try:
        x = float(value)

        if not math.isfinite(x):
            return fallback

        return f"{x:,.{decimals}f}"

    except (TypeError, ValueError):
        return fallback


def money(value):
    try:
        x = float(value)

        if not math.isfinite(x):
            return "—"

        return f"₹{x:,.2f}"

    except (TypeError, ValueError):
        return "—"


def percent(value):
    try:
        x = float(value)

        if not math.isfinite(x):
            return "—"

        return f"{x:.1f}%"

    except (TypeError, ValueError):
        return "—"


def safe_float(value):
    try:
        return float(value)

    except (TypeError, ValueError):
        return 0.0


def fmt_text(value, fallback="—"):
    if value is None or value == "":
        return fallback

    return str(value)


def card_html(label, value, sub="", main=False):
    cls = "card main" if main else "card"

    return (
        f'<div class="{cls}">'
        f'<div class="lbl">{label}</div>'
        f'<div class="val">{value}</div>'
        f'<div class="sub">{sub}</div>'
        f'</div>'
    )


def grid(cards, cols=3):
    cls = "grid3" if cols == 3 else "grid2"

    st.markdown(
        f'<div class="{cls}">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def status_html(name, status, detail=""):
    text = str(status if status is not None else "—").upper()

    if text in ("PASS", "TRUE", "YES", "OK", "READY"):
        cls = "green"

    elif text in ("FAIL", "FALSE", "NO", "ERROR"):
        cls = "red"

    else:
        cls = "yellow"

    return (
        f'<div class="status">'
        f'<span class="left"><b>{name}</b>'
        f'<span class="detail">{detail}</span></span>'
        f'<b class="{cls}">{text}</b>'
        f'</div>'
    )


def section(title):
    st.markdown(
        f'<div class="section">{title}</div>',
        unsafe_allow_html=True,
    )


def load_all():
    return {
        name: read_json(path)
        for name, path in FILES.items()
    }


def get_active_trade(paper, journal):
    active = paper.get("active_trade")

    if isinstance(active, dict):
        return active

    for trade in lst(journal.get("trades")):

        if (
            isinstance(trade, dict)
            and str(trade.get("status", "")).upper() == "ACTIVE"
        ):
            return trade

    return None


# ============================================================
# CROSS-SOURCE FALLBACK HELPERS
# ============================================================

def get_spot(raw, ind, paper):
    return first_value(
        val(raw, "live_spot", "spot", "nifty_spot"),
        val(ind, "live_spot", "spot", "nifty_spot"),
        val(paper, "live_spot", "spot", "nifty_spot"),
        default=None,
    )


def get_day_high(raw, ind, paper):
    """
    Priority:
        indicator calculated value
        raw live value
        paper value
    """

    level_engine = d(ind.get("level_engine"))

    return first_value(
        val(ind, "intraday_high"),
        val(ind, "day_high"),
        val(ind, "live_day_high"),
        val(level_engine, "day_high"),
        val(raw, "live_day_high"),
        val(raw, "day_high"),
        val(paper, "live_day_high"),
        val(paper, "day_high"),
        default=None,
    )


def get_day_low(raw, ind, paper):
    level_engine = d(ind.get("level_engine"))

    return first_value(
        val(ind, "intraday_low"),
        val(ind, "day_low"),
        val(ind, "live_day_low"),
        val(level_engine, "day_low"),
        val(raw, "live_day_low"),
        val(raw, "day_low"),
        val(paper, "live_day_low"),
        val(paper, "day_low"),
        default=None,
    )


def get_rsi(raw, ind, paper):
    return first_value(
        val(ind, "live_rsi"),
        val(ind, "rsi"),
        val(ind, "rsi_live"),
        val(raw, "live_rsi"),
        val(raw, "rsi"),
        val(paper, "live_rsi"),
        val(paper, "rsi"),
        default=None,
    )


def get_ema9(raw, ind, paper):
    return first_value(
        val(ind, "live_ema9"),
        val(ind, "ema9"),
        val(ind, "ema_9"),
        val(ind, "ema9_live"),
        val(raw, "live_ema9"),
        val(raw, "ema9"),
        val(paper, "live_ema9"),
        val(paper, "ema9"),
        default=None,
    )


def get_ema20(raw, ind, paper):
    return first_value(
        val(ind, "live_ema20"),
        val(ind, "ema20"),
        val(ind, "ema_20"),
        val(ind, "ema20_live"),
        val(raw, "live_ema20"),
        val(raw, "ema20"),
        val(paper, "live_ema20"),
        val(paper, "ema20"),
        default=None,
    )


def get_volume_ratio(raw, ind, paper):
    return first_value(
        val(ind, "live_volume_ratio"),
        val(ind, "volume_ratio"),
        val(ind, "vol_ratio"),
        val(ind, "live_vol_ratio"),
        val(raw, "live_volume_ratio"),
        val(raw, "volume_ratio"),
        val(paper, "live_volume_ratio"),
        val(paper, "volume_ratio"),
        default=None,
    )


def get_support(ind, raw, paper):
    level_engine = d(ind.get("level_engine"))

    support = d(level_engine.get("nearest_support"))

    result = first_value(
        val(support, "level"),
        val(ind, "nearest_support"),
        val(ind, "support"),
        val(raw, "nearest_support"),
        val(raw, "support"),
        val(paper, "nearest_support"),
        val(paper, "support"),
        default=None,
    )

    return result


def get_resistance(ind, raw, paper):
    level_engine = d(ind.get("level_engine"))

    resistance = d(level_engine.get("nearest_resistance"))

    result = first_value(
        val(resistance, "level"),
        val(ind, "nearest_resistance"),
        val(ind, "resistance"),
        val(raw, "nearest_resistance"),
        val(raw, "resistance"),
        val(paper, "nearest_resistance"),
        val(paper, "resistance"),
        default=None,
    )

    return result


def get_futures_tick(raw, ind, paper):
    return first_value(
        raw.get("futures_tick"),
        ind.get("futures_tick"),
        paper.get("futures_tick"),
        default={},
    )


# ============================================================
# LAST GOOD SNAPSHOT
# ============================================================

def keep_last_good(current):

    if "last_good_dashboard" not in st.session_state:
        st.session_state["last_good_dashboard"] = {}

    cache = st.session_state["last_good_dashboard"]

    for name, value in current.items():

        if isinstance(value, dict) and value:
            cache[name] = value

    merged = {}

    for name in FILES:
        merged[name] = cache.get(
            name,
            current.get(name, {})
        )

    return merged


# ============================================================
# RENDER
# ============================================================

def render_dashboard():

    data = keep_last_good(load_all())

    raw = d(data["raw"])
    ind = d(data["ind"])
    ms = d(data["structure"])
    paper = d(data["paper"])
    journal = d(data["journal"])

    decision = d(paper.get("decision"))
    active = get_active_trade(paper, journal)

    # ========================================================
    # UNIVERSAL FALLBACK DATA
    # ========================================================

    spot = get_spot(raw, ind, paper)

    day_high = get_day_high(raw, ind, paper)
    day_low = get_day_low(raw, ind, paper)

    rsi = get_rsi(raw, ind, paper)
    ema9 = get_ema9(raw, ind, paper)
    ema20 = get_ema20(raw, ind, paper)

    volume_ratio = get_volume_ratio(
        raw,
        ind,
        paper,
    )

    support_value = get_support(
        ind,
        raw,
        paper,
    )

    resistance_value = get_resistance(
        ind,
        raw,
        paper,
    )

    futures = d(
        get_futures_tick(
            raw,
            ind,
            paper,
        )
    )

    # ========================================================
    # MARKET STATUS
    # ========================================================

    market = str(
        first_value(
            val(raw, "market_status"),
            val(ind, "market_status"),
            val(paper, "market_status"),
            default="UNKNOWN",
        )
    ).upper()

    if market == "CLOSED":

        status_text = "🟡 CLOSED"
        status_class = "yellow"

    else:

        connected_value = first_value(
            raw.get("websocket_connected"),
            ind.get("websocket_connected"),
            paper.get("websocket_connected"),
            default=False,
        )

        connected = bool(connected_value)

        status_text = (
            "🟢 LIVE"
            if connected
            else "🔴 OFF"
        )

        status_class = (
            "green"
            if connected
            else "red"
        )

    # ========================================================
    # LAST UPDATE
    # ========================================================

    last_update = first_value(
        val(raw, "last_update"),
        val(ind, "calculated_at_ist"),
        val(ind, "last_update"),
        val(paper, "last_update_ist"),
        val(paper, "last_update"),
        default=None,
    )

    # ========================================================
    # HEADER
    # ========================================================

    st.markdown(
        f"""
        <div class="header">
            <div>
                <div class="header-title">📈 NIFTY PAPER</div>
                <div class="header-sub">
                    Paper only · Read-only
                </div>
            </div>

            <div class="header-status {status_class}">
                {status_text}<br>
                <span class="header-sub">{market}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs(
        [
            "📊 MARKET",
            "🎯 TRADE",
            "📒 HISTORY",
        ]
    )

    # ========================================================
    # MARKET
    # ========================================================

    with tabs[0]:

        grid(
            [
                card_html(
                    "NIFTY LIVE",
                    number(spot, 2),
                    "last market value",
                    True,
                ),

                card_html(
                    "DAY HIGH / LOW",
                    f"{number(day_high,0)} / {number(day_low,0)}",
                    "session",
                    True,
                ),
            ],
            2,
        )

        grid(
            [
                card_html(
                    "RSI",
                    number(rsi),
                ),

                card_html(
                    "EMA 9",
                    number(ema9, 0),
                ),

                card_html(
                    "EMA 20",
                    number(ema20, 0),
                ),
            ],
            3,
        )

        grid(
            [
                card_html(
                    "VOLUME",
                    (
                        f"{number(volume_ratio)}x"
                        if volume_ratio is not None
                        else "—"
                    ),
                ),

                card_html(
                    "SUPPORT",
                    number(support_value, 0),
                ),

                card_html(
                    "RESISTANCE",
                    number(resistance_value, 0),
                ),
            ],
            3,
        )

        # ----------------------------------------------------
        # CE / PE FLOW
        # ----------------------------------------------------

        section("CE / PE FLOW")

        order_flow = d(
            ms.get("order_flow")
        )

        options_flow = d(
            order_flow.get("options")
        )

        ce = d(
            options_flow.get("ce")
        )

        pe = d(
            options_flow.get("pe")
        )

        grid(
            [
                status_html(
                    "CE FLOW",
                    ce.get("state"),
                    "option flow",
                ),

                status_html(
                    "PE FLOW",
                    pe.get("state"),
                    "option flow",
                ),
            ],
            2,
        )

        # ----------------------------------------------------
        # OI SUPPORT / RESISTANCE
        # ----------------------------------------------------

        section(
            "OI SUPPORT / RESISTANCE"
        )

        oi_sr = d(
            ms.get(
                "oi_support_resistance"
            )
        )

        oi_support = first_value(
            val(oi_sr, "support"),
            val(ms, "oi_support"),
            val(ind, "oi_support"),
            val(raw, "oi_support"),
            default=None,
        )

        oi_resistance = first_value(
            val(oi_sr, "resistance"),
            val(ms, "oi_resistance"),
            val(ind, "oi_resistance"),
            val(raw, "oi_resistance"),
            default=None,
        )

        grid(
            [
                card_html(
                    "OI SUPPORT",
                    number(oi_support, 0),
                ),

                card_html(
                    "OI RESISTANCE",
                    number(oi_resistance, 0),
                ),
            ],
            2,
        )

        # ----------------------------------------------------
        # FUTURES BUY / SELL
        # ----------------------------------------------------

        section(
            "FUTURES BUY / SELL"
        )

        buy_quantity = first_value(
            val(
                futures,
                "total_buy_quantity",
            ),
            val(
                futures,
                "buy_quantity",
            ),
            val(
                raw,
                "futures_buy_quantity",
            ),
            val(
                ms,
                "futures_buy_quantity",
            ),
            default=None,
        )

        sell_quantity = first_value(
            val(
                futures,
                "total_sell_quantity",
            ),
            val(
                futures,
                "sell_quantity",
            ),
            val(
                raw,
                "futures_sell_quantity",
            ),
            val(
                ms,
                "futures_sell_quantity",
            ),
            default=None,
        )

        grid(
            [
                card_html(
                    "BUY QTY",
                    number(
                        buy_quantity,
                        0,
                    ),
                ),

                card_html(
                    "SELL QTY",
                    number(
                        sell_quantity,
                        0,
                    ),
                ),
            ],
            2,
        )

        if market == "CLOSED":

            st.markdown(
                f"""
                <div class="last-data">
                    Market closed · Last available data:
                    {fmt_text(last_update)}
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ========================================================
    # TRADE
    # ========================================================

    with tabs[1]:

        setup = str(
            val(
                decision,
                "setup",
                default="NONE",
            )
        )

        trade_type = str(
            val(
                decision,
                "trade_type",
                default="—",
            )
        )

        ready = bool(
            decision.get("ready")
        )

        decision_class = (
            "green"
            if ready
            else "yellow"
        )

        icon = (
            "🟢"
            if ready
            else "🟡"
        )

        strike = number(
            decision.get(
                "option_strike"
            ),
            0,
        )

        st.markdown(
            f"""
            <div class="trade">
                <div class="lbl">
                    CURRENT DECISION
                </div>

                <div class="big {decision_class}">
                    {icon} {setup}
                </div>

                <div style="
                    font-size:10px;
                    font-weight:900;
                    color:#334155;
                    margin-top:2px
                ">
                    {trade_type} · Strike {strike}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        reason = first_value(
            val(
                decision,
                "reason",
            ),
            val(
                ind,
                "algo_reason",
            ),
            val(
                ind,
                "reason",
            ),
            default="Waiting for setup…",
        )

        st.markdown(
            f'<div class="reason">{fmt_text(reason)}</div>',
            unsafe_allow_html=True,
        )

        section("STRATEGY GATES")

        # ----------------------------------------------------
        # SIGNAL RSI
        # ----------------------------------------------------

        signal_rsi = first_value(
            val(decision, "rsi"),
            val(ind, "signal_rsi"),
            val(ind, "rsi"),
            default=None,
        )

        # ----------------------------------------------------
        # SIGNAL EMA
        # ----------------------------------------------------

        signal_ema9 = first_value(
            val(decision, "ema9"),
            val(ind, "signal_ema9"),
            val(ind, "ema9"),
            default=None,
        )

        signal_ema20 = first_value(
            val(decision, "ema20"),
            val(ind, "signal_ema20"),
            val(ind, "ema20"),
            default=None,
        )

        # ----------------------------------------------------
        # SIGNAL VOLUME
        # ----------------------------------------------------

        signal_volume = first_value(
            val(
                decision,
                "volume_ratio",
                "signal_volume_ratio",
            ),
            val(
                ind,
                "signal_volume_ratio",
            ),
            val(
                ind,
                "volume_ratio",
            ),
            default=None,
        )

        gate_items = [

            (
                "RSI",

                first_value(
                    val(
                        decision,
                        "rsi_pass",
                    ),
                    val(
                        ind,
                        "signal_rsi_status",
                    ),
                    default=None,
                ),

                f"RSI {number(signal_rsi)}",
            ),

            (
                "EMA",

                first_value(
                    val(
                        decision,
                        "ema_pass",
                    ),
                    val(
                        ind,
                        "signal_ema_status",
                    ),
                    default=None,
                ),

                f"9 {number(signal_ema9,0)} · "
                f"20 {number(signal_ema20,0)}",
            ),

            (
                "VOLUME",

                first_value(
                    val(
                        decision,
                        "volume_pass",
                    ),
                    val(
                        ind,
                        "signal_vol_status",
                    ),
                    default=None,
                ),

                f"{number(signal_volume)}x · min 1.20x",
            ),

            (
                "RUNWAY",

                first_value(
                    val(
                        decision,
                        "runway_pass",
                    ),
                    val(
                        ind,
                        "runway_status",
                    ),
                    default=None,
                ),

                f'{fmt_text(val(decision, "runway", default="—"))}'
                " · min 15",
            ),

            (
                "CANDLE",

                val(
                    decision,
                    "candle_size_pass",
                ),

                f'{number(decision.get("candle_range"))}'
                " pts · 12–25",
            ),

            (
                "WICK",

                val(
                    decision,
                    "wick_pass",
                ),

                f'{number(decision.get("opposite_wick"))}'
                " pts · max 5% body",
            ),

            (
                "OI / FLOW",

                val(
                    decision,
                    "structure_pass",
                ),

                f'{fmt_text(val(decision, "oi_state", default="—"))}'
                " / "
                f'{fmt_text(val(decision, "flow_state", default="—"))}',
            ),
        ]

        # 3 gates per row
        for i in range(
            0,
            len(gate_items),
            3,
        ):

            batch = gate_items[
                i:i + 3
            ]

            st.markdown(
                '<div class="grid3">'
                +
                "".join(
                    status_html(*item)
                    for item in batch
                )
                +
                '</div>',
                unsafe_allow_html=True,
            )

        # ----------------------------------------------------
        # TRADE & ACCOUNT
        # ----------------------------------------------------

        section(
            "TRADE & ACCOUNT"
        )

        if isinstance(
            active,
            dict,
        ):

            grid(
                [
                    card_html(
                        "ACTIVE",
                        active.get(
                            "option_symbol",
                            "—",
                        ),
                    ),

                    card_html(
                        "QTY",
                        number(
                            active.get(
                                "qty"
                            ),
                            0,
                        ),
                    ),

                    card_html(
                        "ENTRY LTP",
                        money(
                            active.get(
                                "option_entry_ltp",
                                active.get(
                                    "entry"
                                ),
                            )
                        ),
                    ),
                ],
                3,
            )

            grid(
                [
                    card_html(
                        "CURRENT LTP",
                        money(
                            active.get(
                                "current_option_ltp"
                            )
                        ),
                    ),

                    card_html(
                        "RUNNING P&L",
                        money(
                            active.get(
                                "running_pnl"
                            )
                        ),
                        "unrealized",
                    ),

                    card_html(
                        "WALLET",
                        money(
                            first_value(
                                val(
                                    paper,
                                    "wallet_balance",
                                ),
                                val(
                                    journal,
                                    "wallet_balance",
                                ),
                                default=None,
                            )
                        ),
                        "realized only",
                    ),
                ],
                3,
            )

            grid(
                [
                    card_html(
                        "REALIZED P&L",
                        money(
                            first_value(
                                val(
                                    paper,
                                    "realized_pnl",
                                ),
                                val(
                                    journal,
                                    "realized_pnl",
                                ),
                                default=None,
                            )
                        ),
                        "closed trades",
                    ),
                ],
                2,
            )

        else:

            grid(
                [
                    card_html(
                        "ACTIVE TRADE",
                        "NONE",
                        "waiting",
                    ),

                    card_html(
                        "WALLET",
                        money(
                            first_value(
                                val(
                                    paper,
                                    "wallet_balance",
                                ),
                                val(
                                    journal,
                                    "wallet_balance",
                                ),
                                default=None,
                            )
                        ),
                        "realized only",
                    ),
                ],
                2,
            )

            grid(
                [
                    card_html(
                        "REALIZED P&L",
                        money(
                            first_value(
                                val(
                                    paper,
                                    "realized_pnl",
                                ),
                                val(
                                    journal,
                                    "realized_pnl",
                                ),
                                default=None,
                            )
                        ),
                        "closed trades",
                    ),
                ],
                2,
            )

    # ========================================================
    # HISTORY
    # ========================================================

    with tabs[2]:

        trades = [
            t
            for t in lst(
                journal.get("trades")
            )
            if isinstance(
                t,
                dict,
            )
        ]

        total_trades = first_value(
            val(
                paper,
                "total_trades",
            ),
            len(trades),
            default=0,
        )

        win_rate_value = first_value(
            val(
                paper,
                "win_rate",
            ),
            val(
                journal,
                "win_rate",
            ),
            default=None,
        )

        closed_trades = first_value(
            val(
                paper,
                "closed_trades",
            ),
            val(
                journal,
                "closed_trades",
            ),
            default=0,
        )

        grid(
            [
                card_html(
                    "TRADES",
                    str(total_trades),
                ),

                card_html(
                    "WIN RATE",
                    percent(
                        win_rate_value
                    ),
                ),

                card_html(
                    "CLOSED",
                    str(
                        closed_trades
                    ),
                ),
            ],
            3,
        )

        section(
            "RECENT TRADES"
        )

        if trades:

            for trade in reversed(
                trades[-6:]
            ):

                status = str(
                    trade.get(
                        "status",
                        "—",
                    )
                ).upper()

                pnl_value = first_value(
                    val(
                        trade,
                        "pnl_realized",
                    ),
                    val(
                        trade,
                        "running_pnl",
                    ),
                    default=None,
                )

                numeric_pnl = safe_float(
                    pnl_value
                )

                result_class = (
                    "green"
                    if numeric_pnl > 0
                    else (
                        "red"
                        if numeric_pnl < 0
                        else "yellow"
                    )
                )

                symbol = trade.get(
                    "option_symbol",
                    "—",
                )

                trade_type = trade.get(
                    "trade_type",
                    trade.get(
                        "type",
                        "—",
                    ),
                )

                entry_time = trade.get(
                    "entry_time",
                    trade.get(
                        "candle_time",
                        "—",
                    ),
                )

                st.markdown(
                    f"""
                    <div class="status">
                        <span class="left">
                            <b>
                                {trade_type} · {symbol}
                            </b>

                            <span class="detail">
                                {entry_time} · {status}
                            </span>
                        </span>

                        <b class="{result_class}">
                            {money(pnl_value)}
                        </b>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        else:

            st.markdown(
                """
                <div class="status">
                    <span class="left">
                        <b>No paper trades yet</b>
                    </span>
                    <b class="muted">—</b>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ========================================================
    # FOOTER
    # ========================================================

    st.markdown(
        f"""
        <div class="last-data">
            Dashboard update
            {datetime.now(IST).strftime("%H:%M:%S IST")}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# LIVE UPDATE
# ============================================================

if hasattr(st, "fragment"):

    @st.fragment(run_every=2)
    def live_dashboard():
        render_dashboard()

    live_dashboard()

else:

    render_dashboard()
