import time, json, os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="NIFTY DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

def load_live_signal():
    if not os.path.exists('data_signal.json'): 
        return {'live_spot': 24141.35, 'rsi_v': 44.7, 'ema9': 24152.83, 'nifty_status': '⏳ Waiting...', 'rsi_status': 'FAIL', 'ema_status': 'FAIL', 'vol_status': 'FAIL', 'runway_status': 'FAIL', 'oi_status': 'FAIL', 'wall_status': 'FAIL', 'vol_val': '1.2x SMA', 'runway_val': '45 pts', 'oi_val': '1.8x', 'depth_val': '62%', 'last_update': '00:00:00'}
    try:
        with open('data_signal.json', 'r') as f: return json.load(f)
    except: return st.session_state.get('p_good', {})

data = load_live_signal()
st.session_state['p_good'] = data

st.info(f"📊 NIFTY 50: {data.get('nifty_status')} | 🕒 TS: {data.get('last_update')}")

def map_pf(s): return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'

# कंटेनरची उंची ३८० वरून सरळ ४6० केली जेणेकरून ५ आणि ६ नंबरचे पॉईंट्स मावतील
dhan_html = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.4; height: 430px;">
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:15px;">
        <h1 style="font-size:36px; margin:2px 0; color:#00e676; font-weight:bold;">{data.get('live_spot'):.2f}</h1>
    </div>
    <table style="width:100%; font-size:13px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden; border: 1px solid #1c2136;">
        <thead><tr style="background:#1c2136; color:#8f96a3; font-size:11px;"><th style="padding:8px;">INDICATOR NAME</th><th style="padding:8px; text-align:center;">VALUE</th><th style="padding:8px; text-align:right;">STATUS</th></tr></thead>
        <tbody>
            <tr><td style="padding:8px;">1. 5-Min True RSI</td><td style="padding:8px; text-align:center; color:#ffb300; font-weight:bold;">{data.get('rsi_v', 0.0):.1f}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('rsi_status'))}</td></tr>
            <tr><td style="padding:8px;">2. Institutional 9 EMA</td><td style="padding:8px; text-align:center; color:#fff;">{data.get('ema9', 0.0):.2f}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('ema_status'))}</td></tr>
            <tr><td style="padding:8px;">3. Volume Tower</td><td style="padding:8px; text-align:center; color:#fff;">{data.get('vol_val')}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('vol_status'))}</td></tr>
            <tr><td style="padding:8px;">4. Runway Breakthrough</td><td style="padding:8px; text-align:center; color:#fff;">{data.get('runway_val')}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('runway_status'))}</td></tr>
            <tr><td style="padding:8px;">5. Option Chain OI Bias</td><td style="padding:8px; text-align:center; color:#fff;">{data.get('oi_val', '1.0x')}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('oi_status', 'FAIL'))}</td></tr>
            <tr><td style="padding:8px;">6. Order Book Depth Wall</td><td style="padding:8px; text-align:center; color:#fff;">{data.get('depth_val', '0%')}</td><td style="padding:8px; text-align:right;">{map_pf(data.get('wall_status', 'PASS'))}</td></tr>
        </tbody>
    </table>
</div>"""

components.html(dhan_html, height=450, scrolling=False)
time.sleep(2); st.rerun()
