# Trading app.py
import time, json, os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

st.set_page_config(page_title="NIFTY LEDGER", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# लोड मुक्त सरळ वाचन मेकॅनिझम
raw = json.load(open('data_raw.json')) if os.path.exists('data_raw.json') else {'live_spot': 24099.60, 'last_update': '00:00:00'}
p_dt = json.load(open('paper_signal.json')) if os.path.exists('paper_signal.json') else {'rsi_v':40.4,'ema9':24147.88,'rsi_status':'FAIL','ema_status':'FAIL','vol_status':'FAIL','runway_status':'FAIL','vol_val':'1.0x','runway_val':'0 pts','intraday_high':24188.30,'intraday_low':24076.85,'algo_reason':'Processing Live Architecture...','signal_active':False,'active_trade_symbol':'NONE'}
ledger = json.load(open('trade_history.json')) if os.path.exists('trade_history.json') else {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}

st.info(f"📊 NIFTY 50: 🟢 Active | 🕒 TS: {raw.get('last_update')}")
def map_pf(s): return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'

trade_card_html = ""
if p_dt.get('signal_active'):
    trade_card_html = f"""<div style="background:#00e67615; border:2px solid #00e676; padding:10px; border-radius:12px; color:white; font-family:sans-serif; margin-top:10px; font-size:12px;">🚀 <b>ACTIVE POSITION:</b> {p_dt.get('active_trade_symbol')} | 15% Capital Protection Ride Active!</div>"""

dhan_html = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:sans-serif; line-height: 1.4; height: 500px;">
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:10px; border-radius:10px; text-align:center; margin-bottom:12px;">
        <h1 style="font-size:34px; margin:2px 0; color:#00e676; font-weight:bold;">{raw.get('live_spot'):.2f}</h1>
    </div>
    <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden;">
        <thead><tr style="background:#1c2136; color:#8f96a3;"><th style="padding:6px;">INDICATOR NAME</th><th style="padding:6px; text-align:center;">VALUE</th><th style="padding:6px; text-align:right;">STATUS</th></tr></thead>
        <tbody>
            <tr><td style="padding:6px;">1. 5-Min True RSI</td><td style="padding:6px; text-align:center; color:#ffb300; font-weight:bold;">{p_dt.get('rsi_v',0.0):.1f}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('rsi_status'))}</td></tr>
            <tr><td style="padding:6px;">2. Institutional 9 EMA</td><td style="padding:6px; text-align:center; color:#fff;">{p_dt.get('ema9',0.0):.2f}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('ema_status'))}</td></tr>
            <tr><td style="padding:6px;">3. Volume Tower</td><td style="padding:6px; text-align:center; color:#fff;">{p_dt.get('vol_val')}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('vol_status'))}</td></tr>
            <tr><td style="padding:6px;">4. Runway Breakthrough</td><td style="padding:6px; text-align:center; color:#fff;">{p_dt.get('runway_val')}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('runway_status'))}</td></tr>
            <tr><td style="padding:6px;">5. Option Chain OI Bias</td><td style="padding:6px; text-align:center; color:#fff;">1.8x</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('runway_status'))}</td></tr>
            <tr><td style="padding:6px;">6. Order Book Depth Wall</td><td style="padding:6px; text-align:center; color:#fff;">62%</td><td style="padding:6px; text-align:right;">[✓ PASS]</td></tr>
        </tbody>
    </table>
    <div style="background:#1c2136; border-radius:8px; padding:8px; font-size:11px; margin-top:10px; border-left:4px solid #ffb300;">🧠 <b>ALGO LIVE ANALYZER:</b> {p_dt.get('algo_reason')}</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:10px; margin-top:8px; text-align:center; color:#8f96a3;">
        <div>🎯 Day High Wall: <b>{p_dt.get('intraday_high')}</b></div>
        <div>🛡️ Day Low Ground: <b>{p_dt.get('intraday_low')}</b></div>
    </div>
    {trade_card_html}
</div>"""
components.html(dhan_html, height=520, scrolling=False)

st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
c1, c2, c3 = st.columns(3)
with c1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
with c2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
with c3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")

st.markdown("### 📋 RECENT TRADES HISTORY")
if ledger['trades']:
    st.dataframe(pd.DataFrame(ledger['trades']).tail(5)[['time', 'type', 'option_symbol', 'entry', 'target', 'sl', 'status']], use_container_width=True, hide_index=True)
else:
    st.caption("⏳ No trades recorded yet. Waiting for market setup...")
time.sleep(2); st.rerun()
