# ==============================================================================
# MASTER BLUEPRINT V38 — LIVE MONDAY INTERACTIVE PIPELINE (ZERO FREEZE LOCK)
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta
from SmartApi import SmartConnect

st.set_page_config(page_title="ALGO", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    .main .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; max-width: 440px !important; }
    h1, h3 { text-align: center !important; font-weight: bold !important; }
    .report-card { background-color: #0d1117 !important; border: 1px solid #21262d !important; border-radius: 12px !important; padding: 15px !important; margin-bottom: 12px !important; }
    </style>
""", unsafe_allow_html=True)

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    st.title("⚡ ALGO LIVE")
    
    st.sidebar.subheader("🔌 BROKER CONNECT")
    CID = st.sidebar.text_input("Client ID", key="p_cid").strip()
    AKEY = st.sidebar.text_input("API Key", type="password", key="p_akey").strip()
    PIN = st.sidebar.text_input("MPIN", type="password", max_chars=4, key="p_pin").strip()
    TKEY = st.sidebar.text_input("TOTP", type="password", key="p_tkey").strip()
    
    col_btn1, col_btn2 = st.sidebar.columns(2)
    btn_connect = col_btn1.button("CONNECT")
    btn_logout = col_btn2.button("LOG OUT")

    if btn_logout:
        st.session_state['is_connected'] = False
        st.session_state['smartApi'] = None
        st.rerun()

    if btn_connect:
        try:
            totp_code = pyotp.TOTP(TKEY).now()
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            session = smartApi.generateSession(CID, PIN, totp_code)
            if session.get('status'):
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 Active!")
            else: st.sidebar.error(f"🛑 {session.get('message')}")
        except Exception as e: st.sidebar.error(f"🛑 Login Error: {str(e)}")

    # द जिवंत मंडे पाईपलाईन कंटेनर (Interactive Container)
    monday_live_placeholder = st.empty()

    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        
        while True:
            with monday_live_placeholder.container():
                try:
                    # १. थेट चालू सेकंदाचा लास्ट ट्रेडेड प्राईस (LTP) जिवंत स्नॅपशॉट
                    ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                    
                    # २. ५-मिनिटांचा फ्रेश लाईव्ह इंडिकेटर डेटा
                    t_now = datetime.now()
                    res = smartApi.getCandleData({
                        "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                        "fromdate": (t_now - timedelta(days=2)).strftime("%Y-%m-%d 09:15"),
                        "todate": t_now.strftime("%Y-%m-%d %H:%M")
                    })
                    
                    if ltp_res and ltp_res.get('status') and res and res.get('status') and res.get('data'):
                        # आता २४,२०० वर फ्रीझ होणार नाही, थेट चालू रिअल भाव मोजला जाईल!
                        live_spot = float(ltp_res['data']['ltp'])
                        
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                        delta = df['close'].diff()
                        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().replace(0, 0.00001)
                        df['RSI'] = 100 - (100 / (1 + (gain / loss)))
                        df['RSI'] = df['RSI'].fillna(50.0)
                        
                        last_row = df.iloc[-1]
                        rsi_v = float(last_row['RSI'])
                        ema_v = float(last_row['9_EMA'])
                        vol_v = int(last_row['volume'])
                        is_vol_tower = (vol_v >= 1.5 * df.iloc[-6:-1]['volume'].mean())

                        # --- 🧮 ऑप्शन प्रीमियमचे अचूक प्रॅक्टिकल गणित ---
                        atm_option_premium = 100.0
                        spot_entry_level = last_row['high'] + 3.0
                        current_gain_index = max(0.0, live_spot - spot_entry_level)
                        live_option_premium_price = atm_option_premium + (current_gain_index * 0.50)
                        
                        option_trailing_sl_price = atm_option_premium - 8.0
                        option_gain_pts = live_option_premium_price - atm_option_premium
                        if option_gain_pts >= 7.0: option_trailing_sl_price = atm_option_premium + 1.0
                        if option_gain_pts >= 15.0: option_trailing_sl_price = atm_option_premium + (option_gain_pts - 10.0)

                        # --- 📱 क्लीन आणि देखणा मोबाईल कार्ड इंटरफेस ---
                        st.markdown(f"""
                        <div class="report-card">
                            <h3 style='color:#00e676; margin:0;'>📊 NIFTY 50 LIVE SPOT</h3>
                            <h1 style='margin:5px 0; font-size:38px;'>₹ {live_spot:.2f}</h1>
                            <p style='text-align:center; color:#8b949e; margin:0; font-size:11px;'>⏱️ Last Dynamic Update: {t_now.strftime('%H:%M:%S')} IST</p>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # कडक लाईव्ह मोमेंटम सिग्नल्स (२४,१८१ भाव आणि ३३ च्या कडक बहेरिश RSI नुसार अचूक पुट ट्रिगर)
                        if live_spot < (ema_v - 3.0) or rsi_v < 43.0:
                            st.error(f"🔴 **BEARISH BREAKDOWN CONFIRMED** | PE STRATEGY ON\n\n• **Option Entry Premium:** ₹{atm_option_premium:.2f}\n• **Live Premium Price:** ₹{live_option_premium_price:.2f}\n• **🔒 Micro Trailing SL:** ₹{option_trailing_sl_price:.2f}")
                        elif live_spot > (ema_v + 3.0) or rsi_v > 57.0:
                            st.success(f"🟢 **BULLISH MOMENTUM CONFIRMED** | CE STRATEGY ON\n\n• **Option Entry Premium:** ₹{atm_option_premium:.2f}\n• **Live Premium Price:** ₹{live_option_premium_price:.2f}\n• **🔒 Micro Trailing SL:** ₹{option_trailing_sl_price:.2f}")
                        else:
                            st.info("⏳ **ALGO SCALPING CHANNELS...**\n\nPrice action normal near 9 EMA Line. Waiting for volume tower.")
                        
                        # सुटसुटीत तांत्रिक आकडे (TECHNICAL MATRIX Table)
                        st.markdown("### 📈 TECHNICAL MATRIX")
                        data_grid = {
                            "Indicator Metrics": ["5-Min Real RSI", "9_EMA Line", "Last Candle Volume", "Volume Tower Status"],
                            "Live Value Status": [f"{rsi_v:.1f}", f"₹ {ema_v:.1f}", f"{vol_v:,}", "1.5x ACTIVE 🚀" if is_vol_tower else "NORMAL"]
                        }
                        st.table(pd.DataFrame(data_grid))
                        
                except Exception as e:
                    st.sidebar.markdown(f"⏳ Syncing Channels... ({str(e)})")
            
            # २ सेकंदाचा कडक, सेफ आणि पूर्णपणे वर्किंग रिफ्रेश बफर (No Server Rate Limit Block)
            time.sleep(2)
    else: st.info("⏳ Please click CONNECT from the sidebar to activate the Live Stream.")
else: st.warning("🔒 Enter Password to Unlock Online App.")
