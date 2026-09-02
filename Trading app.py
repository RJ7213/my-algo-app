import json
import math
from datetime import datetime, timezone, timedelta

import streamlit as st

# ============================================================
# NIFTY PAPER - FINAL MOBILE DASHBOARD
# READ-ONLY: no strategy calculations, no orders.
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

# ------------------------------------------------------------
# MOBILE UI
# ------------------------------------------------------------
st.markdown(
    """
<style>
#MainMenu, footer, header {visibility:hidden;}

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

.grid2 { grid-template-columns:repeat(2,minmax(0,1fr)); }
.grid3 { grid-template-columns:repeat(3,minmax(0,1fr)); }

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

.main .val { font-size:19px; }

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

.green { color:#159447 !important; }
.red { color:#dc3545 !important; }
.yellow { color:#b77900 !important; }
.muted { color:#64748b !important; }

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


# ------------------------------------------------------------
# SAFE HELPERS
# ------------------------------------------------------------
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
    if not isinstance(obj, dict):
        return default
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
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
    st.markdown(f'<div class="{cls}">{"".join(cards)}</div>', unsafe_allow_html=True)


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
    st.markdown(f'<div class="section">{title}</div>', unsafe_allow_html=True)


def load_all():
    return {name: read_json(path) for name, path in FILES.items()}


def get_active_trade(paper, journal):
    active = paper.get("active_trade")
    if isinstance(active, dict):
        return active

    for trade in lst(journal.get("trades")):
        if isinstance(trade, dict) and str(trade.get("status", "")).upper() == "ACTIVE":
            return trade
    return None


# ------------------------------------------------------------
# LAST GOOD SNAPSHOT
# Keeps the last valid display in the current dashboard
# session when market closes or a file is briefly unavailable.
# The dashboard never writes to the engine files.
# ------------------------------------------------------------
def keep_last_good(current):
    if "last_good_dashboard" not in st.session_state:
        st.session_state["last_good_dashboard"] = {}

    cache = st.session_state["last_good_dashboard"]

    for name, value in current.items():
        if isinstance(value, dict) and value:
            # A dict with at least one useful key is considered valid.
            cache[name] = value

    merged = {}
    for name in FILES:
        merged[name] = cache.get(name, current.get(name, {}))

    return merged


# ------------------------------------------------------------
# RENDER
# ------------------------------------------------------------
def render_dashboard():
    data = keep_last_good(load_all())

    raw = d(data["raw"])
    ind = d(data["ind"])
    ms = d(data["structure"])
    paper = d(data["paper"])
    journal = d(data["journal"])

    decision = d(paper.get("decision"))
    active = get_active_trade(paper, journal)

    spot = val(raw, "live_spot", default=val(paper, "live_spot"))

    market = str(
        val(
            raw,
            "market_status",
            default=val(paper, "market_status", default="UNKNOWN"),
        )
    ).upper()

    # IMPORTANT:
    # CLOSED means show LAST DATA, not blank/off.
    if market == "CLOSED":
        status_text = "🟡 CLOSED"
        status_class = "yellow"
    else:
        connected = bool(raw.get("websocket_connected"))
        status_text = "🟢 LIVE" if connected else "🔴 OFF"
        status_class = "green" if connected else "red"

    last_update = val(
        raw,
        "last_update",
        default=val(ind, "calculated_at_ist", default=paper.get("last_update_ist")),
    )

    # ---------------- HEADER ----------------
    st.markdown(
        f"""
        <div class="header">
            <div>
                <div class="header-title">📈 NIFTY PAPER</div>
                <div class="header-sub">Paper only · Read-only</div>
            </div>
            <div class="header-status {status_class}">
                {status_text}<br>
                <span class="header-sub">{market}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["📊 MARKET", "🎯 TRADE", "📒 HISTORY"])

    # ========================================================
    # MARKET
    # ========================================================
    with tabs[0]:
        day_high = val(raw, "live_day_high", default=ind.get("intraday_high"))
        day_low = val(raw, "live_day_low", default=ind.get("intraday_low"))

        grid(
            [
                card_html("NIFTY LIVE", number(spot, 2), "last market value", True),
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
                card_html("RSI", number(val(ind, "live_rsi", "rsi"))),
                card_html("EMA 9", number(val(ind, "live_ema9", "ema9"), 0)),
                card_html("EMA 20", number(val(ind, "live_ema20", "ema20"), 0)),
            ],
            3,
        )

        level_engine = d(ind.get("level_engine"))
        support = d(level_engine.get("nearest_support"))
        resistance = d(level_engine.get("nearest_resistance"))

        grid(
            [
                card_html("VOLUME", f'{number(ind.get("live_volume_ratio"))}x'),
                card_html("SUPPORT", number(support.get("level"), 0)),
                card_html("RESISTANCE", number(resistance.get("level"), 0)),
            ],
            3,
        )

        section("CE / PE FLOW")

        order_flow = d(ms.get("order_flow"))
        options_flow = d(order_flow.get("options"))
        ce = d(options_flow.get("ce"))
        pe = d(options_flow.get("pe"))

        grid(
            [
                status_html("CE FLOW", ce.get("state"), "option flow"),
                status_html("PE FLOW", pe.get("state"), "option flow"),
            ],
            2,
        )

        section("OI SUPPORT / RESISTANCE")
        oi_sr = d(ms.get("oi_support_resistance"))

        grid(
            [
                card_html("OI SUPPORT", number(oi_sr.get("support"), 0)),
                card_html("OI RESISTANCE", number(oi_sr.get("resistance"), 0)),
            ],
            2,
        )

        section("FUTURES BUY / SELL")
        futures = d(raw.get("futures_tick"))

        grid(
            [
                card_html("BUY QTY", number(futures.get("total_buy_quantity"), 0)),
                card_html("SELL QTY", number(futures.get("total_sell_quantity"), 0)),
            ],
            2,
        )

        if market == "CLOSED":
            st.markdown(
                f'<div class="last-data">Market closed · Last available data: {fmt_text(last_update)}</div>',
                unsafe_allow_html=True,
            )

    # ========================================================
    # TRADE
    # ========================================================
    with tabs[1]:
        setup = str(val(decision, "setup", default="NONE"))
        trade_type = str(val(decision, "trade_type", default="—"))
        ready = bool(decision.get("ready"))
        decision_class = "green" if ready else "yellow"
        icon = "🟢" if ready else "🟡"
        strike = number(decision.get("option_strike"), 0)

        st.markdown(
            f'<div class="trade">'
            f'<div class="lbl">CURRENT DECISION</div>'
            f'<div class="big {decision_class}">{icon} {setup}</div>'
            f'<div style="font-size:10px;font-weight:900;color:#334155;margin-top:2px">'
            f'{trade_type} · Strike {strike}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        reason = val(
            decision,
            "reason",
            default=ind.get("algo_reason", "Waiting for setup…"),
        )
        st.markdown(f'<div class="reason">{fmt_text(reason)}</div>', unsafe_allow_html=True)

        section("STRATEGY GATES")

        gate_items = [
            (
                "RSI",
                val(decision, "rsi_pass", default=ind.get("signal_rsi_status")),
                f'RSI {number(val(decision, "rsi", default=ind.get("signal_rsi")))}',
            ),
            (
                "EMA",
                val(decision, "ema_pass", default=ind.get("signal_ema_status")),
                f'9 {number(ind.get("signal_ema9"),0)} · 20 {number(ind.get("signal_ema20"),0)}',
            ),
            (
                "VOLUME",
                val(decision, "volume_pass", default=ind.get("signal_vol_status")),
                f'{number(ind.get("signal_volume_ratio"))}x · min 1.20x',
            ),
            (
                "RUNWAY",
                val(decision, "runway_pass", default=ind.get("runway_status")),
                f'{fmt_text(val(decision, "runway", default="—"))} · min 15',
            ),
            (
                "CANDLE",
                decision.get("candle_size_pass"),
                f'{number(decision.get("candle_range"))} pts · 12–25',
            ),
            (
                "WICK",
                decision.get("wick_pass"),
                f'{number(decision.get("opposite_wick"))} pts · max 5% body',
            ),
            (
                "OI / FLOW",
                decision.get("structure_pass"),
                f'{fmt_text(val(decision, "oi_state", default="—"))} / '
                f'{fmt_text(val(decision, "flow_state", default="—"))}',
            ),
        ]

        # 2–3 gates per row, never one full-width gate.
        for i in range(0, len(gate_items), 3):
            batch = gate_items[i:i + 3]
            st.markdown(
                '<div class="grid3">' +
                "".join(status_html(*item) for item in batch) +
                '</div>',
                unsafe_allow_html=True,
            )

        section("TRADE & ACCOUNT")

        if isinstance(active, dict):
            grid(
                [
                    card_html("ACTIVE", active.get("option_symbol", "—")),
                    card_html("QTY", number(active.get("qty"), 0)),
                    card_html(
                        "ENTRY LTP",
                        money(active.get("option_entry_ltp", active.get("entry"))),
                    ),
                ],
                3,
            )

            grid(
                [
                    card_html("CURRENT LTP", money(active.get("current_option_ltp"))),
                    card_html(
                        "RUNNING P&L",
                        money(active.get("running_pnl")),
                        "unrealized",
                    ),
                    card_html(
                        "WALLET",
                        money(
                            val(
                                paper,
                                "wallet_balance",
                                default=journal.get("wallet_balance"),
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
                            val(
                                paper,
                                "realized_pnl",
                                default=journal.get("realized_pnl"),
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
                    card_html("ACTIVE TRADE", "NONE", "waiting"),
                    card_html(
                        "WALLET",
                        money(
                            val(
                                paper,
                                "wallet_balance",
                                default=journal.get("wallet_balance"),
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
                            val(
                                paper,
                                "realized_pnl",
                                default=journal.get("realized_pnl"),
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
        trades = [t for t in lst(journal.get("trades")) if isinstance(t, dict)]

        grid(
            [
                card_html("TRADES", str(len(trades))),
                card_html(
                    "WIN RATE",
                    percent(val(paper, "win_rate", default=journal.get("win_rate"))),
                ),
                card_html(
                    "CLOSED",
                    str(
                        val(
                            paper,
                            "closed_trades",
                            default=journal.get("closed_trades", 0),
                        )
                    ),
                ),
            ],
            3,
        )

        # Wallet/P&L intentionally NOT repeated here.

        section("RECENT TRADES")

        if trades:
            for trade in reversed(trades[-6:]):
                status = str(trade.get("status", "—")).upper()
                pnl_value = val(
                    trade,
                    "pnl_realized",
                    default=trade.get("running_pnl"),
                )
                numeric_pnl = safe_float(pnl_value)
                result_class = (
                    "green"
                    if numeric_pnl > 0
                    else ("red" if numeric_pnl < 0 else "yellow")
                )

                symbol = trade.get("option_symbol", "—")
                trade_type = trade.get("trade_type", trade.get("type", "—"))
                entry_time = trade.get(
                    "entry_time",
                    trade.get("candle_time", "—"),
                )

                st.markdown(
                    f'<div class="status">'
                    f'<span class="left"><b>{trade_type} · {symbol}</b>'
                    f'<span class="detail">{entry_time} · {status}</span></span>'
                    f'<b class="{result_class}">{money(pnl_value)}</b>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="status"><span class="left">'
                '<b>No paper trades yet</b></span>'
                '<b class="muted">—</b></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        f'<div class="last-data">Dashboard update {datetime.now(IST).strftime("%H:%M:%S IST")}</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# LIVE UPDATE
# ============================================================
# Fragment reruns only this dashboard area.
# No st.rerun(), no time.sleep().
# ============================================================
if hasattr(st, "fragment"):
    @st.fragment(run_every=2)
    def live_dashboard():
        render_dashboard()

    live_dashboard()
else:
    render_dashboard()
