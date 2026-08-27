import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

# 💻 कॉम्पॅक्ट मोबाईल लेआउट सेटिंग्स
st.set_page_config(page_title="NIFTY LIVE SCALPER", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 💾 सेफ डेटा लोडर फंक्शन
def load_live_signal():
    if not os.path.exists('data_signal.json'):
        return {
            'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 
            'nifty_status': '⏳ Waiting for Worker', 'last_update': '00:00:00'
        }
    try:
        with open('data_signal.json', 'r') as f: 
            return json.load(f)
    except: 
        return st.session_state.get('previous_good_data', {
            'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 
            'nifty_status': '🔄 Syncing', 'last_update': '00:00:00'
        })

# 📊 मुख्य रेंडरिंग इंजिन सुरू
data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ NIFTY ALGO LIVE")

# 📱 स्क्रीनवर फक्त निफ्टीचा लाइव्ह स्टेटस बार (क्रूड पूर्णपणे काढले)
st.info(f"📊 NIFTY 50: {data.get('nifty_status', '🔄 Syncing')} | 🕒 Last Update: {data.get('last_update', '00:00:00')}")

# सेटअप डिटेक्शन मॅपिंग
rsi_val = data.get('rsi_v', 38.17)
setup = "Major Rejection" if rsi_val < 30 else "Pullback"

# सीएसएस स्टाइल मॅनेजर फंक्शन
def check_active(actual, expected):
    return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if actual == expected else "background:#111422;opacity:0.3;color:#8f96a3;"

# 🎨 निफ्टी डार्क थीम कार्ड रेंडरिंग
dhan_card_n = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
        <div style="{check_active(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
        <div style="{check_active(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
        <div style="{check_active(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
        <div style="{check_active(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
    </div>
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
        <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{data.get('live_spot', 24207.75):.2f}</h1>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
            <div style="background:#111422; padding:5px; border-radius:4px;"><b>True RSI:</b> {rsi_val:.2f}</div>
            <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> {data.get('ema9', 24241.76):.2f}</div>
        </div>
    </div>
</div>"""

components.html(dhan_card_n, height=190, scrolling=False)

# ⏱️ स्क्रीन रीफ्रेश रेट (२ सेकंद)
time.sleep(2)
st.rerun()
