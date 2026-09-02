# Trading app.py
# ============================================================
# NIFTY PAPER TRADING DASHBOARD
# ============================================================
#
# READ-ONLY DASHBOARD
# -------------------
# This file NEVER calculates strategy and NEVER sends orders.
#
# Reads:
#   data_raw.json
#   processed_indicators.json
#   processed_market_structure.json
#   paper_engine_output.json
#   trade_history.json
#
# SHOWS ALL IMPORTANT FIELDS PUBLISHED BY ALL ENGINES:
#   1) Connection / market status
#   2) NIFTY spot
#   3) Day High / Day Low
#   4) Live + signal RSI
#   5) Live + signal EMA9 / EMA20
#   6) Volume / volume ratio
#   7) Runway
#   8) Candle OHLC / range / body / wicks
#   9) Major levels / support / resistance
#  10) Option-chain contracts
#  11) OI / OI change / volume
#  12) Buy Qty / Sell Qty
#  13) Best-5 BUY / SELL order book
#  14) Market-structure OI support/resistance
#  15) Order-flow
#  16) Current paper decision
#  17) Active paper trade
#  18) Actual option LTP
#  19) Running P&L
#  20) Wallet / realized P&L / win rate
#  21) Complete trade journal
#
# IMPORTANT:
#   Dashboard is READ-ONLY.
#   No trading logic is implemented here.
# ============================================================

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="NIFTY PAPER TRADING PRO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
<style>
.main .block-container {
    padding-top: 0.7rem;
    padding-bottom: 1rem;
    max-width: 1800px;
}

.metric-card {
    padding: 12px;
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 10px;
    margin-bottom: 8px;
}

.section-title {
    font-size: 20px;
    font-weight: 700;
    margin-top: 12px;
    margin-bottom: 8px;
}

.small-muted {
    font-size: 12px;
    opacity: .75;
}

.pass {
    font-weight: 700;
}

.fail {
    font-weight: 700;
}

.status-box {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid rgba(128,128,128,.25);
    margin-bottom: 8px;
}

