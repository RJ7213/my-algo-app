import json
import math
from datetime import datetime, timezone, timedelta

import streamlit as st

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
# COMPACT MOBILE-FIRST DASHBOARD
# Read-only. No strategy calculations. No trading decisions.
# Only reads engine JSON outputs.
# ============================================================

st.markdown(
    """
<style>
#MainMenu, footer, header {visibility:hidden;}
[data-testid="stAppViewContainer"] {background:#070b12;}
.main .block-container {max-width:560px; padding:.35rem .45rem 1rem;}
[data-testid="stTabs"] button {font-size:12px; font-weight:800; padding:7px 3px;}
[data-testid="stTabs"] [role="tablist"] {gap:1px;}

.card {
    background:#101722;
    border:1px solid #202b3a;
    border-radius:10px;
    padding:7px 9px;
    margin:2px 0;
}
.lbl {font-size:8px;color:#7f8da1;text-transform:uppercase;letter-spacing:.45px;}
.val {font-size:16px;font-weight:800;color:#eef4fb;line-height:1.1;margin-top:2px;}
.sub {font-size:8px;color:#748196;margin-top:2px;}
.section {font-size:11px;font-weight:800;color:#dce5f0;margin:8px 2px 4px;}
.status {
    display:flex;
    justify-content:space-between;
    align-items:center;
    background:#0e1621;
    border:1px solid #202b3a;
    border-radius:9px;
    padding:6px 9px;
    margin:2px 0;
}
.green {color:#5ee58b;}
.red {color:#ff6f75;}
.yellow {color:#f5cf5d;}
.muted {color:#8290a4;}
.big {font-size:22px;font-weight:900;line-height:1.05;}
.tiny {font-size:8px;color:#748196;}
.trade {
    background:#111c2b;
    border:1px solid #294568;
    border-radius:10px;
    padding:8px 9px;
    margin:2px 0;
}
hr {margin:6px 0;border-color:#202b3a;}
[data-testid="stVerticalBlock"] {gap:.15rem;}
@media(max-width:600px){
    .main .block-container{padding:.25rem .3rem .8rem;}
    .val{font-size:15px;}
    .big{font-size:20px;}
}
</style>
""",
    unsafe_allow_html=True,
)


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
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def card(label, value, sub=""):
    st.markdown(
        f'<div class="card"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def gate(name, status, detail=""):
    text = str(status if status is not None else "—").upper()
    if text in ("PASS", "TRUE", "YES", "OK", "READY"):
        cls = "green"
    elif text in ("FAIL", "FALSE", "NO", "ERROR"):
        cls = "red"
    else:
        cls = "yellow"

    st.markdown(
        f'<div class="status"><span><b>{name}</b><br>'
        f'<span class="tiny">{detail}</span></span>'
        f'<b class="{cls}">{text}</b></div>',
        unsafe_allow_html=True,
    )


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


def render_dashboard():
    data = load_all()
    raw = data["raw"]
    ind = data["ind"]
    ms = data["structure"]
    paper = data["paper"]
    journal = data["journal"]

    decision = d(paper.get("decision"))
    active = get_active_trade(paper, journal)

    spot = val(raw, "live_spot", default=val(paper, "live_spot"))
    connected = bool(raw.get("websocket_connected"))
    market = str(
        val(raw, "market_status", default=val(paper, "market_status", default="UNKNOWN"))
    ).upper()

    connection_class = "green" if connected else "red"
    connection_text = "🟢 LIVE" if connected else "🔴 OFF"

    # ---------- HEADER ----------
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:1px 2px 5px">'
        f'<div><b style="font-size:17px">📈 NIFTY PAPER</b>'
        f'<div class="tiny">Paper only · Read-only dashboard</div></div>'
        f'<div style="text-align:right"><b class="{connection_class}">{connection_text}</b>'
        f'<br><span class="tiny">{market}</span></div></div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["📊 MARKET", "🎯 TRADE", "📒 HISTORY"])

    # ========================================================
    # 1. MARKET — ONLY MARKET DATA
    # ========================================================
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            card("NIFTY LIVE", number(spot, 2), "live spot")
        with c2:
            day_high = val(raw, "live_day_high", default=ind.get("intraday_high"))
            day_low = val(raw, "live_day_low", default=ind.get("intraday_low"))
            card("DAY HIGH / LOW", f"{number(day_high, 0)} / {number(day_low, 0)}", "session")

        c1, c2, c3 = st.columns(3)
        with c1:
            card("RSI", number(val(ind, "live_rsi", "rsi")))
        with c2:
            card("EMA 9", number(val(ind, "live_ema9", "ema9"), 0))
        with c3:
            card("EMA 20", number(val(ind, "live_ema20", "ema20"), 0))

        c1, c2, c3 = st.columns(3)
        with c1:
            card("VOLUME", f'{number(ind.get("live_volume_ratio"))}x')
        with c2:
            level_engine = d(ind.get("level_engine"))
            support = d(level_engine.get("nearest_support"))
            card("SUPPORT", number(support.get("level"), 0))
        with c3:
            resistance = d(level_engine.get("nearest_resistance"))
            card("RESISTANCE", number(resistance.get("level"), 0))

        st.markdown('<div class="section">CE / PE FLOW</div>', unsafe_allow_html=True)
        order_flow = d(ms.get("order_flow"))
        options_flow = d(order_flow.get("options"))
        ce = d(options_flow.get("ce"))
        pe = d(options_flow.get("pe"))

        c1, c2 = st.columns(2)
        with c1:
            gate("CE FLOW", ce.get("state"), "option flow")
        with c2:
            gate("PE FLOW", pe.get("state"), "option flow")

        st.markdown('<div class="section">OI SUPPORT / RESISTANCE</div>', unsafe_allow_html=True)
        oi_sr = d(ms.get("oi_support_resistance"))
        c1, c2 = st.columns(2)
        with c1:
            card("OI SUPPORT", number(oi_sr.get("support"), 0))
        with c2:
            card("OI RESISTANCE", number(oi_sr.get("resistance"), 0))

        st.markdown('<div class="section">FUTURES BUY / SELL</div>', unsafe_allow_html=True)
        futures = d(raw.get("futures_tick"))
        c1, c2 = st.columns(2)
        with c1:
            card("BUY QTY", number(futures.get("total_buy_quantity"), 0))
        with c2:
            card("SELL QTY", number(futures.get("total_sell_quantity"), 0))

    # ========================================================
    # 2. TRADE — DECISION + GATES + ACCOUNT IN ONE PLACE
    # ========================================================
    with tabs[1]:
        setup = str(val(decision, "setup", default="NO SETUP"))
        trade_type = str(val(decision, "trade_type", default="—"))
        ready = bool(decision.get("ready"))
        decision_class = "green" if ready else "yellow"
        icon = "🟢" if ready else "🟡"
        strike = number(decision.get("option_strike"), 0)

        st.markdown(
            f'<div class="trade"><div class="tiny">CURRENT DECISION</div>'
            f'<div class="big {decision_class}">{icon} {setup}</div>'
            f'<b>{trade_type}</b> · Strike {strike}</div>',
            unsafe_allow_html=True,
        )

        reason = val(
            decision,
            "reason",
            default=ind.get("algo_reason", default="Waiting for setup…"),
        )
        st.markdown(
            f'<div class="tiny" style="padding:3px 2px 4px">{reason}</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="section">STRATEGY GATES</div>', unsafe_allow_html=True)
        gate(
            "RSI",
            val(decision, "rsi_pass", default=ind.get("signal_rsi_status")),
            f'RSI {number(val(decision, "rsi", default=ind.get("signal_rsi")))}',
        )
        gate(
            "EMA",
            val(decision, "ema_pass", default=ind.get("signal_ema_status")),
            f'9 {number(ind.get("signal_ema9"), 0)} · 20 {number(ind.get("signal_ema20"), 0)}',
        )
        gate(
            "VOLUME",
            val(decision, "volume_pass", default=ind.get("signal_vol_status")),
            f'{number(ind.get("signal_volume_ratio"))}x · min 1.20x',
        )
        gate(
            "RUNWAY",
            val(decision, "runway_pass", default=ind.get("runway_status")),
            f'{val(decision, "runway", default="—")} · min 15',
        )
        gate(
            "CANDLE",
            decision.get("candle_size_pass"),
            f'{number(decision.get("candle_range"))} pts · 12–25',
        )
        gate(
            "WICK",
            decision.get("wick_pass"),
            f'{number(decision.get("opposite_wick"))} pts · max 5% body',
        )
        gate(
            "OI / FLOW",
            decision.get("structure_pass"),
            f'{val(decision, "oi_state", default="—")} / {val(decision, "flow_state", default="—")}',
        )

        # One single place for trade + wallet/account data.
        st.markdown('<div class="section">TRADE & ACCOUNT</div>', unsafe_allow_html=True)

        if isinstance(active, dict):
            c1, c2 = st.columns(2)
            with c1:
                card("ACTIVE", active.get("option_symbol", "—"))
            with c2:
                card("QTY", number(active.get("qty"), 0))

            c1, c2 = st.columns(2)
            with c1:
                card("ENTRY LTP", money(active.get("option_entry_ltp", active.get("entry"))))
            with c2:
                card("CURRENT LTP", money(active.get("current_option_ltp")))

            card("RUNNING P&L", money(active.get("running_pnl")), "unrealized · wallet unchanged")
        else:
            st.markdown(
                '<div class="status"><span>No active paper trade</span>'
                '<b class="muted">WAITING</b></div>',
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)
        with c1:
            card(
                "WALLET",
                money(val(paper, "wallet_balance", default=journal.get("wallet_balance"))),
                "realized only",
            )
        with c2:
            card(
                "REALIZED P&L",
                money(val(paper, "realized_pnl", default=journal.get("realized_pnl"))),
                "closed trades",
            )

    # ========================================================
    # 3. HISTORY — ONLY HISTORY
    # ========================================================
    with tabs[2]:
        trades = [t for t in lst(journal.get("trades")) if isinstance(t, dict)]

        c1, c2, c3 = st.columns(3)
        with c1:
            card("TRADES", str(len(trades)))
        with c2:
            card("WIN RATE", percent(val(paper, "win_rate", default=journal.get("win_rate"))))
        with c3:
            card("CLOSED", str(val(paper, "closed_trades", default=journal.get("closed_trades", 0))))

        total_realized = val(paper, "realized_pnl", default=journal.get("realized_pnl"))
        card("TOTAL REALIZED P&L", money(total_realized))

        st.markdown('<div class="section">RECENT TRADES</div>', unsafe_allow_html=True)

        if trades:
            for trade in reversed(trades[-6:]):
                status = str(trade.get("status", "—")).upper()
                pnl_value = val(trade, "pnl_realized", default=trade.get("running_pnl"))
                pnl = money(pnl_value)
                numeric_pnl = safe_float(pnl_value)
                result_class = "green" if numeric_pnl > 0 else ("red" if numeric_pnl < 0 else "yellow")

                symbol = trade.get("option_symbol", "—")
                trade_type = trade.get("trade_type", trade.get("type", "—"))
                entry_time = trade.get("entry_time", trade.get("candle_time", "—"))

                st.markdown(
                    f'<div class="status"><span><b>{trade_type} · {symbol}</b><br>'
                    f'<span class="tiny">{entry_time} · {status}</span></span>'
                    f'<b class="{result_class}">{pnl}</b></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="status"><span>No paper trades yet</span>'
                '<b class="muted">—</b></div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="tiny" style="text-align:center;margin-top:6px">'
            f'Updated {datetime.now(IST).strftime("%H:%M:%S IST")}</div>',
            unsafe_allow_html=True,
        )


# ============================================================
# LIVE UPDATE
# Only the dashboard fragment reruns every 2 seconds.
# No st.rerun() and no time.sleep().
# ============================================================

if hasattr(st, "fragment"):

    @st.fragment(run_every=2)
    def live_dashboard():
        render_dashboard()

    live_dashboard()
else:
    # Compatibility fallback for older Streamlit versions.
    render_dashboard()
