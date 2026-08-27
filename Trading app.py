import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="NIFTY LIVE SCALPER", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 'nifty_status': '⏳ Waiting', 'last_update': '00:00:00'}
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('previous_good_data', {'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 'nifty_status': '🔄 Syncing', 'last_update': '00:00:00'})

data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ NIFTY ALGO LIVE")
st.info(f"📊 NIFTY 50: {data['nifty_status']} | 🕒 Last Update: {data['last_update']}")

setup = "Major Rejection" if data['rsi_v'] < 30 else "Pullback"

def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

dhan_card_n = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
        <div style="{check_active(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_active(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_active(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_active(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
        <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{data['live_spot']:.2f}</h1>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
            <div style="background:#111422; padding:5px; border-radius:4px;"><b>True RSI:</b> {data['rsi_v']:.2f}</div>
            <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> {data['ema9']:.2f}</div>
        </div>
    </div>
</div>"""
components.html(dhan_card_n, height=190, scrolling=False)

time.sleep(2)
st.rerun()
