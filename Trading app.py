import time
import json
import os
import streamlit as st
import streamlit.components.v1 as components

# 💻 कॉम्पॅक्ट मोबाईल लेआउट सेटिंग्स
st.set_page_config(page_title="ALGO MOBILE DASHBOARD", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 💾 सेफ डेटा लोडर फंक्शन (सर्व्हरवर क्रॅश रोखण्यासाठी)
def load_live_signal():
    # जर बॅकएंड कामगाराने अजून फाईल बनवली नसेल तर डिफॉल्ट डेटा दाखवणे
    if not os.path.exists('data_signal.json'):
        return {
            'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 'nifty_status': '⏳ Waiting for Worker',
            'crude_spot': 7670.0, 'crude_rsi': 47.9, 'crude_ema9': 7665.0, 'crude_status': '⏳ Waiting for Worker',
            'last_update': '00:00:00'
        }
    try:
        with open('data_signal.json', 'r') as f:
            return json.load(f)
    except:
        # जर एकाच वेळी रीड आणि राईट झाले तर एरर न दाखवता जुना सेफ डेटा देणे
        return st.session_state.get('previous_good_data', {
            'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 'nifty_status': '🔄 Syncing',
            'crude_spot': 7670.0, 'crude_rsi': 47.9, 'crude_ema9': 7665.0, 'crude_status': '🔄 Syncing',
            'last_update': '00:00:00'
        })
# 📊 मुख्य रेंडरिंग इंजिन सुरू
data = load_live_signal()
st.session_state['previous_good_data'] = data

st.title("⚡ ALGO LIVE")

# 📱 स्क्रीनवर दोन्ही इंजिनचा लाइव्ह स्टेटस बार
st.info(f"📊 NIFTY: {data['nifty_status']} | CRUDE: {data['crude_status']} | 🕒 TS: {data['last_update']}")

# सेटअप डिटेक्शन मॅपिंग
setup = "Major Rejection" if data['rsi_v'] < 30 else "Pullback"
c_setup = "Day High/Low" if data['crude_rsi'] > 55 else "Pullback"

# सीएसएस स्टाइल मॅनेजर फंक्शन (दुरुस्त सुटसुटीत रचना)
def check_active(actual, expected):
    if actual == expected:
        return "background:#00e67620;border:1px solid #00e676;color:#00e676;"
    return "background:#111422;opacity:0.3;color:#8f96a3;"
tab_nifty, tab_crude = st.tabs(["📈 NIFTY 50", "🛢️ CRUDEOIL"])

with tab_nifty:
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

with tab_crude:
    dhan_card_c = f"""
    <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
            <div style="{check_active(c_setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
            <div style="{check_active(c_setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
            <div style="{check_active(c_setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
            <div style="{check_active(c_setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
        </div>
        <div style="background-color:#ffb30010; border:1px solid #ffb30050; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
            <h1 style="font-size:36px; margin:4px 0; color:#ffb300; font-weight:bold;">₹ {data['crude_spot']:.2f}</h1>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
                <div style="background:#111422; padding:5px; border-radius:4px;"><b>True RSI:</b> {data['crude_rsi']:.2f}</div>
                <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> ₹{data['crude_ema9']:.2f}</div>
            </div>
        </div>
    </div>"""
    components.html(dhan_card_c, height=190, scrolling=False)

# ⏱️ स्क्रीन रीफ्रेश रेट (२ सेकंद)
time.sleep(2)
st.rerun()
