# Trading app.py
# ============================================================
# NIFTY PAPER - SOURCE-OF-TRUTH MOBILE DASHBOARD
# ============================================================
#
# READ ONLY.
#
# IMPORTANT ARCHITECTURE:
#
#   Angel One
#      |
#      v
#   data_worker.py
#      |
#      v
#   data_raw.json  --------------------+
#                                      |
#                    +-----------------+------------------+
#                    |                 |                  |
#                    v                 v                  v
#             indicator_calc   market_structure       DASHBOARD
#                    |                 |
#                    v                 v
#          processed_indicators  processed_market_structure
#                    |                 |
#                    +--------+--------+
#                             v
#                       paper_engine
#                             |
#                             v
#                  paper_engine_output.json
#
# SOURCE OWNERSHIP:
#
# RAW / BROKER DATA:
#   data_raw.json
#     - live_spot
#     - intraday_high / intraday_low
#     - futures_quote
#     - option_quote
#     - websocket_connected
#     - timestamps
#
# INDICATORS:
#   processed_indicators.json
#     - RSI
#     - EMA9 / EMA20
#     - volume ratio
#     - support / resistance
#     - runway
#     - candle / wick measurements
#
# MARKET STRUCTURE:
#   processed_market_structure.json
#     - CE / PE flow
#     - OI support / resistance
#     - futures/order-flow structure
#
# PAPER ENGINE:
#   paper_engine_output.json
#     - decision
#     - gates
#     - active trade
#     - running P&L
#     - realized P&L
#     - wallet
#
# HISTORY:
#   trade_history.json
#
# RULE:
#   Dashboard NEVER calculates indicators or trading decisions.
#   Dashboard NEVER uses one engine's value as a fallback for
#   another engine's value.
#
# ============================================================

import html
import json
import math
from datetime import datetime, timezone, timedelta

import streamlit as st


# ============================================================
# PAGE
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
# CSS
# ============================================================

