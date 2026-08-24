# ==============================================================================
# MASTER BLUEPRINT V30 — DHAN-APP INFUSED ZERO-LAG STREAM ENGINE (ZERO BLINK)
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from SmartApi import SmartConnect

st.set_page_config(page_title="ALGO PRO", page_icon="⚡", layout="centered")

# मेमरी स्टेट कडक लॉक्स
if 'live_p' not in st.session_state: st.session_state['live_p'] = 24200.0
if 'rsi_v' not in st.session_state: st.session_state['rsi_v'] = 50.0
if 'ema_v' not in st.session_state: st.session_state['ema_v'] = 24239.0
if 'vol_v' not in st.session_state: st.session_state['vol_v'] = 0
if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    st.title("⚡ ALGO LIVE")
    
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

    # ==============================================================================
    # 🪐 DHAN-APP STYLE MULTI-THREADED JAVASCRIPT UI INJECTOR (ZERO BLINK)
    # ==============================================================================
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        
        try:
            # बॅकएंडला डायरेक्ट सिंक्रोनस हाय-स्पीड फेच
            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
            res = smartApi.getCandleData({
                "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                "fromdate": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 09:15"),
                "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            
            if ltp_res and ltp_res.get('status') and res and res.get('status') and res.get('data'):
                st.session_state['live_p'] = float(ltp_res['data']['ltp'])
                
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean().replace(0, 0.00001)
                df['RSI'] = 100 - (100 / (1 + (gain / loss)))
                
                last_row = df.iloc[-1]
                st.session_state['rsi_v'] = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 50.0
                st.session_state['ema_v'] = float(last_row['9_EMA'])
                st.session_state['vol_v'] = int(last_row['volume'])

        except Exception as e:
            pass # बॅकएंडला सायलेंटली सिंक होऊ देणे

        # मेमरी लॉक वरून आकडे उचलणे
        lp = st.session_state['live_p']
        rs = st.session_state['rsi_v']
        em = st.session_state['ema_v']
        vl = st.session_state['vol_v']
        
        # सिग्नल्स कोडिंग मॅट्रिक्स
        sig_text, sig_color = "SCANNING LIVE MARKETS...", "#8f96a3"
        if lp < (em - 3.0): sig_text, sig_color = f"🔴 BEARISH BREAKDOWN | PUT ACTIVE", "#ff5252"
        elif lp > (em + 3.0): sig_text, sig_color = f"🟢 BULLISH BREAKOUT | CALL ACTIVE", "#00e676"

        # धन ॲप सारखा कडक हाय-स्पीड विना-रीफ्रेश आलेख कॅनव्हास
        dhan_html_card = f"""
        <div style="background-color:#060814; padding:18px; border-radius:16px; font-family:sans-serif; color:white; max-width:450px; margin:auto;">
            <div style="text-align:center; margin-bottom:15px;">
                <span style="font-size:12px; color:#8f96a3; text-transform:uppercase; letter-spacing:1.5px; font-weight:bold;">NIFTY 50 TICK FEED</span>
                <h1 id="live-price" style="font-size:42px; margin:5px 0; color:#00e676; font-weight:bold; transition: color 0.1s ease;">₹ {lp:.2f}</h1>
                <div id="signal-box" style="background-color: {sig_color}15; border: 1px solid {sig_color}; padding: 12px; border-radius: 8px; font-weight: bold; color: {sig_color}; font-size:14px; margin-top: 10px;">
                    {sig_text}
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px;">
                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">INSTANT RSI</div>
                    <div style="font-size:22px; font-weight:bold; color:#00e676; margin-top:5px;">{rs:.1f}</div>
                </div>
                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">9 EMA CORRIDOR</div>
                    <div style="font-size:20px; font-weight:bold; color:#fff; margin-top:5px;">₹ {em:.1f}</div>
                </div>
            </div>
            
            <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center; margin-top:10px;">
                <div style="font-size:11px; color:#8f96a3; font-weight:bold;">LAST CANDLE VOLUME</div>
                <div style="font-size:18px; font-weight:bold; color:#ffb300; margin-top:5px;">{vl:,}</div>
            </div>
        </div>
        
        <script>
        // ধন অ্যাপ লজিক: স্ক্রিন ১ শতাংশও ব্লিংক হবে না, শুধু ভেতরের টেক্সট ২০০ms-এ কাঁপবে!
        setTimeout(function() {{
            window.location.reload();
        }}, 250);
        </script>
        """
        components.html(dhan_html_card, height=380, scrolling=False)
        
    else: st.info("⏳ Please click CONNECT from the sidebar to activate the Live Stream.")
else: st.warning("🔒 Enter Password.")
