# ==============================================================================
# MASTER BLUEPRINT V27 — INSTANT SYNCHRONOUS TICK SCALPER (ZERO FREEZE LOCK)
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
    .main .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
    div[data-testid="stMetric"] {
        background-color: #0f121d !important;
        border: 1px solid #222634 !important;
        border-radius: 12px !important;
        padding: 12px !important;
        text-align: center !important;
    }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: bold !important; color: #00e676 !important; }
    div[data-testid="stMetricLabel"] { font-size: 13px !important; color: #8f96a3 !important; }
    </style>
""", unsafe_allow_html=True)

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    st.title("⚡ ALGO")
    
    st.sidebar.subheader("🔌 CONNECT")
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
            smartApi = SmartConnect(api_key=AKEY, timeout=10)
            session = smartApi.generateSession(CID, PIN, totp_code)
            if session.get('status'):
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 Active!")
            else: st.sidebar.error(f"🛑 {session.get('message')}")
        except Exception as e: st.sidebar.error(f"🛑 Login Error: {str(e)}")

    # DIRECT SYNCHRONOUS REAL-TIME STREAM PIPELINE
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        try:
            # क्रैश-प्रूफ डायरेक्ट सिंक्रोनस एक्सचेंज डेटा फेच
            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
            
            res = smartApi.getCandleData({
                "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                "fromdate": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 09:15"),
                "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            
            if ltp_res and ltp_res.get('status') and res and res.get('status') and res.get('data'):
                # थेट चालू सेकंदाचा रिअल-टाइम जिवंत भाव कॅप्चर करणे!
                live_p = float(ltp_res['data']['ltp'])
                
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                delta = df['close'].diff()
                df['RSI'] = 100 - (100 / (1 + ((delta.where(delta > 0, 0)).rolling(14).mean() / (-delta.where(delta < 0, 0)).rolling(14).mean())))
                df['RSI'] = df['RSI'].fillna(50.0).replace([np.inf, -np.inf], 50.0)
                
                last_row = df.iloc[-1]
                rsi_v, ema_v, vol_v = float(last_row['RSI']), float(last_row['9_EMA']), int(last_row['volume'])
                is_vol_tower = (vol_v >= 1.5 * df.iloc[-6:-1]['volume'].mean())
                
                # मुख्य डिस्प्ले: आता २४,२०० वर फ्रीझ होणार नाही!
                st.subheader(f"🔥 NIFTY 50 LIVE: ₹ {live_p:.2f}")
                st.caption(f"⏱️ Instant Sync Time: {datetime.now().strftime('%H:%M:%S.%f')[:-4]}")
                
                # --- 🎯 सुधारित प्रॅक्टिकल मार्केट स्ट्रक्चर सिग्नल्स ---
                # २४,१७२ वर मार्केट गेल्यास कडक पुट दाखवेल आणि २४,१९३ वर येताच सिग्नल्स अचूक री-मॅप करेल!
                if live_p < (ema_v - 3.0):
                    st.error(f"🔴 **BEARISH MOMENTUM ACTIVE** | PUT STRATEGY ON")
                    st.info(f"🎯 Target Corridor: Below {live_p - 20.0:.1f} | 🛡️ SL Swings: {live_p + 15.0:.1f}")
                elif live_p > (ema_v + 3.0):
                    st.success(f"🟢 **BULLISH MOMENTUM ACTIVE** | CALL STRATEGY ON")
                    st.info(f"🎯 Target Corridor: Above {live_p + 20.0:.1f} | 🛡️ SL Swings: {live_p - 15.0:.1f}")
                else:
                    st.info("⏳ **ALGO SCALPING CHANNELS...** Consolidating near 9 EMA Corridor.")
                
                col1, col2 = st.columns(2)
                col1.metric("INSTANT RSI (5-Min)", f"{rsi_v:.1f}", delta="BEARISH" if live_p < ema_v else "BULLISH")
                col2.metric("9 EMA CORRIDOR", f"₹ {ema_v:.1f}", delta=f"{live_p - ema_v:.1f}")
                
                col3, col4 = st.columns(2)
                col3.metric("LAST CANDLE VOLUME", f"{vol_v:,}")
                col4.metric("VOL TOWER STATUS", "1.5x ACTIVE 🚀" if is_vol_tower else "NORMAL")
            else:
                st.warning("⏳ Synchronizing Real-Time Nifty Stream...")
        except Exception as e:
            st.sidebar.markdown(f"⏳ Stream Syncing... ({str(e)})")
            
        # ०.२ सेकंदाचा कडक हाय-स्पीड रिफ्रेश लूप (No Thread Lock!)
        time.sleep(0.2)
        st.rerun()
    else:
        st.info("⏳ Click CONNECT from the sidebar to activate the Live Stream.")
else:
    st.sidebar.warning("🔒 Enter Password.")
