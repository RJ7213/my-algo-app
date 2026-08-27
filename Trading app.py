import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="NIFTY FLUID DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {
            'live_spot': 24334.55, 'rsi_v': 88.6, 'ema9': 24260.30, 'nifty_status': '⏳ Waiting',
            'rsi_status': 'FAIL', 'ema_status': 'FAIL', 'vol_status': 'FAIL',
            'runway_status': 'FAIL', 'oi_status': 'FAIL', 'wall_status': 'FAIL',
            'vol_val': 1.5, 'oi_val': 1.2, 'depth_val': 1.1, 'last_update': '00:00:00'
        }
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('previous_good_data')

data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ ALGO LIVE")
rsi_v = data.get('rsi_v', 88.6)
setup = "Day High/Low" if rsi_v > 70 else "Pullback"

def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

def map_pass_fail(status_str):
    return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if status_str == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'

dhan_card_premium = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.5;">
    
    <div style="font-size:10px; color:#8f96a3; margin-bottom:8px; font-weight:bold;">🐾 DETECTED TECHNICAL SETUP</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:15px;">
        <div style="{check_active(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_active(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_active(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_active(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:15px;">
        <div style="font-size:11px; font-weight:bold; color:#00e676; margin-bottom:4px;">📈 NIFTY SPOT LIVE</div>
        <h1 style="font-size:38px; margin:4px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24334.55):.2f}</h1>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; margin-top:5px;">
            <div style="background:#111422; padding:6px; border-radius:4px;"><b>Nifty RSI:</b> {rsi_v:.1f}</div>
            <div style="background:#111422; padding:6px; border-radius:4px;"><b>9 EMA:</b> {data.get('ema9', 24260.30):.2f}</div>
        </div>
    </div>
    
    <div style="font-size:11px; color:#ffb300; margin-bottom:8px; font-weight:bold;">📋 FLUID CRITERIA MATRICES</div>
    <div style="background:#111422; padding:12px; border-radius:10px; font-size:12px; border: 1px solid #1c2136; display:flex; flex-direction:column; gap:6px;">
        <div style="display:flex; justify-content:between;"><span>1. 5-Min True RSI ({rsi_v:.1f})</span> <span>{map_pass_fail(data.get('rsi_status'))}</span></div>
        <div style="display:flex; justify-content:between;"><span>2. Institutional 9 EMA</span> <span>{map_pass_fail(data.get('ema_status'))}</span></div>
        <div style="display:flex; justify-content:between;"><span>3. Volume Tower ({data.get('vol_val')}x)</span> <span>{map_pass_fail(data.get('vol_status'))}</span></div>
        <div style="display:flex; justify-content:between;"><span>4. Runway Breakthrough</span> <span>{map_pass_fail(data.get('runway_status'))}</span></div>
        <div style="display:flex; justify-content:between;"><span>5. Option Chain OI Bias ({data.get('oi_val')}x)</span> <span>{map_pass_fail(data.get('oi_status'))}</span></div>
        <div style="display:flex; justify-content:between;"><span>6. Order Book Depth Wall</span> <span>{map_pass_fail(data.get('wall_status'))}</span></div>
    </div>
</div>"""

components.html(dhan_card_premium, height=360, scrolling=False)

time.sleep(2)
st.rerun()
