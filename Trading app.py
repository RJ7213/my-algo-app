# ============================================================
# NIFTY PAPER TRADING PRO — LIGHTWEIGHT LIVE DASHBOARD
# ============================================================
# READ-ONLY: no strategy calculation, no BUY/SELL logic, no orders.
# ============================================================

import json
import math
import os
from datetime import timedelta, timezone

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="NIFTY Paper Trading Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
st.markdown(
    """
<style>
[data-testid="stAppViewContainer"] { background:#f4f6f9; }
[data-testid="stHeader"] { background:rgba(244,246,249,.94); }
.main .block-container { max-width:1500px; padding:.65rem .8rem 1.5rem; }
#MainMenu, footer { visibility:hidden; }

.hero { background:linear-gradient(135deg,#111827,#273449); color:#fff;
        border-radius:14px; padding:12px 15px; margin-bottom:9px; }
.hero-title { font-size:22px; font-weight:850; }
.hero-sub { font-size:10px; opacity:.72; margin-top:2px; }

.kpi { background:#fff; border:1px solid #e2e8f0; border-radius:11px;
       padding:8px 10px; min-height:68px; box-shadow:0 1px 5px rgba(15,23,42,.045); }
.kpi-label { font-size:9px; color:#64748b; text-transform:uppercase; letter-spacing:.55px; }
.kpi-value { font-size:20px; font-weight:850; color:#111827; margin-top:2px; white-space:nowrap; }
.kpi-sub { font-size:9px; color:#94a3b8; margin-top:1px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

.section { font-size:16px; font-weight:850; color:#111827; margin:12px 0 6px; }
.card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:11px 12px; }
.trade-main { font-size:24px; font-weight:900; color:#111827; }
.muted { color:#64748b; font-size:11px; }
.good { color:#087443; font-weight:800; }
.bad { color:#b42318; font-weight:800; }
.warn { color:#9a6700; font-weight:800; }

[data-testid="stTabs"] button { font-weight:850; font-size:13px; }
[data-testid="stDataFrame"] { border-radius:9px; overflow:hidden; }

@media (max-width:700px) {
  .main .block-container { padding:.35rem .45rem 1rem; }
  .hero-title { font-size:19px; }
  .kpi { min-height:61px; padding:7px 8px; }
  .kpi-value { font-size:17px; }
  .section { font-size:15px; margin-top:10px; }
}
</style>
""",
    unsafe_allow_html=True,
)

IST = timezone(timedelta(hours=5, minutes=30))
FILES = {
    "raw": "data_raw.json",
    "ind": "processed_indicators.json",
    "structure": "processed_market_structure.json",
    "paper": "paper_engine_output.json",
    "ledger": "trade_history.json",
}


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def fmt(value, decimals=2, fallback="—"):
    x = safe_float(value)
    return fallback if x is None else f"{x:,.{decimals}f}"


def money(value):
    x = safe_float(value)
    return "—" if x is None else f"₹{x:,.2f}"


