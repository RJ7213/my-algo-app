import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

# 💻 पेज सेटिंग्स
st.set_page_config(page_title="RENDER PINPOINT ALGO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 🔐 क्रेडेंशियल्स मेमरी
CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" 

# 🧠 सेशन स्टेट बॅकअप (वारंवार डाउनलोड रोखण्यासाठी)
if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None
if 'nifty_df_cache' not in st.session_state: st.session_state['nifty_df_cache'] = None
if 'crude_df_cache' not in st.session_state: st.session_state['crude_df_cache'] = None
if 'last_fetch_time' not in st.session_state: st.session_state['last_fetch_time'] = {'NIFTY': datetime.min, 'CRUDE': datetime.min}

if 'last_valid_data' not in st.session_state:
    st.session_state['last_valid_data'] = {
        'live_spot': 24207.75, 'rsi_v': 19.81, 'ema9': 24220.30,
        'crude_spot': 6817.0, 'crude_rsi': 47.9, 'crude_ema9': 6812.0,
        'setup_detected': "Major Rejection", 'c_setup': "Pullback"
    }
# 🛠️ ट्रेडिंगव्ह्यू अचूक RSI (RMA Method)
def calculate_tv_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).astype(float)
    loss = (-delta.where(delta < 0, 0)).astype(float)
    
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, 0.00001)
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# 🧮 लाईव्ह टिक सिंकिंग इंजिन
def process_indicators(df, current_ltp):
    if df is None or df.empty:
        return 0.0, 0.0
    
    df_calc = df.copy()
    # शेवटच्या कॅन्डलमध्ये लाईव्ह टिक भरणे
    df_calc.iloc[-1, df_calc.columns.get_loc('close')] = current_ltp
    df_calc['close'] = df_calc['close'].astype(float)
    
    rsi_val = calculate_tv_rsi(df_calc['close'], 14)
    ema_val = float(df_calc['close'].ewm(span=9, adjust=False).mean().iloc[-1])
    
    return float(rsi_val), float(ema_val)
# 🚪 साइडबार ऑटोलॉगिन
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
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 System Active!")
                st.rerun()
        except Exception as e: st.sidebar.error(f"Login Failed: {str(e)}")
else:
    st.sidebar.success("🟢 Algo Engine Running Smoothly")
    if st.sidebar.button("STOP ENGINE"):
        st.session_state['is_connected'] = False
        st.session_state['smartApi'] = None
        st.rerun()

# 🖳 मुख्य रेंडरिंग स्क्रीन
if st.session_state['is_connected'] and st.session_state['smartApi']:
    smartApi = st.session_state['smartApi']
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    current_time = ist_now.time()
    is_weekend = (ist_now.weekday() >= 5)
    
    live_spot = st.session_state['last_valid_data']['live_spot']
    rsi_v = st.session_state['last_valid_data']['rsi_v']
    ema9 = st.session_state['last_valid_data']['ema9']
    crude_spot = st.session_state['last_valid_data']['crude_spot']
    crude_rsi = st.session_state['last_valid_data']['crude_rsi']
    crude_ema9 = st.session_state['last_valid_data']['crude_ema9']

    # 📈 १. निफ्टी ऑप्टिमाइझ फेचिंग
    if (not is_weekend) and (datetime_time(9, 15) <= current_time <= datetime_time(15, 30)):
        try:
            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
            if ltp_res and ltp_res.get('status'): live_spot = float(ltp_res['data']['ltp'])
            
            # ५ मिनिटांतून फक्त एकदाच हिस्टोरिकल डेटा मागवणे (अडथळा रोखण्यासाठी)
            if st.session_state['nifty_df_cache'] is None or (ist_now - st.session_state['last_fetch_time']['NIFTY']).total_seconds() > 300:
                from_time = (ist_now - timedelta(minutes=400)).strftime("%Y-%m-%d %H:%M")
                res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                if res and res.get('data'):
                    st.session_state['nifty_df_cache'] = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                    st.session_state['last_fetch_time']['NIFTY'] = ist_now
            
            if st.session_state['nifty_df_cache'] is not None:
                rsi_v, ema9 = process_indicators(st.session_state['nifty_df_cache'], live_spot)
        except: pass

    # 🛢️ २. क्रूड ऑईल रात्रीच्या टेस्टिंगसाठी ऑप्टिमाइझ फेचिंग
    if (not is_weekend) and (datetime_time(9, 0) <= current_time <= datetime_time(23, 30)):
        try:
            crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294")
            if crude_ltp_res and crude_ltp_res.get('status'): crude_spot = float(crude_ltp_res['data']['ltp'])
            
            if st.session_state['crude_df_cache'] is None or (ist_now - st.session_state['last_fetch_time']['CRUDE']).total_seconds() > 300:
                from_time = (ist_now - timedelta(minutes=500)).strftime("%Y-%m-%d %H:%M")
                res_c = smartApi.getCandleData({"exchange": "MCX", "symboltoken": "255294", "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                if res_c and res_c.get('data'):
                    st.session_state['crude_df_cache'] = pd.DataFrame(res_c['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                    st.session_state['last_fetch_time']['CRUDE'] = ist_now
                    
            if st.session_state['crude_df_cache'] is not None:
                crude_rsi, crude_ema9 = process_indicators(st.session_state['crude_df_cache'], crude_spot)
        except: pass

    st.session_state['last_valid_data'].update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'crude_spot': crude_spot, 'crude_rsi': crude_rsi, 'crude_ema9': crude_ema9})

    # UI कार्ड्स डिस्प्ले
    setup = "Major Rejection" if rsi_v < 30 else "Pullback"
    c_setup = "Day High/Low" if crude_rsi > 55 else "Pullback"
    tab_nifty, tab_crude = st.tabs(["📈 NIFTY 50", "🛢️ CRUDEOIL"])
    t_map = lambda s: '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s=="PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
    s_active = lambda act, s_name: "background:#00e67620;border:1px solid #00e676;color:#00e676;" if act == s_name else "background:#111422;opacity:0.3;color:#8f96a3;"
    
    with tab_nifty:
        r_st = "PASS" if rsi_v < 30 else "FAIL"
        e_st = "PASS" if live_spot > ema9 else "FAIL"
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
            <div style="background:#111422; padding:12px; border-radius:10px; font-size:12px; border: 1px solid #1c2136; line-height:1.6;">
                <div>1. Pinpoint RSI <b>({rsi_v:.2f})</b>: {t_map(r_st)}</div>
                <div>2. Institutional 9 EMA: {t_map(e_st)}</div>
            </div>
        </div>"""
        components.html(dhan_card_n, height=260, scrolling=False)

    with tab_crude:
        cr_st = "PASS" if crude_rsi > 55 else "FAIL"
        ce_st = "PASS" if crude_spot > crude_ema9 else "FAIL"
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
            <div style="background:#111422; padding:15px; border-radius:10px; font-size:12px; border:1px solid #1c2136; line-height:1.6;">
                <div>1. Pinpoint RSI <b>({crude_rsi:.2f})</b>: {t_map(cr_st)}</div>
                <div>2. Institutional 9 EMA: {t_map(ce_st)}</div>
            </div>
        </div>"""
        components.html(dhan_card_c, height=260, scrolling=False)

    time.sleep(2)
    st.rerun()
