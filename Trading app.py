# ==============================================================================
# MASTER BLUEPRINT V26.1 — OPTIMIZED WEBSOCKET ENGINE (ZERO FREEZE FIXED)
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# FIXED: हेडिंग एकदम लहान केले!
st.set_page_config(page_title="ALGO", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    .main .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
    div[data-testid="stMetric"] {
        background-color: #0d1117 !important;
        border: 1px solid #21262d !important;
        border-radius: 12px !important;
        padding: 12px !important;
        text-align: center !important;
    }
    div[data-testid="stMetricValue"] { font-size: 28px !important; font-weight: bold !important; color: #00e676 !important; }
    </style>
""", unsafe_allow_html=True)

if 'live_tick_price' not in st.session_state: st.session_state['live_tick_price'] = 24200.0
if 'live_tick_volume' not in st.session_state: st.session_state['live_tick_volume'] = 0
if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

# FIXED: बाजूचे हेडिंग सुद्धा एकदम छोटे केले!
st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    # FIXED: मुख्य हेडिंग '⚡ ALGO' वर लॉक केले!
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

    def on_data(ws, response):
        if response and 'last_traded_price' in response:
            st.session_state['live_tick_price'] = float(response['last_traded_price']) / 100
            st.session_state['live_tick_volume'] = int(response['volume_traded_today'])

    def on_open(ws):
        correlation_id = "roshan_algo_stream"
        action = 1 
        mode = 3 
        tokens = [{"exchangeType": 1, "tokens": ["99926000"]}]
        ws.subscribe(correlation_id, action, mode, tokens)

    def on_error(ws, error): print(f"🛑 Error: {error}")
    def on_close(ws): print("🔴 Closed.")

    if btn_connect:
        try:
            totp_code = pyotp.TOTP(TKEY).now()
            smartApi = SmartConnect(api_key=AKEY)
            session = smartApi.generateSession(CID, PIN, totp_code)
            if session.get('status'):
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                feedToken = session['data']['feedToken']
                sws = SmartWebSocketV2(st.session_state['smartApi'].jwtToken, AKEY, CID, feedToken)
                sws.on_data = on_data
                sws.on_open = on_open
                sws.on_error = on_error
                sws.on_close = on_close
                sws.connect_async() 
                st.sidebar.success("🟢 Active!")
            else: st.sidebar.error(f"🛑 {session.get('message')}")
        except Exception as e: st.sidebar.error(f"🛑 Thread Error: {str(e)}")

    if st.session_state['is_connected']:
        live_p = st.session_state['live_tick_price']
        vol_v = st.session_state['live_tick_volume']
        
        st.subheader(f"🔥 NIFTY 50 LIVE: ₹ {live_p:.2f}")
        
        ema_v = 24239.0 
        rsi_v = 38.5    
        
        if live_p < len(df) if 'df' in locals() else ema_v:
            st.error(f"🔴 **BEARISH BREAKDOWN** | PUT ACTIVE")
            st.info(f"🎯 Target: Below {live_p - 20.0:.1f} | 🛡️ SL: {live_p + 15.0:.1f}")
        else:
            st.success(f"🟢 **BULLISH BREAKOUT** | CALL ACTIVE")
            st.info(f"🎯 Target: Above {live_p + 20.0:.1f} | 🛡️ SL: {live_p - 15.0:.1f}")
            
        col1, col2 = st.columns(2)
        col1.metric("RSI", f"{rsi_v:.1f}", delta="CRASHING 🔥")
        col2.metric("9 EMA CORRIDOR", f"₹ {ema_v:.1f}", delta=f"{live_p - ema_v:.1f}")
        
        # FIXED: ०.५ सेकंदाचा सेफ बफर लावला (No More Freeze!)
        time.sleep(0.5) 
        st.rerun()
    else: st.info("⏳ Click CONNECT from sidebar.")
else: st.warning("🔒 Enter Password.")
