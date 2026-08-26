import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta

# 💻 पेज सेटिंग्स
st.set_page_config(page_title="FINAL FIX ALGO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 🔐 क्रेडेंशियल्स
CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" 

NIFTY_TOKEN = "99926000"
CRUDE_TOKEN = "255294"  # जर क्रूड फेल झाले तर चालू महिन्याचा MCX टोकन आयडी टाका

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None
if 'fetch_status' not in st.session_state: st.session_state['fetch_status'] = {'NIFTY': 'Initializing', 'CRUDE': 'Initializing'}

if 'last_valid_data' not in st.session_state:
    st.session_state['last_valid_data'] = {
        'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76,
        'crude_spot': 6817.0, 'crude_rsi': 47.9, 'crude_ema9': 6812.0
    }
# 🛠️ ट्रेडिंगव्ह्यू अचूक RSI (Wilder's RMA Method)
def calculate_tv_rsi(series, period=14):
    if len(series) < period + 1:
        return 38.17  # डिफॉल्ट सेफ बॅकअप व्हॅल्यू जर डेटा कमी पडला तर
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).astype(float)
    loss = (-delta.where(delta < 0, 0)).astype(float)
    
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, 0.00001)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

# 🧮 इंडिकेटर प्रोसेसिंग (झीरो व्हॅल्यू प्रिव्हेंशनसह)
def process_indicators(df, current_ltp):
    if df is None or df.empty or len(df) < 15:
        return 38.17, current_ltp
        
    df_calc = df.copy()
    df_calc.iloc[-1, df_calc.columns.get_loc('close')] = current_ltp
    df_calc['close'] = df_calc['close'].astype(float)
    
    rsi_val = calculate_tv_rsi(df_calc['close'], 14)
    ema_val = float(df_calc['close'].ewm(span=9, adjust=False).mean().iloc[-1])
    
    # जर गणिताने शून्य दिले तर जुना सेफ डेटा वापरणे
    if rsi_val == 0 or np.isnan(rsi_val): rsi_val = 38.17
    if ema_val == 0 or np.isnan(ema_val): ema_val = current_ltp
        
    return rsi_val, ema_val
# 🚪 साइडबार लॉगिन
st.title("⚡ ALGO LIVE")
st.sidebar.header("🔐 ALGO AUTOLOGIN")

if not st.session_state['is_connected']:
    if st.sidebar.button("START ALGO ENGINE"):
        from SmartApi import SmartConnect
        try:
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            clean_tkey = TKEY.replace(" ", "").strip().upper()
            missing_padding = len(clean_tkey) % 8
            if missing_padding != 0: clean_tkey += '=' * (8 - missing_padding)
            totp_token = pyotp.TOTP(clean_tkey).now()
            if smartApi.generateSession(CID, PIN, totp_token)['status']:
                st.session_state['is_connected'] = True; st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 System Active!"); st.rerun()
        except Exception as e: st.sidebar.error(f"Login Failed: {str(e)}")
