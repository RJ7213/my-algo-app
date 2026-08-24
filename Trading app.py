# ==============================================================================
# MASTER BLUEPRINT V65 — THE LIVE CRUDE OIL MCX TURBO ENGINE (NIGHT TEST READY)
# ==============================================================================
import time, pyotp, pandas as pd, numpy as np, streamlit as st, streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

st.set_page_config(page_title="ALGO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715": st.session_state['master_unlocked'] = True
else: st.session_state['master_unlocked'] = False

if st.session_state['master_unlocked']:
    st.title("⚡ ALGO LIVE")
    st.sidebar.subheader("🔌 BROKER CONNECTION")
    CID = st.sidebar.text_input("Client ID", value="R990942", key="p_cid").strip()
    AKEY = st.sidebar.text_input("API Key", type="password", key="p_akey").strip()
    PIN = st.sidebar.text_input("MPIN", type="password", max_chars=4, key="p_pin").strip()
    TKEY = st.sidebar.text_input("TOTP Key/Seed", type="password", key="p_tkey").strip()
    
    col_btn1, col_btn2 = st.sidebar.columns(2)
    btn_connect = col_btn1.button("CONNECT")
    if col_btn2.button("LOG OUT"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()

    if btn_connect and not st.session_state['is_connected']:
        from SmartApi import SmartConnect
        try:
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            if smartApi.generateSession(CID, PIN, pyotp.TOTP(TKEY).now())['status']:
                st.session_state['is_connected'] = True; st.session_state['smartApi'] = smartApi; st.sidebar.success("🟢 Active!")
            else: st.sidebar.error("🛑 Login Failed.")
        except Exception as e: st.sidebar.error(f"🛑 Error: {str(e)}")

    dhan_app_canvas = st.empty()
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        while True:
            with dhan_app_canvas.container():
                try:
                    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                    
                    # --- 📊 १. निफ्टीचा हिस्टोरिकल डेटा (बंद मार्केट) ---
                    ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                    res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=3)).strftime("%Y-%m-%d 09:15"), "todate": ist_now.strftime("%Y-%m-%d 15:30")})
                    
                    # --- 🛢️ २. क्रूड ऑइलचा जिवंत लाईव्ह डेटा (चालू मार्केट - MCX) ---
                    # MCX क्रूड ऑइल चालू फ्युचर्स कॉन्ट्रॅक्ट सिंकिंग
                    crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294") 
                    crude_res = smartApi.getCandleData({"exchange": "MCX", "symboltoken": "255294", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=2)).strftime("%Y-%m-%d 09:00"), "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                    
                    if ltp_res['status'] and res['status'] and res['data'] and crude_ltp_res['status'] and crude_res['data']:
                        # निफ्टी कॅल्क्युलेशन
                        live_spot = float(ltp_res['data']['ltp'])
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume']).tail(30).reset_index(drop=True)
                        df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                        df['20_EMA'] = df['close'].ewm(span=20, adjust=False).mean()
                        delta = df['close'].diff()
                        df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).ewm(com=13, adjust=False).mean() / delta.clip(upper=0).abs().ewm(com=13, adjust=False).mean().replace(0, 0.00001))))
                        last_row = df.iloc[-1]
                        rsi_v = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 33.0
                        ema9, ema20 = float(last_row['9_EMA']), float(last_row['20_EMA'])

                        # क्रूड ऑइल लाईव्ह कॅल्क्युलेशन 🛢️
                        crude_spot = float(crude_ltp_res['data']['ltp'])
                        c_df = pd.DataFrame(crude_res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume']).tail(30).reset_index(drop=True)
                        c_df['9_EMA'] = c_df['close'].ewm(span=9, adjust=False).mean()
                        c_df['20_EMA'] = c_df['close'].ewm(span=20, adjust=False).mean()
                        c_delta = c_df['close'].diff()
                        c_df['RSI'] = 100 - (100 / (1 + (c_delta.clip(lower=0).ewm(com=13, adjust=False).mean() / c_delta.clip(upper=0).abs().ewm(com=13, adjust=False).mean().replace(0, 0.00001))))
                        c_last_row = c_df.iloc[-1]
                        crude_rsi = float(c_last_row['RSI']) if not np.isnan(c_last_row['RSI']) else 50.0
                        crude_ema9, crude_ema20 = float(c_last_row['9_EMA']), float(c_last_row['20_EMA'])

                        # मूळ पॅनेल रचना - ड्युएल ग्रिड लेआउट (NIFTY + CRUDE OIL SIDE BY SIDE)
                        dhan_card = f"""
                        <div style="background-color:#060814; padding:20px; border-radius:16px; font-family:sans-serif; color:white; max-width:440px; margin:auto; border: 1px solid #1c2136;">
                            
                            <!-- 🛢️ क्रूड ऑइलचा जिवंत लाईव्ह डेटा बॉक्स -->
                            <div style="background-color:#ffb30010; border: 1px solid #ffb30050; padding:15px; border-radius:12px; text-align:center; margin-bottom:15px;">
                                <span style="font-size:11px; color:#ffb300; text-transform:uppercase; font-weight:bold; letter-spacing:1px;">🛢️ CRUDEOIL MCX LIVE (🧪 TONIGHT TEST)</span>
                                <h1 style="font-size:38px; margin:5px 0; color:#ffb300; font-weight:bold;">₹ {crude_spot:.0f}</h1>
                                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; font-size:12px;">
                                    <div style="background:#111422; padding:6px; border-radius:6px;"><b>Live RSI:</b> <span style="color:#00e676;">{crude_rsi:.1f}</span></div>
                                    <div style="background:#111422; padding:6px; border-radius:6px;"><b>9 EMA:</b> ₹{crude_ema9:.0f}</div>
                                </div>
                            </div>

                            <!-- 📊 निफ्टीचा शेवटचा डेटा बॉक्स -->
                            <div style="text-align:center; margin-bottom:15px; background:#11142250; padding:12px; border-radius:12px; border:1px solid #1c2136;">
                                <span style="font-size:11px; color:#8f96a3; font-weight:bold; text-transform:uppercase;">📊 NIFTY 50 (LAST SESSION CLOSE)</span>
                                <h2 style="font-size:28px; margin:5px 0; color:#00e676; font-weight:bold;">₹ {live_spot:.2f}</h2>
                                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:5px; font-size:11px; color:#8f96a3;">
                                    <div><b>RSI:</b> {rsi_v:.1f}</div>
                                    <div><b>9 EMA:</b> ₹{ema9:.1f}</div>
                                </div>
                            </div>
                            
                            <div style="background-color:#ff525215; border:1px solid #ff5252; padding:10px; border-radius:8px; font-weight: bold; color:#ff5252; font-size:12px; text-align:center; margin-top:10px;">
                                🔴 PE STRATEGY ACTIVATED (LAST SETTLEMENT CANDLE PE SIGNAL)
                            </div>
                            
                            <p style='text-align:center; color:#5c6370; margin:15px 0 0 0; font-size:10px;'>⏱️ MCX Night Streaming Operational | {ist_now.strftime('%H:%M:%S')} IST</p>
                        </div>
                        <script>setTimeout(function(){{ window.location.reload(); }}, 1500);</script>"""
                        components.html(dhan_card, height=480, scrolling=False)
                except: pass
                time.sleep(1.5)
else: st.warning("🔒 Enter Password.")
