# Trading app.py - भाग १
import time, json, os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="NIFTY LEDGER DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

def load_live_signal():
    if not os.path.exists('data_signal.json'): return {'live_spot': 24090.85, 'rsi_v': 25.79, 'ema9': 24145.80, 'nifty_status': '⏳ Waiting for Worker...', 'last_update': '00:00:00', 'rsi_status': 'FAIL', 'ema_status': 'FAIL', 'vol_status': 'FAIL', 'runway_status': 'FAIL', 'oi_status': 'FAIL', 'wall_status': 'FAIL', 'vol_val': '1.0x', 'runway_val': '0 pts', 'oi_val': '1.0x', 'depth_val': '0%', 'intraday_high': 24297.45, 'intraday_low': 24090.85, 'algo_reason': 'Starting...'}
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('p_good', {})

def load_trade_ledger():
    if not os.path.exists('trade_history.json'): return {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    try:
        with open('trade_history.json', 'r') as f: return json.load(f)
    except: return {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}

data, ledger = load_live_signal(), load_trade_ledger()
st.session_state['p_good'] = data
st.info(f"📊 NIFTY: {data.get('nifty_status')} | 🕒 TS: {data.get('last_update')}")
rsi_v = data.get('rsi_v', 25.7)
setup = "Pullback" if rsi_v < 50 else "Day High/Low"

def check_act(a, e): return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if a == e else "background:#111422;opacity:0.3;color:#8f96a3;"
def map_pf(s): return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
# Trading app.py - भाग २
dhan_html = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.4; height: 550px;">
    <div style="font-size:10px; color:#8f96a3; margin-bottom:8px; font-weight:bold;">🐾 DETECTED TECHNICAL SETUP</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:12px;">
        <div style="{check_act(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_act(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_act(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_act(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:10px; border-radius:10px; text-align:center; margin-bottom:12px;">
        <h1 style="font-size:34px; margin:2px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24090.85):.2f}</h1>
    </div>
    <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden; border: 1px solid #1c2136;">
        <thead><tr style="background:#1c2136; color:#8f96a3; font-size:10px;"><th style="padding:6px 8px;">INDICATOR NAME</th><th style="padding:6px 8px; text-align:center;">VALUE</th><th style="padding:6px 8px; text-align:right;">STATUS</th></tr></thead>
        <tbody>
            <tr><td style="padding:6px 8px;">1. 5-Min True RSI</td><td style="padding:6px 8px; text-align:center; color:#ffb300; font-weight:bold;">{rsi_v:.1f}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('rsi_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">2. Institutional 9 EMA</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data.get('ema9', 24145.80):.2f}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('ema_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">3. Volume Tower</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data.get('vol_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('vol_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">4. Runway Breakthrough</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data.get('runway_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('runway_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">5. Option Chain OI Bias</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data.get('oi_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('oi_status'))}</td></tr>
            <tr><td style="padding:6px 8px;">6. Order Book Depth Wall</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data.get('depth_val')}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data.get('wall_status'))}</td></tr>
        </tbody>
    </table>
    <div style="background:#1c2136; border-radius:8px; padding:10px; font-size:11px; margin-top:10px; border-left:4px solid #ffb300; color:#e2e5ec;">🧠 <b>ALGO ANALYSIS:</b> {data.get('algo_reason')}</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:10px; margin-top:8px; text-align:center; color:#8f96a3;">
        <div style="background:#111422; padding:5px; border-radius:4px;">🎯 Day High Wall: <b>{data.get('intraday_high')}</b></div>
        <div style="background:#111422; padding:5px; border-radius:4px;">🛡️ Day Low Ground: <b>{data.get('intraday_low')}</b></div>
    </div>
</div>"""
components.html(dhan_html, height=580, scrolling=False)

st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
c1, c2, c3 = st.columns(3)
with c1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
with c2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
with c3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")

st.markdown("### 📋 RECENT TRADES HISTORY")
if ledger['trades']:
    raw_df = pd.DataFrame(ledger['trades']).tail(5)
    st.dataframe(pd.DataFrame({'TIME': raw_df['time'], 'TYPE': raw_df['type'], 'ENTRY': raw_df['entry'].round(1), 'TARGET': raw_df['target'].round(1), 'SL': raw_df['sl'].round(1), 'STATUS': raw_df['status']}), use_container_width=True, hide_index=True)
else:
    st.caption("⏳ No trades recorded yet. Waiting for market setup...")
time.sleep(2); st.rerun()
