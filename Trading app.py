import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="NIFTY LEDGER DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {'live_spot': 24090.85, 'rsi_v': 25.79, 'ema9': 24145.80, 'nifty_status': '⏳ Waiting', 'last_update': '00:00:00'}
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('previous_good_data', {})

def load_trade_ledger():
    if not os.path.exists('trade_history.json'):
        return {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    try:
        with open('trade_history.json', 'r') as f: return json.load(f)
    except: return {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}

data = load_live_signal()
ledger = load_trade_ledger()
st.session_state['previous_good_data'] = data

st.info(f"📊 NIFTY: {data.get('nifty_status')} | 🕒 TS: {data.get('last_update')}")
rsi_v = data.get('rsi_v', 25.7)
setup = "Pullback" if rsi_v < 50 else "Day High/Low"

def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

def map_pass_fail(status_str):
    return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if status_str == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
dhan_card_html = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.4;">
    <div style="font-size:10px; color:#8f96a3; margin-bottom:8px; font-weight:bold;">🐾 DETECTED TECHNICAL SETUP</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:12px;">
        <div style="{check_active(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_active(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_active(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_active(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:10px; border-radius:10px; text-align:center; margin-bottom:12px;">
        <h1 style="font-size:34px; margin:2px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24090.85):.2f}</h1>
    </div>
    
    <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden; border: 1px solid #1c2136;">
        <thead>
            <tr style="background:#1c2136; color:#8f96a3; font-size:10px; text-align:left;">
                <th style="padding:6px 8px;">INDICATOR NAME</th>
                <th style="padding:6px 8px; text-align:center;">VALUE</th>
                <th style="padding:6px 8px; text-align:right;">STATUS</th>
            </tr>
        </thead>
        <tbody>
            <tr><td style="padding:6px 8px;">1. 5-Min True RSI</td><td style="padding:6px 8px; text-align:center; color:#ffb300; font-weight:bold;">{rsi_v:.1f}</td><td style="padding:6px 8px; text-align:right;">{map_pass_fail(data.get('rsi_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">2. Institutional 9 EMA</td><td style="padding:6px 8px; text-align:center; color:#fff; font-weight:bold;">{data.get('ema9', 24145.80):.2f}</td><td style="padding:6px 8px; text-align:right;">{map_pass_fail(data.get('ema_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">3. Volume Tower</td><td style="padding:6px 8px; text-align:center; color:#fff; font-weight:bold;">{data.get('vol_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pass_fail(data.get('vol_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">4. Runway Breakthrough</td><td style="padding:6px 8px; text-align:center; color:#fff; font-weight:bold;">{data.get('runway_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pass_fail(data.get('runway_status'))}</td></tr>
        </tbody>
    </table>
    <div style="background:#1c2136; border-radius:8px; padding:10px; font-size:11px; margin-top:10px; border-left:4px solid #ffb300; color:#e2e5ec;">
        🧠 <b>ALGO ANALYSIS:</b> {data.get('algo_reason')}
    </div>
</div>"""
components.html(dhan_card_html, height=350, scrolling=False)

st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
col1, col2, col3 = st.columns(3)
with col1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
with col2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
with col3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")

st.markdown("### 📋 RECENT TRADES HISTORY")
if ledger['trades']:
    raw_history_df = pd.DataFrame(ledger['trades']).tail(5)
    display_df = pd.DataFrame({
        'TIME': raw_history_df['time'].str.slice(11, 19),
        'TYPE': raw_history_df['type'],
        'ENTRY': raw_history_df['entry'].round(1),
        'TARGET': raw_history_df['target'].round(1),
        'SL': raw_history_df['sl'].round(1),
        'STATUS': raw_history_df['status']
    })
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.caption("⏳ No trades recorded yet. Waiting for market setup...")

time.sleep(2)
st.rerun()
