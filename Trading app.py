# ==============================================================================
# MASTER BLUEPRINT V23 — ZERO-LAG 1-SECOND INSTANT STREAMING ENGINE (LIVE SCALPER)
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Zero-Lag Algo Terminal", page_icon="⚡", layout="centered")

# मोबाईलसाठी भयंकर कडक आणि सुपर-फास्ट डिजिटल लेआउट
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

# MEMORY STATE HARD LOCKS
if 'master_unlocked' not in st.session_state: st.session_state['master_unlocked'] = False
if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 MASTER APP SECURITY")
input_password = st.sidebar.text_input("Master Password", type="password", key="saved_master_pass")

if input_password == "Roshan@715": st.session_state['master_unlocked'] = True
else: st.session_state['master_unlocked'] = False

if st.session_state['master_unlocked']:
    st.title("🚀 ZERO-LAG SATELLITE")
    
    st.sidebar.subheader("🔌 BROKER CONNECTION")
    with st.sidebar.form("login_form"):
        CID = st.text_input("Client ID", value="R990942", key="saved_cid").strip()
        AKEY = st.text_input("SmartAPI Key", type="password", key="saved_akey").strip()
        PIN = st.text_input("4-Digit MPIN", type="password", max_chars=4, key="saved_pin").strip()
        TKEY = st.text_input("TOTP Key/Seed", type="password", key="saved_tkey").strip()
        btn_connect = st.form_submit_button("CONNECT LIVE BROKER")

    if btn_connect:
        try:
            totp_code = pyotp.TOTP(TKEY).now()
            smartApi = SmartConnect(api_key=AKEY, timeout=10)
            session = smartApi.generateSession(CID, PIN, totp_code)
            if session.get('status'):
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 Connected!")
            else:
                st.sidebar.error(f"🛑 {session.get('message', 'Failed')}")
                st.session_state['is_connected'] = False
        except Exception as e:
            st.sidebar.error(f"🛑 Error: {str(e)}")
            st.session_state['is_connected'] = False

    # INSTANT TICK REFRESH ENGINE (1-Second Instant Pipeline)
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        try:
            # १. थेट चालू सेकंदाचा लास्ट ट्रेडेड प्राईस (LTP) ओढणे
            ltp_res = smartApi.getLTP("NSE", "NIFTY", "99926000")
            
            # २. बॅकएंड मॅथसाठी मागील कॅन्डल डेटा
            res = smartApi.getCandleData({
                "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                "fromdate": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 09:15"),
                "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            
            if ltp_res and ltp_res.get('status') and res and res.get('status'):
                live_p = float(ltp_res['data']['ltp']) # चालू सेकंदाचा जिवंत भाव!
                
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                delta = df['close'].diff()
                df['RSI'] = 100 - (100 / (1 + ((delta.where(delta > 0, 0)).rolling(14).mean() / (-delta.where(delta < 0, 0)).rolling(14).mean())))
                
                last_row = df.iloc[-1]
                rsi_v, ema_v, vol_v = last_row['RSI'], last_row['9_EMA'], last_row['volume']
                is_vol_tower = (vol_v >= 1.5 * df.iloc[-6:-1]['volume'].mean())
                
                # --- मुख्य स्क्रीन डिजिटल सिग्नल्स ---
                st.subheader(f"⚡ NIFTY 50 LIVE TICK: ₹ {live_p:.2f}")
                st.caption(f"⏱️ Instant Stream Refresh Time: {datetime.now().strftime('%H:%M:%S')}")
                
                if is_vol_tower and abs(live_p - ema_v) <= 10.0 and abs(live_p - last_row['open']) <= 20.0:
                    if rsi_v > 60.0: st.success(f"🟢 **CALL TRIGGERED** | Target: {live_p + 20.0:.1f} | SL: Last Swing Low")
                    elif rsi_v < 40.0: st.error(f"🔴 **PUT TRIGGERED** | Target: {live_p - 20.0:.1f} | SL: Last Swing High")
                else:
                    st.info("⏳ **ALGO SCANNING LIVE MARKETS...** PRICE ACTION NORMAL.")
                
                # कडक मोबाईल ग्रिड लेआउट
                col1, col2 = st.columns(2)
                col1.metric("INSTANT RSI (5-Min)", f"{rsi_v:.1f}", delta="BULLISH" if rsi_v > 60 else ("BEARISH" if rsi_v < 40 else "NEUTRAL"))
                col2.metric("9 EMA CORRIDOR", f"₹ {ema_v:.1f}", delta=f"{live_p - ema_v:.1f}")
                
                col3, col4 = st.columns(2)
                col3.metric("LAST CANDLE VOLUME", f"{vol_v:,}")
                col4.metric("VOL TOWER STATUS", "1.5x ACTIVE 🚀" if is_vol_tower else "NORMAL")
            else:
                st.warning("⏳ Refreshing Instant Nifty Tick Stream...")
        except Exception as e:
            st.sidebar.markdown(f"⏳ Syncing Stream... ({str(e)})")
            
        # १ सेकंदाचा अल्ट्रा-फास्ट रिफ्रेश लूप!
        time.sleep(1)
        st.rerun()
    else:
        st.info("⏳ Please connect your Angel One Broker Engine from the sidebar to start live scanning.")
else:
    st.warning("🔒 SECURITY LOCK: Enter the correct Master Password to activate App Engine.")
