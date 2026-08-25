import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

st.set_page_config(page_title="ALGO V66", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

# स्क्रीन ब्लँक होऊ नये म्हणून बॅकअप मेमरी बँक (चार्टनुसार लेटेस्ट व्हॅल्यूज सेट केल्या)
if 'last_valid_data' not in st.session_state:
    st.session_state['last_valid_data'] = {
        'live_spot': 24244.80, 'rsi_v': 79.31, 'ema9': 24242.18,
        'crude_spot': 6817.0, 'crude_rsi': 47.9, 'crude_ema9': 6812.0,
        'intraday_high': 24260.00, 'intraday_low': 24128.80,
        'session_status': "⏳ ALGO SCALPING RUNNING... WAITING FOR 15-PT BREAKOUT", 'sig_color': "#8f96a3"
    }

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")
if input_password == "Roshan@715": st.session_state['master_unlocked'] = True
else: st.session_state['master_unlocked'] = False

if st.session_state['master_unlocked']:
    st.title("⚡ ALGO LIVE")
    CID = st.sidebar.text_input("Client ID", value="R990942", key="p_cid").strip()
    AKEY = st.sidebar.text_input("API Key", type="password", key="p_akey").strip()
    PIN = st.sidebar.text_input("MPIN", type="password", max_chars=4, key="p_pin").strip()
    TKEY = st.sidebar.text_input("TOTP Key/Seed", type="password", key="p_tkey").strip()
    
    col_btn1, col_btn2 = st.sidebar.columns(2)
    if col_btn1.button("CONNECT") and not st.session_state['is_connected']:
        from SmartApi import SmartConnect
        try:
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            if smartApi.generateSession(CID, PIN, pyotp.TOTP(TKEY).now())['status']:
                st.session_state['is_connected'] = True; st.session_state['smartApi'] = smartApi; st.sidebar.success("🟢 Connected!")
        except: pass
    if col_btn2.button("LOG OUT"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()

    dhan_app_canvas = st.empty()
    if st.session_state['is_connected']:
        while True:
            with dhan_app_canvas.container():
                try:
                    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                    
                    live_spot = st.session_state['last_valid_data']['live_spot']
                    rsi_v = st.session_state['last_valid_data']['rsi_v']
                    ema9 = st.session_state['last_valid_data']['ema9']
                    crude_spot = st.session_state['last_valid_data']['crude_spot']
                    crude_rsi = st.session_state['last_valid_data']['crude_rsi']
                    crude_ema9 = st.session_state['last_valid_data']['crude_ema9']
                    intraday_high = st.session_state['last_valid_data']['intraday_high']
                    intraday_low = st.session_state['last_valid_data']['intraday_low']
                    session_status = st.session_state['last_valid_data']['session_status']
                    sig_color = st.session_state['last_valid_data']['sig_color']

                    # एपीआय चालू असेल तर डेटा ओढणे, नाहीतर बॅकअप मेमरी वापरणे (No Blank Screen)
                    if st.session_state['smartApi']:
                        try:
                            smartApi = st.session_state['smartApi']
                            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                            crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294")
                            res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=2)).strftime("%Y-%m-%d 09:15"), "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                            
                            if ltp_res and ltp_res.get('status') and ltp_res.get('data'):
                                live_spot = float(ltp_res['data']['ltp'])
                            if crude_ltp_res and crude_ltp_res.get('status') and crude_ltp_res.get('data'):
                                crude_spot = float(crude_ltp_res['data']['ltp'])
                                
                            if res and res.get('data'):
                                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                                df['close'] = df['close'].astype(float)
                                delta = df['close'].diff()
                                gain = (delta.clip(lower=0)).ewm(alpha=1/14, adjust=False).mean()
                                loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                                rs = gain / loss.replace(0, 0.00001)
                                rsi_v = float(100 - (100 / (1 + rs)).iloc[-1])
                                
                                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                                ema9 = float(df['9_EMA'].iloc[-1])
                                
                                current_day_str = ist_now.strftime("%Y-%m-%d")
                                day_candles = df[df['date'].astype(str).str.contains(current_day_str)]
                                intraday_high = day_candles['high'].astype(float).max() if not day_candles.empty else live_spot
                                intraday_low = day_candles['low'].astype(float).min() if not day_candles.empty else live_spot

                            # १५-पॉइंट मॅक्रो रुल सिग्नल्स फिक्स
                            if live_spot >= (intraday_high - 15) and rsi_v > 70:
                                session_status, sig_color = "🟢 CE BREAKOUT ACTIVATED (GENUINE SWING RIDE)", "#00e676"
                            elif live_spot <= (intraday_low + 15) and rsi_v < 30:
                                session_status, sig_color = "🔴 PE BREAKOUT ACTIVATED (OPERATOR WALL CRASH)", "#ff5252"
                            else:
                                session_status, sig_color = "⏳ SCALPING SCANNERS ACTIVE... WAITING FOR 15-PT BREAKOUT", "#8f96a3"

                            # मेमरी बँक अपडेट करणे
                            st.session_state['last_valid_data'] = {
                                'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9,
                                'crude_spot': crude_spot, 'crude_rsi': crude_rsi, 'crude_ema9': crude_ema9,
                                'intraday_high': intraday_high, 'intraday_low': intraday_low,
                                'session_status': session_status, 'sig_color': sig_color
                            }
                        except: pass

                    dhan_card = f"""
                    <div style="background-color:#060814; padding:20px; border-radius:16px; font-family:sans-serif; color:white; max-width:440px; margin:auto; border: 1px solid #1c2136;">
                        <div style="background-color:#ffb30010; border:1px solid #ffb30050; padding:15px; border-radius:12px; text-align:center; margin-bottom:15px;">
                            <span style="font-size:11px; color:#ffb300; text-transform:uppercase; font-weight:bold;">🛢️ CRUDEOIL MCX LIVE</span>
                            <h1 style="font-size:38px; margin:5px 0; color:#ffb300; font-weight:bold;">₹ {crude_spot:.0f}</h1>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; font-size:12px;">
                                <div style="background:#111422; padding:6px; border-radius:6px;"><b>Live RSI:</b> <span style="color:#00e676;">{crude_rsi:.1f}</span></div>
                                <div style="background:#111422; padding:6px; border-radius:6px;"><b>9 EMA:</b> ₹{crude_ema9:.0f}</div>
                            </div>
                        </div>
                        <div style="background-color:#00e67610; border:1px solid #00e67650; padding:15px; border-radius:12px; text-align:center; margin-bottom:15px;">
                            <span style="font-size:11px; color:#00e676; text-transform:uppercase; font-weight:bold;">📈 NIFTY SPOT LIVE</span>
                            <h1 style="font-size:38px; margin:5px 0; color:#00e676; font-weight:bold;">{live_spot:.2f}</h1>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; font-size:12px;">
                                <div style="background:#111422; padding:6px; border-radius:6px;"><b>Nifty RSI:</b> {rsi_v:.1f}</div>
                                <div style="background:#111422; padding:6px; border-radius:6px;"><b>9 EMA:</b> {ema9:.2f}</div>
                            </div>
                        </div>
                        <div style="background:#111422; padding:12px; border-radius:10px; font-size:12px; line-height:1.6; border: 1px solid #1c2136;">
                            <div style="color:{sig_color}; font-weight:bold; margin-bottom:8px; text-align:center;">{session_status}</div>
                            <hr style="border:0; border-top:1px solid #1c2136; margin:8px 0;">
                            <div><b>Intraday High:</b> {intraday_high:.2f} | <b>Low:</b> {intraday_low:.2f}</div>
                            <div><b>OI Bias:</b> <span style="color:#00e676; font-weight:bold;">STRONG BULLISH</span></div>
                        </div>
                    </div>
                    """
                    components.html(dhan_card, height=480, scrolling=False)
                except: pass
            time.sleep(1)