st.markdown(
    """
<style>
#MainMenu, footer, header {
    visibility: hidden;
}

[data-testid="stAppViewContainer"] {
    background: #f4f7f9;
}

.main .block-container {
    max-width: 560px;
    padding: .35rem .35rem 1rem;
}

[data-testid="stTabs"] button {
    font-size: 12px;
    font-weight: 800;
    padding: 7px 3px;
}

[data-testid="stTabs"] [role="tablist"] {
    gap: 1px;
}

.section {
    font-size: 11px;
    font-weight: 900;
    color: #334155;
    margin: 8px 2px 4px;
}

.grid2, .grid3 {
    display: grid;
    gap: 5px;
    width: 100%;
    margin: 3px 0;
}

.grid2 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.grid3 {
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

.card {
    background: #ffffff;
    border: 1px solid #d9e1e8;
    border-radius: 9px;
    padding: 7px 8px;
    min-width: 0;
    box-shadow: 0 1px 2px rgba(15,23,42,.04);
}

.card.main {
    padding: 9px 10px;
}

.lbl {
    font-size: 8px;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: .4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.val {
    font-size: 15px;
    font-weight: 900;
    color: #0f172a;
    line-height: 1.1;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.main .val {
    font-size: 19px;
}

.sub {
    font-size: 7px;
    color: #94a3b8;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.trade {
    background: #ffffff;
    border: 1px solid #cbd8e5;
    border-radius: 10px;
    padding: 9px 10px;
    margin: 4px 0;
    box-shadow: 0 1px 2px rgba(15,23,42,.04);
}

.status {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 5px;
    background: #ffffff;
    border: 1px solid #d9e1e8;
    border-radius: 8px;
    padding: 6px 8px;
    min-width: 0;
}

.status .left {
    min-width: 0;
}

.status b {
    color: #1e293b;
    font-size: 10px;
}

.status .detail {
    font-size: 7px;
    color: #94a3b8;
    display: block;
    margin-top: 1px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.green {
    color: #159447 !important;
}

.red {
    color: #dc3545 !important;
}

.yellow {
    color: #b77900 !important;
}

.muted {
    color: #64748b !important;
}

.big {
    font-size: 21px;
    font-weight: 950;
    line-height: 1.05;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 3px 5px;
}

.header-title {
    font-size: 16px;
    font-weight: 950;
    color: #0f172a;
}

.header-sub {
    font-size: 7px;
    color: #64748b;
    margin-top: 1px;
}

.header-status {
    text-align: right;
    font-size: 10px;
    font-weight: 900;
}

.last-data {
    text-align: center;
    font-size: 7px;
    color: #64748b;
    margin: 6px 0 2px;
}

.reason {
    font-size: 8px;
    color: #64748b;
    line-height: 1.25;
    margin: 3px 2px 5px;
}

.source {
    font-size: 7px;
    color: #94a3b8;
    margin-top: 2px;
}

@media(max-width:600px) {
    .main .block-container {
        padding: .25rem .28rem .75rem;
    }

    .grid2, .grid3 {
        gap: 4px;
    }

    .card {
        padding: 6px 7px;
    }

    .val {
        font-size: 14px;
    }

    .main .val {
        font-size: 18px;
    }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# JSON / TYPE HELPERS
# ============================================================

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def d(value):
    return value if isinstance(value, dict) else {}


def lst(value):
    return value if isinstance(value, list) else []


def finite_float(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def number(value, decimals=2, fallback="—"):
    x = finite_float(value)
    if x is None:
        return fallback
    return f"{x:,.{decimals}f}"


def money(value):
    x = finite_float(value)
    if x is None:
        return "—"
    return f"₹{x:,.2f}"


def percent(value):
    x = finite_float(value)
    if x is None:
        return "—"
    return f"{x:.1f}%"


def text(value, fallback="—"):
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def bool_text(value):
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    if value is None:
        return "—"
    return str(value).upper()


# ============================================================
# HTML RENDER HELPERS
# ============================================================

def render_html(markup):
    """
    Use Streamlit's native HTML renderer when available.
    This avoids the deployed-app problem where <div> markup
    can appear as literal text.
    """
    native_html = getattr(st, "html", None)

    if callable(native_html):
        native_html(markup)
    else:
        st.markdown(markup, unsafe_allow_html=True)


def card_html(label, value, sub="", main=False):
    cls = "card main" if main else "card"
    return (
        f'<div class="{cls}">'
        f'<div class="lbl">{html.escape(str(label))}</div>'
        f'<div class="val">{value}</div>'
        f'<div class="sub">{html.escape(str(sub))}</div>'
        f'</div>'
    )


def grid(cards, cols=3):
    cls = "grid3" if cols == 3 else "grid2"
    render_html(
        f'<div class="{cls}">{"".join(cards)}</div>'
    )


def section(title):
    render_html(
        f'<div class="section">{html.escape(str(title))}</div>'
    )


def status_html(name, status, detail=""):
    raw = str(status if status is not None else "—").upper()

    if raw in ("PASS", "TRUE", "YES", "OK", "READY"):
        cls = "green"
    elif raw in ("FAIL", "FALSE", "NO", "ERROR"):
        cls = "red"
    else:
        cls = "yellow"

    return (
        '<div class="status">'
        '<span class="left">'
        f'<b>{html.escape(str(name))}</b>'
        f'<span class="detail">{html.escape(str(detail))}</span>'
        '</span>'
        f'<b class="{cls}">{html.escape(raw)}</b>'
        '</div>'
    )


# ============================================================
# DIRECT SOURCE ACCESS
# ============================================================

def source_value(source, *keys, default=None):
    """
    IMPORTANT:
    This helper searches ONLY inside the supplied source.
    It never falls back to another engine/file.
    """
    if not isinstance(source, dict):
        return default

    for key in keys:
        value = source.get(key)
        if value is not None and value != "":
            return value

    return default


def load_all():
    return {
        name: read_json(path)
        for name, path in FILES.items()
    }


# ============================================================
# SOURCE-SPECIFIC READERS
# ============================================================

# ---------------- RAW OWNER ----------------

def raw_spot(raw):
    return source_value(raw, "live_spot")


def raw_day_high(raw):
    return source_value(raw, "intraday_high")


def raw_day_low(raw):
    return source_value(raw, "intraday_low")


def raw_futures_quote(raw):
    return d(raw.get("future_quote"))


def raw_option_quote(raw):
    return d(raw.get("option_quote"))


def raw_websocket(raw):
    return raw.get("websocket_connected")


def raw_last_update(raw):
    return source_value(raw, "last_update")


def raw_timestamp(raw):
    return source_value(raw, "worker_timestamp", "spot_timestamp")


# ---------------- INDICATOR OWNER ----------------

def ind_rsi(ind):
    return source_value(ind, "rsi", "live_rsi")


def ind_ema9(ind):
    return source_value(ind, "ema9", "live_ema9")


def ind_ema20(ind):
    return source_value(ind, "ema20", "live_ema20")


def ind_volume_ratio(ind):
    return source_value(
        ind,
        "volume_ratio",
        "live_volume_ratio",
        "signal_volume_ratio",
    )


def ind_support(ind):
    level_engine = d(ind.get("level_engine"))
    support = d(level_engine.get("nearest_support"))

    return source_value(
        support,
        "level",
        default=source_value(
            ind,
            "nearest_support",
            "support",
        ),
    )


def ind_resistance(ind):
    level_engine = d(ind.get("level_engine"))
    resistance = d(level_engine.get("nearest_resistance"))

    return source_value(
        resistance,
        "level",
        default=source_value(
            ind,
            "nearest_resistance",
            "resistance",
        ),
    )


def ind_runway(ind):
    return source_value(ind, "runway", "signal_runway")


def ind_candle_range(ind):
    return source_value(
        ind,
        "candle_range",
        "signal_candle_range",
    )


def ind_opposite_wick(ind):
    return source_value(
        ind,
        "opposite_wick",
        "signal_opposite_wick",
    )


# ---------------- STRUCTURE OWNER ----------------

def structure_options(structure):
    return d(d(structure.get("order_flow")).get("options"))


def structure_ce_flow(structure):
    return d(structure_options(structure).get("ce"))


def structure_pe_flow(structure):
    return d(structure_options(structure).get("pe"))


def structure_oi_sr(structure):
    return d(structure.get("oi_support_resistance"))


def structure_oi_support(structure):
    sr = structure_oi_sr(structure)
    return source_value(sr, "support")


def structure_oi_resistance(structure):
    sr = structure_oi_sr(structure)
    return source_value(sr, "resistance")


# ---------------- PAPER ENGINE OWNER ----------------

def paper_decision(paper):
    return d(paper.get("decision"))


def paper_active_trade(paper, journal):
    active = paper.get("active_trade")

    if isinstance(active, dict):
        return active

    # History is only used to display an active journal record.
    # It is NOT used as a market-data fallback.
    for trade in lst(journal.get("trades")):
        if (
            isinstance(trade, dict)
            and str(trade.get("status", "")).upper() == "ACTIVE"
        ):
            return trade

    return None


# ============================================================
# MARKET STATUS
# ============================================================

def render_header(raw, paper):
    connected = raw_websocket(raw)

    if connected is True:
        status_text = "🟢 LIVE"
        status_class = "green"
    elif connected is False:
        status_text = "🔴 OFF"
        status_class = "red"
    else:
        status_text = "🟡 UNKNOWN"
        status_class = "yellow"

    market_status = source_value(
        raw,
        "market_status",
        default=source_value(
            paper,
            "market_status",
            default="UNKNOWN",
        ),
    )

    render_html(
        f"""
        <div class="header">
            <div>
                <div class="header-title">📈 NIFTY PAPER</div>
                <div class="header-sub">Paper only · Read-only</div>
            </div>
            <div class="header-status {status_class}">
                {html.escape(status_text)}<br>
                <span class="header-sub">
                    {html.escape(str(market_status).upper())}
                </span>
            </div>
        </div>
        """
    )


# ============================================================
# MARKET TAB
# ============================================================

def render_market(raw, ind, structure):

    # RAW ONLY
    spot = raw_spot(raw)
    day_high = raw_day_high(raw)
    day_low = raw_day_low(raw)

    # INDICATOR ONLY
    rsi = ind_rsi(ind)
    ema9 = ind_ema9(ind)
    ema20 = ind_ema20(ind)
    volume_ratio = ind_volume_ratio(ind)
    support = ind_support(ind)
    resistance = ind_resistance(ind)

    grid(
        [
            card_html(
                "NIFTY LIVE",
                number(spot, 2),
                "data_raw.json · worker",
                True,
            ),
            card_html(
                "DAY HIGH / LOW",
                f"{number(day_high, 0)} / {number(day_low, 0)}",
                "data_raw.json · worker",
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
                "processed_indicators",
            ),
            card_html(
                "EMA 9",
                number(ema9, 0),
                "processed_indicators",
            ),
            card_html(
                "EMA 20",
                number(ema20, 0),
                "processed_indicators",
            ),
        ],
        3,
    )

    grid(
        [
            card_html(
                "VOLUME",
                f"{number(volume_ratio)}x"
                if volume_ratio is not None else "—",
                "processed_indicators",
            ),
            card_html(
                "SUPPORT",
                number(support, 0),
                "processed_indicators",
            ),
            card_html(
                "RESISTANCE",
                number(resistance, 0),
                "processed_indicators",
            ),
        ],
        3,
    )

    section("CE / PE FLOW")

    ce = structure_ce_flow(structure)
    pe = structure_pe_flow(structure)

    grid(
        [
            status_html(
                "CE FLOW",
                source_value(ce, "state"),
                "market structure",
            ),
            status_html(
                "PE FLOW",
                source_value(pe, "state"),
                "market structure",
            ),
        ],
        2,
    )

    section("OI SUPPORT / RESISTANCE")

    grid(
        [
            card_html(
                "OI SUPPORT",
                number(structure_oi_support(structure), 0),
                "market structure",
            ),
            card_html(
                "OI RESISTANCE",
                number(structure_oi_resistance(structure), 0),
                "market structure",
            ),
        ],
        2,
    )

    section("FUTURES BUY / SELL")

    futures = raw_futures_quote(raw)

    buy_qty = source_value(
        futures,
        "total_buy_quantity",
        "buy_quantity",
    )

    sell_qty = source_value(
        futures,
        "total_sell_quantity",
        "sell_quantity",
    )

    grid(
        [
            card_html(
                "BUY QTY",
                number(buy_qty, 0),
                "data_raw.json · futures quote",
            ),
            card_html(
                "SELL QTY",
                number(sell_qty, 0),
                "data_raw.json · futures quote",
            ),
        ],
        2,
    )


# ============================================================
# TRADE TAB
# ============================================================

def render_trade(ind, paper):

    decision = paper_decision(paper)

    setup = source_value(
        decision,
        "setup",
        default="NONE",
    )

    trade_type = source_value(
        decision,
        "trade_type",
        default="—",
    )

    ready = decision.get("ready")

    if ready is True:
        decision_class = "green"
        icon = "🟢"
    elif ready is False:
        decision_class = "yellow"
        icon = "🟡"
    else:
        decision_class = "yellow"
        icon = "🟡"

    strike = source_value(
        decision,
        "option_strike",
    )

    # Escape all user/data text before putting it in HTML.
    setup_html = html.escape(str(setup))
    trade_type_html = html.escape(str(trade_type))

    strike_html = number(strike, 0)

    render_html(
        f"""
        <div class="trade">
            <div class="lbl">CURRENT DECISION</div>
            <div class="big {decision_class}">
                {icon} {setup_html}
            </div>
            <div style="
                font-size:10px;
                font-weight:900;
                color:#334155;
                margin-top:2px
            ">
                {trade_type_html} · Strike {strike_html}
            </div>
        </div>
        """
    )

    reason = source_value(
        decision,
        "reason",
        default="Waiting for setup…",
    )

    render_html(
        f'<div class="reason">{html.escape(str(reason))}</div>'
    )

    section("STRATEGY GATES")

    # ========================================================
    # IMPORTANT:
    # Gate result is owned by paper_engine.
    # Gate measurement shown beside it is taken from the
    # paper-engine decision snapshot.
    #
    # Dashboard does NOT independently recalculate gates.
    # ========================================================

    gate_items = [
        (
            "RSI",
            decision.get("rsi_pass"),
            f"RSI {number(source_value(decision, 'rsi'))}",
        ),
        (
            "EMA",
            decision.get("ema_pass"),
            f"9 {number(source_value(decision, 'ema9'), 0)} · "
            f"20 {number(source_value(decision, 'ema20'), 0)}",
        ),
        (
            "VOLUME",
            decision.get("volume_pass"),
            f"{number(source_value(decision, 'volume_ratio'))}x · min 1.20x",
        ),
        (
            "RUNWAY",
            decision.get("runway_pass"),
            f"{text(source_value(decision, 'runway'))} · min 15",
        ),
        (
            "CANDLE",
            decision.get("candle_size_pass"),
            f"{number(source_value(decision, 'candle_range'))} pts · 12–25",
        ),
        (
            "WICK",
            decision.get("wick_pass"),
            f"{number(source_value(decision, 'opposite_wick'))} pts · max 5% body",
        ),
        (
            "OI / FLOW",
            decision.get("structure_pass"),
            f"{text(source_value(decision, 'oi_state'))} / "
            f"{text(source_value(decision, 'flow_state'))}",
        ),
    ]

    for i in range(0, len(gate_items), 3):
        batch = gate_items[i:i + 3]
        render_html(
            '<div class="grid3">'
            + "".join(status_html(*item) for item in batch)
            + '</div>'
        )

    # ========================================================
    # TRADE & ACCOUNT
    # ========================================================

    section("TRADE & ACCOUNT")

    # Active trade belongs to paper engine.
    active = d(paper.get("active_trade"))

    if active:

        grid(
            [
                card_html(
                    "ACTIVE",
                    html.escape(
                        str(
                            active.get(
                                "option_symbol",
                                "—",
                            )
                        )
                    ),
                    "paper engine",
                ),
                card_html(
                    "QTY",
                    number(active.get("qty"), 0),
                    "paper engine",
                ),
                card_html(
                    "ENTRY LTP",
                    money(
                        active.get(
                            "option_entry_ltp",
                            active.get("entry"),
                        )
                    ),
                    "paper engine",
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
                    "paper engine",
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
                        source_value(
                            paper,
                            "wallet_balance",
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
                        source_value(
                            paper,
                            "realized_pnl",
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
                    "paper engine",
                ),
                card_html(
                    "WALLET",
                    money(
                        source_value(
                            paper,
                            "wallet_balance",
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
                        source_value(
                            paper,
                            "realized_pnl",
                        )
                    ),
                    "closed trades",
                ),
            ],
            2,
        )


# ============================================================
# HISTORY TAB
# ============================================================

def render_history(paper, journal):

    trades = [
        t for t in lst(journal.get("trades"))
        if isinstance(t, dict)
    ]

    total_trades = source_value(
        paper,
        "total_trades",
        default=len(trades),
    )

    win_rate = source_value(
        paper,
        "win_rate",
    )

    closed_trades = source_value(
        paper,
        "closed_trades",
        default=0,
    )

    grid(
        [
            card_html(
                "TRADES",
                str(total_trades),
                "paper engine / journal",
            ),
            card_html(
                "WIN RATE",
                percent(win_rate),
                "paper engine",
            ),
            card_html(
                "CLOSED",
                str(closed_trades),
                "paper engine",
            ),
        ],
        3,
    )

    section("RECENT TRADES")

    if not trades:
        render_html(
            """
            <div class="status">
                <span class="left">
                    <b>No paper trades yet</b>
                </span>
                <b class="muted">—</b>
            </div>
            """
        )
        return

    for trade in reversed(trades[-6:]):

        status = str(
            trade.get("status", "—")
        ).upper()

        pnl = source_value(
            trade,
            "pnl_realized",
            "running_pnl",
        )

        pnl_number = finite_float(pnl)

        if pnl_number is not None and pnl_number > 0:
            result_class = "green"
        elif pnl_number is not None and pnl_number < 0:
            result_class = "red"
        else:
            result_class = "yellow"

        symbol = html.escape(
            str(
                trade.get(
                    "option_symbol",
                    "—",
                )
            )
        )

        trade_type = html.escape(
            str(
                trade.get(
                    "trade_type",
                    trade.get("type", "—"),
                )
            )
        )

        entry_time = html.escape(
            str(
                trade.get(
                    "entry_time",
                    trade.get("candle_time", "—"),
                )
            )
        )

        render_html(
            f"""
            <div class="status">
                <span class="left">
                    <b>{trade_type} · {symbol}</b>
                    <span class="detail">
                        {entry_time} · {html.escape(status)}
                    </span>
                </span>
                <b class="{result_class}">
                    {money(pnl)}
                </b>
            </div>
            """
        )


# ============================================================
# MAIN
# ============================================================

def render_dashboard():

    data = load_all()

    raw = d(data["raw"])
    ind = d(data["ind"])
    structure = d(data["structure"])
    paper = d(data["paper"])
    journal = d(data["journal"])

    render_header(raw, paper)

    tabs = st.tabs(
        [
            "📊 MARKET",
            "🎯 TRADE",
            "📒 HISTORY",
        ]
    )

    with tabs[0]:
        render_market(
            raw,
            ind,
            structure,
        )

    with tabs[1]:
        render_trade(
            ind,
            paper,
        )

    with tabs[2]:
        render_history(
            paper,
            journal,
        )

    last_update = raw_last_update(raw)

    if last_update is None:
        last_update = datetime.now(IST).strftime("%H:%M:%S")

    render_html(
        f"""
        <div class="last-data">
            Worker update · {html.escape(str(last_update))}
            · Dashboard {datetime.now(IST).strftime("%H:%M:%S IST")}
        </div>
        """
    )


# ============================================================
# LIVE REFRESH
# ============================================================

if hasattr(st, "fragment"):

    @st.fragment(run_every=2)
    def live_dashboard():
        render_dashboard()

    live_dashboard()

else:
    render_dashboard()