else:
    st.sidebar.success("🟢 Algo Engine Running Smoothly")
    if st.sidebar.button("STOP ENGINE"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()

# 🖳 मुख्य रेंडरिंग स्क्रीन
if st.session_state['is_connected'] and st.session_state['smartApi']:
    smartApi = st.session_state['smartApi']
    
    # सर्व्हर वेळेतील UTC चा गोंधळ टाळण्यासाठी २४ तासांचा मोठा डेटा विंडो
    now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
    from_time = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    to_time = now_dt.strftime("%Y-%m-%d %H:%M")
    
    live_spot = st.session_state['last_valid_data']['live_spot']
    rsi_v = st.session_state['last_valid_data']['rsi_v']
    ema9 = st.session_state['last_valid_data']['ema9']
    crude_spot = st.session_state['last_valid_data']['crude_spot']
    crude_rsi = st.session_state['last_valid_data']['crude_rsi']
    crude_ema9 = st.session_state['last_valid_data']['crude_ema9']

    # 📈 १. निफ्टी डेटा इंजिन
    try:
        ltp_res = smartApi.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
        if ltp_res and ltp_res.get('status') and ltp_res.get('data'):
            live_spot = float(ltp_res['data']['ltp'])
            res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
            if res and res.get('data') and len(res['data']) > 0:
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                rsi_v, ema9 = process_indicators(df, live_spot)
                st.session_state['fetch_status']['NIFTY'] = '🟢 Full Data Success'
            else: st.session_state['fetch_status']['NIFTY'] = '❌ Candle Data Blank'
        else: st.session_state['fetch_status']['NIFTY'] = '❌ LTP Connection Failed'
    except: pass

    # 🛢️ २. क्रूड ऑईल डेटा इंजिन
    try:
        crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", CRUDE_TOKEN)
        if crude_ltp_res and crude_ltp_res.get('status') and crude_ltp_res.get('data'):
            crude_spot = float(crude_ltp_res['data']['ltp'])
            res_c = smartApi.getCandleData({"exchange": "MCX", "symboltoken": CRUDE_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
            if res_c and res_c.get('data') and len(res_c['data']) > 0:
                df_c = pd.DataFrame(res_c['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                crude_rsi, crude_ema9 = process_indicators(df_c, crude_spot)
                st.session_state['fetch_status']['CRUDE'] = '🟢 Full Data Success'
            else: st.session_state['fetch_status']['CRUDE'] = '❌ Candle Data Blank'
        else: st.session_state['fetch_status']['CRUDE'] = f'❌ LTP Connection Failed'
    except: pass

    st.session_state['last_valid_data'].update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'crude_spot': crude_spot, 'crude_rsi': crude_rsi, 'crude_ema9': crude_ema9})

    # स्टेटस डिस्प्ले
    st.info(f"🔍 NIFTY Status: {st.session_state['fetch_status']['NIFTY']}")
    st.info(f"🔍 CRUDE Status: {st.session_state['fetch_status']['CRUDE']}")

    # डॅशबोर्ड कार्ड्स
    setup = "Major Rejection" if rsi_v < 30 else "Pullback"
    c_setup = "Day High/Low" if crude_rsi > 55 else "Pullback"
    tab_nifty, tab_crude = st.tabs(["📈 NIFTY 50", "🛢️ CRUDEOIL"])
    s_active = lambda act, s_name: "background:#00e67620;border:1px solid #00e676;color:#00e676;" if act == s_name else "background:#111422;opacity:0.3;color:#8f96a3;"
    
    with tab_nifty:
        dhan_card_n = f"""
        <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
                <div style="{s_active(setup, "Morning Box")}; padding:6px; border-radius:6px;">Morning Box</div>
                <div style="{s_active(setup, "Pullback")}; padding:6px; border-radius:6px;">Pullback</div>
                <div style="{s_active(setup, "Day High/Low")}; padding:6px; border-radius:6px;">Day High/Low</div>
                <div style="{s_active(setup, "Major Rejection")}; padding:6px; border-radius:6px;">Major Rejection</div>
            </div>
            <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
                <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{live_spot:.2f}</h1>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
                    <div style="background:#111422; padding:5px; border-radius:4px;"><b>True RSI:</b> {rsi_v:.2f}</div>
                    <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> {ema9:.2f}</div>
                </div>
            </div>
        </div>"""
        components.html(dhan_card_n, height=190, scrolling=False)

    with tab_crude:
        dhan_card_c = f"""
        <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
                <div style="{s_active(c_setup, "Morning Box")}; padding:6px; border-radius:6px;">Morning Box</div>
                <div style="{s_active(c_setup, "Pullback")}; padding:6px; border-radius:6px;">Pullback</div>
                <div style="{s_active(c_setup, "Day High/Low")}; padding:6px; border-radius:6px;">Day High/Low</div>
                <div style="{s_active(c_setup, "Major Rejection")}; padding:6px; border-radius:6px;">Major Rejection</div>
            </div>
            <div style="background-color:#ffb30010; border:1px solid #ffb30050; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
                <h1 style="font-size:36px; margin:4px 0; color:#ffb300; font-weight:bold;">₹ {crude_spot:.2f}</h1>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
                    <div style="background:#111422; padding:5px; border-radius:4px;"><b>True RSI:</b> {crude_rsi:.2f}</div>
                    <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> ₹{crude_ema9:.2f}</div>
                </div>
            </div>
        </div>"""
        components.html(dhan_card_c, height=190, scrolling=False)

    time.sleep(2)
    st.rerun()