div[data-testid="stMetric"] {
    padding: 8px;
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CONSTANTS
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

FILES = {
    "raw": "data_raw.json",
    "indicators": "processed_indicators.json",
    "structure": "processed_market_structure.json",
    "paper": "paper_engine_output.json",
    "ledger": "trade_history.json",
}


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt_num(value, decimals=2):
    x = safe_float(value)
    if x is None:
        return "—"
    return f"{x:,.{decimals}f}"


def fmt_money(value):
    x = safe_float(value)
    if x is None:
        return "—"
    return f"₹{x:,.2f}"


def fmt_pct(value):
    x = safe_float(value)
    if x is None:
        return "—"
    return f"{x:.2f}%"


def quote_age(timestamp):
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(str(timestamp))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return max(
            0.0,
            (datetime.now(dt.tzinfo) - dt).total_seconds(),
        )
    except Exception:
        return None


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_all():
    return {
        key: read_json(path)
        for key, path in FILES.items()
    }


def get_dict(obj):
    return obj if isinstance(obj, dict) else {}


def get_list(obj):
    return obj if isinstance(obj, list) else []


def first_value(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def status_text(value):
    text = str(value or "—").upper()
    if text == "PASS":
        return "🟢 PASS"
    if text == "FAIL":
        return "🔴 FAIL"
    if text in ("SUPPORTIVE", "BUY_BIASED", "BUY_DOMINANT"):
        return "🟢 " + text
    if text in ("OPPOSING", "SELL_BIASED", "SELL_DOMINANT"):
        return "🔴 " + text
    if text in ("NEUTRAL", "BALANCED"):
        return "🟡 " + text
    return text


def flatten_dict(obj, prefix=""):
    """
    Generic read-only field extractor.
    This guarantees newly-added engine fields can also be shown
    without adding dashboard calculations.
    """
    rows = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                rows.extend(flatten_dict(value, name))
            else:
                rows.append({
                    "FIELD": name,
                    "VALUE": value,
                })

    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            name = f"{prefix}[{i}]"
            if isinstance(value, (dict, list)):
                rows.extend(flatten_dict(value, name))
            else:
                rows.append({
                    "FIELD": name,
                    "VALUE": value,
                })

    else:
        rows.append({
            "FIELD": prefix,
            "VALUE": obj,
        })

    return rows


def show_json_fields(title, data, expanded=False):
    with st.expander(title, expanded=expanded):
        rows = flatten_dict(data)
        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No data available.")


# ============================================================
# LOAD
# ============================================================

data = read_all()

raw = get_dict(data["raw"])
ind = get_dict(data["indicators"])
structure = get_dict(data["structure"])
paper = get_dict(data["paper"])
ledger = get_dict(data["ledger"])


# ============================================================
# HEADER
# ============================================================

spot = safe_float(
    first_value(
        raw,
        "live_spot",
        default=first_value(paper, "live_spot"),
    )
)

market_status = str(
    first_value(
        raw,
        "market_status",
        default=first_value(paper, "market_status", default="UNKNOWN"),
    )
)

worker_status = first_value(raw, "worker_status", default="—")
raw_update = first_value(raw, "last_update_ist", "last_update", default="—")
paper_update = first_value(paper, "last_update_ist", default="—")

st.title("📊 NIFTY PAPER TRADING PRO")

h1, h2, h3, h4 = st.columns(4)

with h1:
    st.metric("NIFTY 50", fmt_num(spot, 2))

with h2:
    st.metric("Market", market_status)

with h3:
    st.metric("Worker", "CONNECTED" if raw.get("websocket_connected") else "—")

with h4:
    st.metric("Mode", "PAPER ONLY")


st.caption(
    f"Raw update: {raw_update}  |  Paper engine: {paper_update}  |  "
    f"Worker: {worker_status}"
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("⚙️ Dashboard")

    auto_refresh = st.checkbox(
        "Auto refresh",
        value=True,
    )

    refresh_sec = st.slider(
        "Refresh seconds",
        min_value=1,
        max_value=10,
        value=2,
    )

    st.divider()

    st.subheader("Files")

    for label, filename in FILES.items():
        exists = os.path.exists(filename)
        st.write(
            f"{'🟢' if exists else '🔴'} {filename}"
        )

    st.divider()

    st.caption(
        "READ-ONLY dashboard. "
        "No strategy calculation and no live order execution."
    )


# ============================================================
# TOP MARKET DATA
# ============================================================

st.markdown('<div class="section-title">📈 Market Snapshot</div>', unsafe_allow_html=True)

m1, m2, m3, m4, m5, m6 = st.columns(6)

with m1:
    st.metric("Spot", fmt_num(spot))

with m2:
    st.metric(
        "Day High",
        fmt_num(
            first_value(
                raw,
                "live_day_high",
                default=first_value(ind, "intraday_high"),
            )
        ),
    )

with m3:
    st.metric(
        "Day Low",
        fmt_num(
            first_value(
                raw,
                "live_day_low",
                default=first_value(ind, "intraday_low"),
            )
        ),
    )

with m4:
    st.metric(
        "WebSocket",
        "🟢 LIVE" if raw.get("websocket_connected") else "🔴 OFF",
    )

with m5:
    st.metric(
        "Session",
        first_value(raw, "session_day", default="—"),
    )

with m6:
    st.metric(
        "Option Center",
        fmt_num(first_value(raw, "option_chain_center")),
    )


# ============================================================
# LIVE INDICATORS
# ============================================================

st.markdown('<div class="section-title">🧠 Live Indicators + Signal Candle</div>', unsafe_allow_html=True)

live_rsi = first_value(ind, "rsi", "live_rsi", "rsi_v")
signal_rsi = first_value(ind, "signal_rsi")

live_ema9 = first_value(ind, "ema9", "live_ema9")
signal_ema9 = first_value(ind, "signal_ema9")

live_ema20 = first_value(ind, "ema20", "live_ema20")
signal_ema20 = first_value(ind, "signal_ema20")

live_vol = first_value(ind, "live_volume")
live_vol_avg = first_value(ind, "live_volume_avg")
live_vol_ratio = first_value(ind, "live_volume_ratio")

signal_vol = first_value(ind, "signal_volume")
signal_vol_avg = first_value(ind, "signal_volume_avg")
signal_vol_ratio = first_value(ind, "signal_volume_ratio")

runway = first_value(
    paper.get("decision", {}),
    "runway",
    default=first_value(ind, "runway_val"),
)

i1, i2, i3, i4, i5, i6 = st.columns(6)

with i1:
    st.metric("Live RSI", fmt_num(live_rsi))

with i2:
    st.metric("Signal RSI", fmt_num(signal_rsi))

with i3:
    st.metric("Live EMA9", fmt_num(live_ema9))

with i4:
    st.metric("Signal EMA9", fmt_num(signal_ema9))

with i5:
    st.metric("Live EMA20", fmt_num(live_ema20))

with i6:
    st.metric("Signal EMA20", fmt_num(signal_ema20))

v1, v2, v3, v4 = st.columns(4)

with v1:
    st.metric("Live Volume", fmt_num(live_vol, 0))

with v2:
    st.metric("Live Volume Avg", fmt_num(live_vol_avg, 0))

with v3:
    st.metric("Live Volume Ratio", f"{fmt_num(live_vol_ratio)}x")

with v4:
    st.metric("Signal Volume Ratio", f"{fmt_num(signal_vol_ratio)}x")


# ============================================================
# GATES
# ============================================================

st.markdown('<div class="section-title">🚦 Strategy Gates</div>', unsafe_allow_html=True)

decision = get_dict(paper.get("decision"))

gate_rows = [
    {
        "Gate": "RSI",
        "Status": status_text(
            first_value(decision, "rsi_pass", default=first_value(ind, "signal_rsi_status"))
        ),
        "Value": fmt_num(first_value(decision, "rsi")),
        "Reason": first_value(decision, "rsi_reason", default="—"),
    },
    {
        "Gate": "EMA",
        "Status": status_text(
            first_value(decision, "ema_pass", default=first_value(ind, "signal_ema_status"))
        ),
        "Value": f"EMA9 {fmt_num(signal_ema9)} / EMA20 {fmt_num(signal_ema20)}",
        "Reason": first_value(decision, "ema_reason", default="—"),
    },
    {
        "Gate": "VOLUME",
        "Status": status_text(
            first_value(decision, "volume_pass", default=first_value(ind, "signal_vol_status"))
        ),
        "Value": f"{fmt_num(signal_vol_ratio)}x",
        "Reason": "Required ≥ 1.20x",
    },
    {
        "Gate": "RUNWAY",
        "Status": status_text(
            first_value(decision, "runway_pass", default=first_value(ind, "runway_status"))
        ),
        "Value": str(first_value(decision, "runway", default=first_value(ind, "runway_val", default="—"))),
        "Reason": "Required ≥ 15 points",
    },
    {
        "Gate": "CANDLE SIZE",
        "Status": status_text(
            first_value(decision, "candle_size_pass")
        ),
        "Value": f"{fmt_num(first_value(decision, 'candle_range'))} pts",
        "Reason": "Required 12–25 points",
    },
    {
        "Gate": "OPPOSITE WICK",
        "Status": status_text(
            first_value(decision, "wick_pass")
        ),
        "Value": f"{fmt_num(first_value(decision, 'opposite_wick'))} pts",
        "Reason": "Required ≤ 5% of body",
    },
    {
        "Gate": "OI / ORDER FLOW",
        "Status": status_text(
            first_value(decision, "structure_pass")
        ),
        "Value": f"OI={first_value(decision, 'oi_state', default='—')} / FLOW={first_value(decision, 'flow_state', default='—')}",
        "Reason": first_value(decision, "oi_reason", default="—"),
    },
]

st.dataframe(
    pd.DataFrame(gate_rows),
    use_container_width=True,
    hide_index=True,
)


# ============================================================
# CURRENT DECISION
# ============================================================

st.markdown('<div class="section-title">🎯 Current Paper Decision</div>', unsafe_allow_html=True)

d1, d2, d3, d4, d5 = st.columns(5)

with d1:
    st.metric(
        "Setup",
        first_value(decision, "setup", default="NONE"),
    )

with d2:
    st.metric(
        "Trade Type",
        first_value(decision, "trade_type", default="NONE"),
    )

with d3:
    st.metric(
        "Strike",
        fmt_num(first_value(decision, "option_strike"), 0),
    )

with d4:
    st.metric(
        "Ready",
        "🟢 YES" if decision.get("ready") else "🔴 NO",
    )

with d5:
    st.metric(
        "Candle",
        str(first_value(decision, "candle_time", default="—")),
    )

st.info(
    first_value(
        decision,
        "reason",
        default=first_value(ind, "algo_reason", default="No decision available"),
    )
)


# ============================================================
# CANDLE STRUCTURE
# ============================================================

st.markdown('<div class="section-title">🕯️ Completed Signal Candle</div>', unsafe_allow_html=True)

completed = get_list(ind.get("completed_candles"))

if completed:
    candle = get_dict(completed[-1])

    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)

    with c1:
        st.metric("Time", str(first_value(candle, "date", "datetime", default="—")))

    with c2:
        st.metric("Open", fmt_num(first_value(candle, "open")))

    with c3:
        st.metric("High", fmt_num(first_value(candle, "high")))

    with c4:
        st.metric("Low", fmt_num(first_value(candle, "low")))

    with c5:
        st.metric("Close", fmt_num(first_value(candle, "close")))

    with c6:
        st.metric("Range", fmt_num(first_value(decision, "candle_range")))

    with c7:
        st.metric("Body", fmt_num(first_value(decision, "candle_body")))

    with c8:
        st.metric("Top/Bottom Wick", f"{fmt_num(first_value(decision, 'upper_wick'))} / {fmt_num(first_value(decision, 'lower_wick'))}")
else:
    st.warning("Completed candle data not available.")


# ============================================================
# LEVEL ENGINE
# ============================================================

st.markdown('<div class="section-title">📐 Level Engine</div>', unsafe_allow_html=True)

level_engine = get_dict(ind.get("level_engine"))
levels = get_list(level_engine.get("levels"))

l1, l2 = st.columns(2)

with l1:
    nearest_support = level_engine.get("nearest_support")
    if isinstance(nearest_support, dict):
        st.metric(
            "Nearest Support",
            fmt_num(nearest_support.get("level")),
        )
        st.caption(
            f"{nearest_support.get('name', '—')} | "
            f"Strength {nearest_support.get('strength', '—')}"
        )
    else:
        st.metric("Nearest Support", "—")

with l2:
    nearest_resistance = level_engine.get("nearest_resistance")
    if isinstance(nearest_resistance, dict):
        st.metric(
            "Nearest Resistance",
            fmt_num(nearest_resistance.get("level")),
        )
        st.caption(
            f"{nearest_resistance.get('name', '—')} | "
            f"Strength {nearest_resistance.get('strength', '—')}"
        )
    else:
        st.metric("Nearest Resistance", "—")

if levels:
    level_rows = []
    for x in levels:
        if isinstance(x, dict):
            level_rows.append({
                "LEVEL": x.get("level"),
                "NAME": x.get("name"),
                "SOURCE": x.get("source"),
                "STRENGTH": x.get("strength"),
                "DISTANCE": (
                    abs(
                        safe_float(spot, 0.0)
                        - safe_float(x.get("level"), 0.0)
                    )
                    if spot is not None
                    else None
                ),
            })

    st.dataframe(
        pd.DataFrame(level_rows).sort_values(
            "DISTANCE",
            na_position="last",
        ),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# MARKET STRUCTURE
# ============================================================

st.markdown('<div class="section-title">🏗️ Market Structure</div>', unsafe_allow_html=True)

ms1, ms2, ms3, ms4 = st.columns(4)

order_flow = get_dict(structure.get("order_flow"))
oi_sr = get_dict(structure.get("oi_support_resistance"))

with ms1:
    st.metric(
        "OI Key Level",
        fmt_num(
            first_value(
                structure,
                "oi_key_level",
                default=first_value(structure, "key_oi_level"),
            )
        ),
    )

with ms2:
    st.metric(
        "Structure Bias",
        first_value(
            structure,
            "market_bias",
            "structure_bias",
            default="—",
        ),
    )

with ms3:
    st.metric(
        "CE Flow",
        str(first_value(order_flow.get("options", {}).get("ce", {}), "state", default="—")),
    )

with ms4:
    st.metric(
        "PE Flow",
        str(first_value(order_flow.get("options", {}).get("pe", {}), "state", default="—")),
    )

if oi_sr:
    st.subheader("OI Support / Resistance")

    supports = get_list(oi_sr.get("supports"))
    resistances = get_list(oi_sr.get("resistances"))

    sr_rows = []

    for x in supports:
        if isinstance(x, dict):
            row = dict(x)
            row["SIDE"] = "SUPPORT"
            sr_rows.append(row)

    for x in resistances:
        if isinstance(x, dict):
            row = dict(x)
            row["SIDE"] = "RESISTANCE"
            sr_rows.append(row)

    if sr_rows:
        st.dataframe(
            pd.DataFrame(sr_rows),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# ORDER FLOW
# ============================================================

if order_flow:
    st.subheader("Order Flow")

    per_option = get_dict(order_flow.get("per_option"))

    if per_option:
        flow_rows = []

        for key, value in per_option.items():
            if isinstance(value, dict):
                row = dict(value)
                row["CONTRACT"] = key
                flow_rows.append(row)

        if flow_rows:
            st.dataframe(
                pd.DataFrame(flow_rows),
                use_container_width=True,
                hide_index=True,
            )

    aggregate_flow = {
        "CE": order_flow.get("options", {}).get("ce", {}),
        "PE": order_flow.get("options", {}).get("pe", {}),
    }

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "SIDE": side,
                    **(value if isinstance(value, dict) else {}),
                }
                for side, value in aggregate_flow.items()
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# OPTION CHAIN
# ============================================================

st.markdown('<div class="section-title">📋 Live NIFTY Option Chain</div>', unsafe_allow_html=True)

chain = raw.get("option_chain")
chain = chain if isinstance(chain, dict) else {}

chain_rows = []

for key, item in chain.items():
    if not isinstance(item, dict):
        continue

    strike = safe_float(
        item.get("strike"),
        safe_float(
            key.split(":")[0]
            if ":" in str(key)
            else None
        ),
    )

    option_type = (
        str(item.get("option_type") or item.get("type") or "")
        .upper()
    )

    if not option_type and ":" in str(key):
        option_type = str(key).split(":")[-1].upper()

    ltp = safe_float(item.get("ltp"))

    ts = item.get("timestamp") or item.get("exchange_timestamp")

    chain_rows.append({
        "KEY": key,
        "STRIKE": strike,
        "TYPE": option_type,
        "SYMBOL": item.get("symbol") or item.get("tradingsymbol"),
        "TOKEN": item.get("token") or item.get("symboltoken"),
        "EXPIRY": item.get("expiry"),

        "LTP": ltp,
        "LTP AGE SEC": quote_age(ts),

        "OI": item.get("open_interest"),
        "OI CHANGE %": item.get("open_interest_change_percentage"),
        "DAY VOLUME": item.get("volume_day"),

        "LAST TRADED QTY": item.get("last_traded_quantity"),
        "AVG TRADED PRICE": item.get("average_traded_price"),

        "TOTAL BUY QTY": item.get("total_buy_quantity"),
        "TOTAL SELL QTY": item.get("total_sell_quantity"),

        "OPEN": item.get("open_price"),
        "HIGH": item.get("high_price"),
        "LOW": item.get("low_price"),
        "CLOSE": item.get("closed_price"),

        "UPPER CIRCUIT": item.get("upper_circuit"),
        "LOWER CIRCUIT": item.get("lower_circuit"),

        "EXCHANGE TS": item.get("exchange_timestamp"),
        "TIMESTAMP": item.get("timestamp"),
    })


if chain_rows:
    chain_df = pd.DataFrame(chain_rows)

    sort_cols = [x for x in ["STRIKE", "TYPE"] if x in chain_df.columns]
    if sort_cols:
        chain_df = chain_df.sort_values(sort_cols)

    st.dataframe(
        chain_df,
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    st.caption(
        f"Contracts displayed: {len(chain_rows)} | "
        f"Window: ±{raw.get('option_chain_window_points', '—')} points | "
        f"Strike step: {raw.get('option_chain_strike_step', '—')}"
    )
else:
    st.warning("Live option chain is not available yet.")


# ============================================================
# BEST-5 ORDER BOOK
# ============================================================

st.markdown('<div class="section-title">📚 Option Best-5 Order Book</div>', unsafe_allow_html=True)

if chain:
    selected_key = st.selectbox(
        "Select contract for Best-5",
        options=list(chain.keys()),
        index=(
            list(chain.keys()).index(
                f"{safe_int(first_value(decision, 'option_strike'), 0)}:{first_value(decision, 'option_type', default='CE')}"
            )
            if f"{safe_int(first_value(decision, 'option_strike'), 0)}:{first_value(decision, 'option_type', default='CE')}" in chain
            else 0
        ),
    )

    selected = get_dict(chain.get(selected_key))

    b1, b2 = st.columns(2)

    with b1:
        st.subheader("BUY — Best 5")
        buy5 = get_list(selected.get("best_5_buy_data"))
        if buy5:
            st.dataframe(
                pd.DataFrame(buy5),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No Best-5 BUY data.")

    with b2:
        st.subheader("SELL — Best 5")
        sell5 = get_list(selected.get("best_5_sell_data"))
        if sell5:
            st.dataframe(
                pd.DataFrame(sell5),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No Best-5 SELL data.")
else:
    st.info("Option chain unavailable.")


# ============================================================
# FUTURES
# ============================================================

st.markdown('<div class="section-title">📦 NIFTY Futures</div>', unsafe_allow_html=True)

fut_contract = get_dict(raw.get("futures_contract"))
fut_tick = get_dict(raw.get("futures_tick"))

f1, f2, f3, f4, f5, f6 = st.columns(6)

with f1:
    st.metric("Future LTP", fmt_num(fut_tick.get("ltp")))

with f2:
    st.metric("Future Volume", fmt_num(fut_tick.get("volume_day"), 0))

with f3:
    st.metric("Future OI", fmt_num(fut_tick.get("open_interest"), 0))

with f4:
    st.metric("Future Buy Qty", fmt_num(fut_tick.get("total_buy_quantity"), 0))

with f5:
    st.metric("Future Sell Qty", fmt_num(fut_tick.get("total_sell_quantity"), 0))

with f6:
    st.metric("Live 5m Volume", fmt_num(raw.get("live_futures_volume_5m"), 0))

st.dataframe(
    pd.DataFrame(
        [
            {
                "FIELD": key,
                "VALUE": value,
            }
            for key, value in fut_contract.items()
        ]
    ),
    use_container_width=True,
    hide_index=True,
)


# ============================================================
# ACTIVE PAPER TRADE
# ============================================================

st.markdown('<div class="section-title">💼 Active Paper Trade</div>', unsafe_allow_html=True)

active = paper.get("active_trade")

if not isinstance(active, dict):
    active = next(
        (
            t for t in get_list(ledger.get("trades"))
            if str(t.get("status")) == "ACTIVE"
        ),
        None,
    )

if isinstance(active, dict):
    a1, a2, a3, a4, a5, a6 = st.columns(6)

    with a1:
        st.metric("Trade ID", str(active.get("trade_id", "—")))

    with a2:
        st.metric("Type", str(active.get("trade_type", active.get("type", "—"))))

    with a3:
        st.metric("Symbol", str(active.get("option_symbol", "—")))

    with a4:
        st.metric("Strike", fmt_num(active.get("option_strike"), 0))

    with a5:
        st.metric("Entry LTP", fmt_money(active.get("option_entry_ltp", active.get("entry"))))

    with a6:
        st.metric("Current LTP", fmt_money(active.get("current_option_ltp")))

    a7, a8, a9, a10, a11, a12 = st.columns(6)

    with a7:
        st.metric("Qty", fmt_num(active.get("qty"), 0))

    with a8:
        st.metric("Running P&L", fmt_money(active.get("running_pnl")))

    with a9:
        st.metric("Index Entry", fmt_num(active.get("index_entry")))

    with a10:
        st.metric("Index SL", fmt_num(active.get("index_sl")))

    with a11:
        st.metric("Index Target", fmt_num(active.get("index_target")))

    with a12:
        st.metric("Status", str(active.get("status", "ACTIVE")))

    st.dataframe(
        pd.DataFrame(
            [
                {"FIELD": key, "VALUE": value}
                for key, value in active.items()
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

else:
    st.info("No active paper trade.")


# ============================================================
# WALLET / PERFORMANCE
# ============================================================

st.markdown('<div class="section-title">💰 Paper Wallet & Performance</div>', unsafe_allow_html=True)

wallet = first_value(
    paper,
    "wallet_balance",
    default=first_value(ledger, "wallet_balance"),
)

starting = first_value(
    paper,
    "starting_balance",
    default=first_value(ledger, "starting_balance"),
)

realized = first_value(
    paper,
    "realized_pnl",
    default=first_value(ledger, "realized_pnl"),
)

running = first_value(
    paper,
    "running_pnl",
    default=first_value(ledger, "active_running_pnl"),
)

total_pnl = first_value(
    paper,
    "total_pnl",
    default=first_value(ledger, "total_pnl"),
)

w1, w2, w3, w4, w5, w6 = st.columns(6)

with w1:
    st.metric("Starting", fmt_money(starting))

with w2:
    st.metric("Wallet", fmt_money(wallet))

with w3:
    st.metric("Realized P&L", fmt_money(realized))

with w4:
    st.metric("Running P&L", fmt_money(running))

with w5:
    st.metric("Total P&L", fmt_money(total_pnl))

with w6:
    st.metric(
        "Win Rate",
        fmt_pct(
            first_value(
                paper,
                "win_rate",
                default=first_value(ledger, "win_rate"),
            )
        ),
    )

p1, p2, p3, p4 = st.columns(4)

with p1:
    st.metric(
        "Total Trades",
        safe_int(
            first_value(
                paper,
                "trade_count",
                default=first_value(ledger, "total_trades"),
            )
        ),
    )

with p2:
    st.metric(
        "Closed",
        safe_int(
            first_value(
                paper,
                "closed_trades",
                default=first_value(ledger, "closed_trades"),
            )
        ),
    )

with p3:
    st.metric(
        "Target Hits",
        safe_int(
            first_value(
                paper,
                "target_hits",
                default=first_value(ledger, "target_hits"),
            )
        ),
    )

with p4:
    st.metric(
        "SL Hits",
        safe_int(
            first_value(
                paper,
                "sl_hits",
                default=first_value(ledger, "sl_hits"),
            )
        ),
    )


# ============================================================
# COMPLETE TRADE JOURNAL
# ============================================================

st.markdown('<div class="section-title">📒 Complete Paper Trade Journal</div>', unsafe_allow_html=True)

trades = get_list(ledger.get("trades"))

if trades:
    journal_rows = []

    for t in trades:
        if not isinstance(t, dict):
            continue

        journal_rows.append({
            "TRADE ID": t.get("trade_id"),
            "STATUS": t.get("status"),

            "ENTRY TIME": t.get("entry_time"),
            "EXIT TIME": t.get("exit_time"),

            "TYPE": t.get("trade_type", t.get("type")),
            "STRATEGY": t.get("strategy_used"),

            "SYMBOL": t.get("option_symbol"),
            "EXPIRY": t.get("option_expiry"),
            "STRIKE": t.get("option_strike"),

            "ENTRY LTP": t.get("option_entry_ltp", t.get("entry")),
            "EXIT LTP": t.get("option_exit_ltp", t.get("exit_price")),
            "CURRENT LTP": t.get("current_option_ltp"),

            "QTY": t.get("qty"),

            "INDEX ENTRY": t.get("index_entry"),
            "INDEX SL": t.get("index_sl"),
            "INDEX TARGET": t.get("index_target"),

            "PREMIUM SL": t.get("premium_sl"),
            "PREMIUM TARGET": t.get("premium_target"),

            "RUNNING P&L": t.get("running_pnl"),
            "REALIZED P&L": t.get("pnl_realized"),

            "EXIT REASON": t.get("exit_reason"),

            "RSI": t.get("signal_rsi"),
            "EMA9": t.get("signal_ema9"),
            "EMA20": t.get("signal_ema20"),
            "VOLUME RATIO": t.get("volume_ratio"),
            "RUNWAY": t.get("runway"),

            "OI STATE": t.get("oi_state"),
            "FLOW STATE": t.get("flow_state"),

            "CANDLE TIME": t.get("candle_time"),
            "QUOTE TIME": t.get("last_quote_time"),
        })

    journal_df = pd.DataFrame(journal_rows)

    st.dataframe(
        journal_df,
        use_container_width=True,
        hide_index=True,
        height=450,
    )

    # Full selected trade.
    trade_ids = [
        str(t.get("trade_id"))
        for t in trades
        if isinstance(t, dict)
    ]

    if trade_ids:
        selected_trade_id = st.selectbox(
            "View complete trade fields",
            trade_ids,
        )

        selected_trade = next(
            (
                t for t in trades
                if str(t.get("trade_id")) == selected_trade_id
            ),
            None,
        )

        if selected_trade:
            show_json_fields(
                f"🔎 Complete fields — {selected_trade_id}",
                selected_trade,
                expanded=False,
            )
else:
    st.info("No paper trades recorded yet.")


# ============================================================
# ENGINE RAW DATA — ALL FIELDS
# ============================================================

st.markdown('<div class="section-title">🔍 Full Engine Data — All Published Fields</div>', unsafe_allow_html=True)

st.caption(
    "These sections are read-only diagnostic views. "
    "No values are calculated or modified by the dashboard."
)

show_json_fields(
    "1️⃣ data_raw.json — ALL fields",
    raw,
    expanded=False,
)

show_json_fields(
    "2️⃣ processed_indicators.json — ALL fields",
    ind,
    expanded=False,
)

show_json_fields(
    "3️⃣ processed_market_structure.json — ALL fields",
    structure,
    expanded=False,
)

show_json_fields(
    "4️⃣ paper_engine_output.json — ALL fields",
    paper,
    expanded=False,
)

show_json_fields(
    "5️⃣ trade_history.json — ALL fields",
    ledger,
    expanded=False,
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()