def first(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for key in keys:
        v = d.get(key)
        if v is not None and v != "":
            return v
    return default


def dct(v):
    return v if isinstance(v, dict) else {}


def lst(v):
    return v if isinstance(v, list) else []


def kpi(label, value, sub=""):
    st.markdown(
        f'<div class="kpi"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def section(title):
    st.markdown(f'<div class="section">{title}</div>', unsafe_allow_html=True)


def state_text(value):
    s = str(value if value is not None else "—").upper()
    if s in {"PASS", "TRUE", "YES", "SUPPORTIVE", "BUY_BIASED", "BUY_DOMINANT", "LIVE", "READY", "OK"}:
        return "🟢 " + s
    if s in {"FAIL", "FALSE", "NO", "OPPOSING", "SELL_BIASED", "SELL_DOMINANT", "OFF", "WAIT"}:
        return "🔴 " + s
    return "🟡 " + s


def render_dashboard():
    # --------------------------------------------------------
    # LOAD — inside refreshable fragment so live data updates
    # without rebuilding the whole Streamlit page.
    # --------------------------------------------------------
    raw = load_json(FILES["raw"])
    ind = load_json(FILES["ind"])
    structure = load_json(FILES["structure"])
    paper = load_json(FILES["paper"])
    ledger = load_json(FILES["ledger"])
    decision = dct(paper.get("decision"))

    spot = first(raw, "live_spot", default=first(paper, "live_spot"))
    connected = bool(raw.get("websocket_connected"))
    market_status = str(first(raw, "market_status", default=first(paper, "market_status", default="UNKNOWN")))
    last_update = first(raw, "last_update_ist", "last_update", default="—")

    active = dct(paper.get("active_trade"))
    if not active:
        active = next((dct(t) for t in lst(ledger.get("trades")) if str(t.get("status", "")).upper() == "ACTIVE"), {})

    setup = str(first(decision, "setup", default="NONE"))
    trade_type = str(first(decision, "trade_type", default="NONE"))
    strike = first(decision, "option_strike")
    ready = bool(decision.get("ready"))

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------
    conn = "🟢 LIVE" if connected else "🔴 OFFLINE"
    st.markdown(
        f'<div class="hero"><div class="hero-title">📈 NIFTY PAPER TRADING PRO</div>'
        f'<div class="hero-sub">{conn} · {market_status.upper()} · PAPER ONLY · Last tick: {last_update}</div></div>',
        unsafe_allow_html=True,
    )

    # Always-visible market bar — the trader should see these first.
    cols = st.columns(7)
    market_items = [
        ("NIFTY SPOT", fmt(spot), "live"),
        ("DAY HIGH", fmt(first(raw, "live_day_high", default=ind.get("intraday_high"))), "session"),
        ("DAY LOW", fmt(first(raw, "live_day_low", default=ind.get("intraday_low"))), "session"),
        ("LIVE RSI", fmt(first(ind, "rsi", "live_rsi")), "live"),
        ("EMA 9", fmt(first(ind, "ema9", "live_ema9")), "live"),
        ("EMA 20", fmt(first(ind, "ema20", "live_ema20")), "live"),
        ("LIVE VOL", f'{fmt(ind.get("live_volume_ratio"))}x', "ratio"),
    ]
    for col, item in zip(cols, market_items):
        with col:
            kpi(*item)

    tab_market, tab_trade, tab_history = st.tabs([
        "📊 LIVE MARKET",
        "🎯 LIVE TRADE",
        "📒 TRADE HISTORY",
    ])

    # ========================================================
    # LIVE MARKET
    # ========================================================
    with tab_market:
        section("Technical Snapshot")
        cols = st.columns(6)
        items = [
            ("Signal RSI", fmt(ind.get("signal_rsi")), "closed candle"),
            ("Signal EMA 9", fmt(ind.get("signal_ema9")), "closed candle"),
            ("Signal EMA 20", fmt(ind.get("signal_ema20")), "closed candle"),
            ("Live Volume", fmt(ind.get("live_volume"), 0), "current"),
            ("Signal Volume", f'{fmt(ind.get("signal_volume_ratio"))}x', "ratio"),
            ("Runway CE / PE", f'{fmt(ind.get("runway_ce"))} / {fmt(ind.get("runway_pe"))}', "points"),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

        section("Level Engine")
        levels = dct(ind.get("level_engine", ind.get("levels")))
        support = dct(levels.get("nearest_support"))
        resistance = dct(levels.get("nearest_resistance"))
        cols = st.columns(6)
        items = [
            ("Support", fmt(support.get("level")), support.get("name", "—")),
            ("Resistance", fmt(resistance.get("level")), resistance.get("name", "—")),
            ("Support Strength", str(support.get("strength", "—")), "level"),
            ("Resistance Strength", str(resistance.get("strength", "—")), "level"),
            ("Morning Box", f'{fmt(levels.get("morning_box_high"))} / {fmt(levels.get("morning_box_low"))}', "H / L"),
            ("Day H / L", f'{fmt(first(raw,"live_day_high",default=ind.get("intraday_high")))} / {fmt(first(raw,"live_day_low",default=ind.get("intraday_low")))}', "session"),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

        section("OI & Order Flow")
        order_flow = dct(structure.get("order_flow"))
        options_flow = dct(order_flow.get("options"))
        ce_flow = dct(options_flow.get("ce"))
        pe_flow = dct(options_flow.get("pe"))
        oi_sr = dct(structure.get("oi_support_resistance"))
        cols = st.columns(6)
        items = [
            ("ATM", fmt(structure.get("atm"), 0), "structure"),
            ("OI Support", fmt(oi_sr.get("support"), 0), "OI"),
            ("OI Resistance", fmt(oi_sr.get("resistance"), 0), "OI"),
            ("CE Flow", state_text(ce_flow.get("state")), "options"),
            ("PE Flow", state_text(pe_flow.get("state")), "options"),
            ("Bias", str(first(structure, "structure_bias", "bias", default="—")), "descriptive"),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

        section("NIFTY Futures")
        fut = dct(raw.get("futures_tick"))
        cols = st.columns(6)
        items = [
            ("Future LTP", fmt(fut.get("ltp")), "NIFTY FUT"),
            ("Future Volume", fmt(fut.get("volume_day"), 0), "day"),
            ("Future OI", fmt(fut.get("open_interest"), 0), "day"),
            ("Buy Qty", fmt(fut.get("total_buy_quantity"), 0), "best-5"),
            ("Sell Qty", fmt(fut.get("total_sell_quantity"), 0), "best-5"),
            ("Live 5m Volume", fmt(raw.get("live_futures_volume_5m"), 0), "current"),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

        section("Live Option Chain")
        chain = raw.get("option_chain")
        if isinstance(chain, dict) and chain:
            rows = []
            for key, q0 in chain.items():
                q = dct(q0)
                rows.append({
                    "STRIKE": safe_float(q.get("strike", key)),
                    "TYPE": str(q.get("option_type", q.get("type", ""))),
                    "LTP": safe_float(q.get("ltp")),
                    "OI": safe_float(q.get("open_interest")),
                    "OI CHG %": safe_float(q.get("oi_change_pct")),
                    "VOLUME": safe_float(q.get("volume")),
                    "BUY QTY": safe_float(q.get("total_buy_quantity")),
                    "SELL QTY": safe_float(q.get("total_sell_quantity")),
                })
            df = pd.DataFrame(rows)
            if not df.empty:
                df = df.sort_values(["STRIKE", "TYPE"], na_position="last")
                st.dataframe(df, width="stretch", hide_index=True, height=360)
                st.caption(f'{len(df)} contracts · center {raw.get("option_chain_center", "—")} · 50-point strikes')
        else:
            st.info("Waiting for live option chain…")

        section("System Health")
        cols = st.columns(5)
        health = [
            ("WebSocket", "LIVE" if connected else "OFF", "data worker"),
            ("Candles", "OK" if raw.get("candle_last_success") else "WAIT", "historical cache"),
            ("Indicators", "READY" if ind else "WAIT", "technical engine"),
            ("Structure", "READY" if structure else "WAIT", "OI / flow engine"),
            ("Paper Engine", "READY" if paper else "WAIT", "decision engine"),
        ]
        for col, item in zip(cols, health):
            with col:
                kpi(*item)

    # ========================================================
    # LIVE TRADE
    # ========================================================
    with tab_trade:
        section("Current Paper Decision")
        decision_label = f"{setup} · {trade_type}"
        if strike is not None:
            decision_label += f" · {fmt(strike, 0)}"
        reason = first(decision, "reason", default="Waiting for all strategy gates…")
        st.markdown(
            f'<div class="card"><div class="muted">PAPER ENGINE</div>'
            f'<div class="trade-main">{"🟢" if ready else "🟡"} {decision_label}</div>'
            f'<div class="muted" style="margin-top:4px">{reason}</div></div>',
            unsafe_allow_html=True,
        )

        section("Strategy Gates")
        gates = dct(decision.get("gates", decision.get("gate_status")))
        if gates:
            gate_rows = []
            for name, value in gates.items():
                if isinstance(value, dict):
                    status = first(value, "status", "state", "pass", default="—")
                    detail = first(value, "reason", "message", default="")
                else:
                    status, detail = value, ""
                gate_rows.append({
                    "GATE": str(name).replace("_", " ").upper(),
                    "STATUS": state_text(status),
                    "DETAIL": str(detail),
                })
            st.dataframe(pd.DataFrame(gate_rows), width="stretch", hide_index=True)
        else:
            st.info("Gate details will appear when paper_engine publishes them.")

        section("Active Paper Trade")
        if active:
            cols = st.columns(8)
            items = [
                ("Trade ID", str(active.get("trade_id", "—")), ""),
                ("Type", str(active.get("trade_type", active.get("type", "—"))), ""),
                ("Option", str(active.get("option_symbol", "—")), "contract"),
                ("Qty", fmt(active.get("qty"), 0), "units"),
                ("Entry LTP", money(active.get("option_entry_ltp", active.get("entry"))), "actual"),
                ("Current LTP", money(active.get("current_option_ltp")), "actual"),
                ("Running P&L", money(active.get("running_pnl")), "unrealized"),
                ("SL / Target", f'{fmt(active.get("index_sl"))} / {fmt(active.get("index_target"))}', "index points"),
            ]
            for col, item in zip(cols, items):
                with col:
                    kpi(*item)
        else:
            st.info("No active paper trade — waiting for a valid completed-candle setup.")

        section("Signal Candle")
        candle = dct(first(decision, "signal_candle", "candle", default=ind.get("latest_completed_candle")))
        cols = st.columns(7)
        items = [
            ("Candle Time", str(first(decision, "candle_time", default=candle.get("time", "—"))), "closed"),
            ("Open", fmt(candle.get("open")), ""),
            ("High", fmt(candle.get("high")), ""),
            ("Low", fmt(candle.get("low")), ""),
            ("Close", fmt(candle.get("close")), ""),
            ("Range", fmt(first(decision, "candle_range", default=candle.get("range"))), "points"),
            ("Runway", fmt(first(decision, "runway", default="—")), "points"),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

        section("Paper Wallet & Performance")
        cols = st.columns(7)
        items = [
            ("Starting", money(first(paper, "starting_balance", default=ledger.get("starting_balance"))), ""),
            ("Wallet", money(first(paper, "wallet_balance", default=ledger.get("wallet_balance"))), "realized only"),
            ("Running P&L", money(paper.get("running_pnl")), "unrealized"),
            ("Realized P&L", money(paper.get("realized_pnl")), "closed trades"),
            ("Total P&L", money(paper.get("total_pnl")), ""),
            ("Closed", str(safe_int(first(paper, "closed_trades", default=ledger.get("closed_trades")))), "trades"),
            ("Win Rate", f'{fmt(first(paper, "win_rate", default=ledger.get("win_rate")))}%', ""),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(*item)

    # ========================================================
    # TRADE HISTORY
    # ========================================================
    with tab_history:
        section("Performance Summary")
        cols = st.columns(6)
        items = [
            ("Total Trades", str(safe_int(first(paper, "trade_count", default=ledger.get("total_trades"))))),
            ("Closed", str(safe_int(first(paper, "closed_trades", default=ledger.get("closed_trades"))))),
            ("Target Hits", str(safe_int(first(paper, "target_hits", default=ledger.get("target_hits"))))),
            ("SL Hits", str(safe_int(first(paper, "sl_hits", default=ledger.get("sl_hits"))))),
            ("Realized P&L", money(paper.get("realized_pnl"))),
            ("Wallet", money(paper.get("wallet_balance"))),
        ]
        for col, item in zip(cols, items):
            with col:
                kpi(item[0], item[1], "")

        section("Trade Journal")
        trades = [dct(t) for t in lst(ledger.get("trades"))]
        if trades:
            rows = []
            for t in trades:
                rows.append({
                    "ID": t.get("trade_id"),
                    "STATUS": t.get("status"),
                    "ENTRY": t.get("entry_time"),
                    "EXIT": t.get("exit_time"),
                    "TYPE": t.get("trade_type", t.get("type")),
                    "STRATEGY": t.get("strategy_used"),
                    "SYMBOL": t.get("option_symbol"),
                    "STRIKE": t.get("option_strike"),
                    "ENTRY LTP": t.get("option_entry_ltp", t.get("entry")),
                    "EXIT LTP": t.get("option_exit_ltp", t.get("exit_price")),
                    "QTY": t.get("qty"),
                    "SL": t.get("index_sl"),
                    "TARGET": t.get("index_target"),
                    "P&L": t.get("pnl_realized"),
                    "EXIT REASON": t.get("exit_reason"),
                    "RSI": t.get("signal_rsi"),
                    "VOL": t.get("volume_ratio"),
                    "OI": t.get("oi_state"),
                    "FLOW": t.get("flow_state"),
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=480)
        else:
            st.info("No paper trades recorded yet.")

        with st.expander("Diagnostics / Engine Files", expanded=False):
            status = []
            for _, path in FILES.items():
                status.append({"FILE": path, "STATUS": "READY" if os.path.exists(path) else "WAITING"})
            st.dataframe(pd.DataFrame(status), width="stretch", hide_index=True)


# ------------------------------------------------------------
# LIVE REFRESH
# ------------------------------------------------------------
# Streamlit fragments prevent the entire page from rebuilding every tick.
# 2 seconds is fast enough for a paper-trading dashboard while remaining
# light on the mobile browser. It does NOT create Angel One API calls.
fragment = getattr(st, "fragment", None)
if fragment is not None:
    @fragment(run_every=2)
    def live_dashboard():
        render_dashboard()
    live_dashboard()
else:
    render_dashboard()
