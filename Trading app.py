import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

# 💻 कॉम्पॅक्ट मोबाईल लेआउट सेटिंग्स
st.set_page_config(page_title="NIFTY FLUID DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 💾 सेफ डेटा लोडर फंक्शन
def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {
            'live_spot': 24165.30, 'rsi_v': 33.8, 'ema9': 24171.64, 'nifty_status': '⏳ Waiting',
            'rsi_status': 'PASS', 'ema_status': 'FAIL', 'vol_status': 'FAIL',
            'runway_status': 'FAIL', 'oi_status': 'FAIL', 'wall_status': 'FAIL',
            'vol_val': 1.1, 'oi_val': 0.8, 'depth_val': 1.2, 'last_update': '00:00:00'
        }
    try:
        with open('data_signal.json', 'r') as f: 
            return json.load(f)
    except: 
        return st.session_state.get('previous_good_data')

# 📊 मुख्य रेंडरिंग इंजिन सुरू
data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ ALGO LIVE")

# 📱 स्क्रीनवर फक्त निफ्टीचा लाइव्ह स्टेटस बार
st.info(f"📊 NIFTY 50: {data.get('nifty_status', '🔄 Syncing')} | 🕒 Last Update: {data.get('last_update', '00:00:00')}")

# सेटअप डिटेक्शन मॅपिंग
rsi_v = data.get('rsi_v', 33.8)
setup = "Pullback" if rsi_v < 50 else "Day High/Low"

# सीएसएस स्टाइल मॅनेजर फंक्शन
def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

def map_pass_fail(status_str):
    return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if status_str == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'

# 🎨 निफ्टी डार्क थीम कार्ड रेंडरिंग (६ चेकपॉइंट्स रचना)
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
        <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24165.30):.2f}</h1>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px; margin-top:5px;">
            <div style="background:#111422; padding:6px; border-radius:4px;"><b>Nifty RSI:</b> {rsi_v:.1f}</div>
            <div style="background:#111422; padding:6px; border-radius:4px;"><b>9 EMA:</b> {data.get('ema9', 24171.64):.2f}</div>
        </div>
    </div>
    
    <div style="font-size:11px; color:#ffb300; margin-bottom:8px; font-weight:bold;">📋 FLUID CRITERIA MATRICES</div>
    <div style="background:#111422; padding:12px; border-radius:10px; font-size:12px; border: 1px solid #1c2136; display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; justify-content:space-between; width:100%;"><span>1. 5-Min True RSI ({rsi_v:.1f})</span> <span>{map_pass_fail(data.get('rsi_status', 'FAIL'))}</span></div>
        <div style="display:flex; justify-content:space-between; width:100%;"><span>2. Institutional 9 EMA</span> <span>{map_pass_fail(data.get('ema_status', 'FAIL'))}</span></div>
        <div style="display:flex; justify-content:space-between; width:100%;"><span>3. Volume Tower ({data.get('vol_val', 1.1)}x)</span> <span>{map_pass_fail(data.get('vol_status', 'FAIL'))}</span></div>
        <div style="display:flex; justify-content:space-between; width:100%;"><span>4. Runway Breakthrough</span> <span>{map_pass_fail(data.get('runway_status', 'FAIL'))}</span></div>
        <div style="display:flex; justify-content:space-between; width:100%;"><span>5. Option Chain OI Bias ({data.get('oi_val', 0.8)}x)</span> <span>{map_pass_fail(data.get('oi_status', 'FAIL'))}</span></div>
        <div style="display:flex; justify-content:space-between; width:100%;"><span>6. Order Book Depth Wall</span> <span>{map_pass_fail(data.get('wall_status', 'FAIL'))}</span></div>
    </div>
</div>"""

components.html(dhan_card_premium, height=390, scrolling=False)

# ⏱️ स्क्रीन रीफ्रेश रेट (२ सेकंद)
time.sleep(2)
st.rerun()
