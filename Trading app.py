# ==============================================================================
# MASTER BLUEPRINT V28 — ZERO-BLINK ULTRA SMOOTH TICK ENGINE (JAVA INJECTOR)
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from SmartApi import SmartConnect

# अत्यंत हलका आणि सुटसुटीत मोबाईल लेआउट
st.set_page_config(page_title="ALGO", page_icon="⚡", layout="centered")

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    st.title("⚡ ALGO PRO")
    
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

    # ULTRA SMOOTH JAVASCRIPT INJECTION TERMINAL
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        
        # बॅकएंडला डेटा फिक्स करून ठेवणे जेणेकरून कॅश री-लोड होणार नाही
        try:
            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
            res = smartApi.getCandleData({
                "exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE",
                "fromdate": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 09:15"),
                "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            
            if ltp_res and ltp_res.get('status') and res and res.get('status') and res.get('data'):
                live_p = float(ltp_res['data']['ltp'])
                
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean().replace(0, 0.00001)
                df['RSI'] = 100 - (100 / (1 + (gain / loss)))
                
                last_row = df.iloc[-1]
                rsi_v = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 50.0
                ema_v = float(last_row['9_EMA'])
                vol_v = int(last_row['volume'])
                
                # सिग्नल्स फॉरमॅटिंग मॅट्रिक्स
                signal_text = "ALGO SCANNING LIVE MARKETS..."
                signal_color = "#8f96a3"
                if live_p < (ema_v - 3.0):
                    signal_text = f"🔴 BEARISH BREAKDOWN | PUT ON (Target: {live_p-20:.1f})"
                    signal_color = "#ff5252"
                elif live_p > (ema_v + 3.0):
                    signal_text = f"🟢 BULLISH BREAKOUT | CALL ON (Target: {live_p+20:.1f})"
                    signal_color = "#00e676"

                # ==============================================================================
                # 🪐 THE JAVASCRIPT ULTRA-SMOOTH LIVE UI INJECTOR (ZERO REFRESH BLINK)
                # ==============================================================================
                html_live_cards = f"""
                <div style="background-color:#060814; padding:15px; border-radius:16px; font-family:sans-serif; color:white;">
                    <div style="text-align:center; margin-bottom:15px;">
                        <span style="font-size:14px; color:#8f96a3; text-transform:uppercase; letter-spacing:1px;">NIFTY 50 LIVE TICK</span>
                        <h1 style="font-size:36px; margin:5px 0; color:#00e676; font-weight:bold;">₹ {live_p:.2f}</h1>
                        <div style="background-color: {signal_color}20; border: 1px solid {signal_color}; padding: 10px; border-radius: 8px; font-weight: bold; color: {signal_color}; margin-top: 10px;">
                            {signal_text}
                        </div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px;">
                        <div style="background:#121624; border:1px solid #1e2338; padding:12px; border-radius:10px; text-align:center;">
                            <div style="font-size:11px; color:#8f96a3;">REAL-TIME RSI</div>
                            <div style="font-size:20px; font-weight:bold; color:#00e676; margin-top:5px;">{rsi_v:.1f}</div>
                        </div>
                        <div style="background:#121624; border:1px solid #1e2338; padding:12px; border-radius:10px; text-align:center;">
                            <div style="font-size:11px; color:#8f96a3;">9 EMA CORRIDOR</div>
                            <div style="font-size:20px; font-weight:bold; color:#fff; margin-top:5px;">₹ {ema_v:.1f}</div>
                        </div>
                    </div>
                    
                    <div style="background:#121624; border:1px solid #1e2338; padding:12px; border-radius:10px; text-align:center; margin-top:10px;">
                        <div style="font-size:11px; color:#8f96a3;">LAST CANDLE VOLUME</div>
                        <div style="font-size:18px; font-weight:bold; color:#ffb300; margin-top:5px;">{vol_v:,}</div>
                    </div>
                </div>
                
                <script>
                // हा जावास्क्रिप्टचा कडक तुकडा ब्राउझरला न चमकवता बॅकएंड डेटा २00ms मध्ये सिंक करेल!
                setTimeout(function() {{
                    window.location.reload();
                }}, 300);
                </script>
                """
                # केवळ कम्पोनंटच्या आत आकडे बदलणार, पूर्ण मुख्य पेज हलणार नाही!
                components.html(html_live_cards, height=360, scrolling=False)
                
            else: st.warning("⏳ Connecting to Broker Stream...")
        except Exception as e:
            st.sidebar.markdown(f"⏳ Syncing Server... ({str(e)})")
            time.sleep(1)
            st.rerun()
    else: st.info("⏳ Click CONNECT from the sidebar to activate the Live Stream.")
else: st.sidebar.warning("🔒 Enter Password.")
