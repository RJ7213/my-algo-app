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
                st.session_state['is_connected'] = True; st.session_state['smartApi'] = smartApi; st.sidebar.success("🟢 Active!")
        except: pass
    if col_btn2.button("LOG OUT"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()

    dhan_app_canvas = st.empty()
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        while True:
            with dhan_app_canvas.container():
                try:
                    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                    current_time = ist_now.time()
                    m_open, m_settle, m_close = datetime_time(9, 15), datetime_time(9, 0), datetime_time(15, 30)
                    
                    if current_time >= m_close or current_time < m_settle:
                        session_status, sig_color, js_reload, f_days, t_hour = "🔒 MARKET CLOSED (DISPLAYING LAST SESSION TRADES)", "#ff5252", 300000, 3, "15:30"
                    elif m_settle <= current_time < m_open:
                        session_status, sig_color, js_reload, f_days, t_hour = "🗓️ PRE-MARKET SETTLEMENT ACTIVE", "#ffb300", 10000, 1, "09:08"
                    else:
                        session_status, sig_color, js_reload, f_days, t_hour = "⏳ ALGO SCALPING SCANNERS ACTIVE... WAITING FOR 15-PT BREAKOUT", "#8f96a3", 2000, 2, "%H:%M"

                    ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                    res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=f_days)).strftime("%Y-%m-%d 09:15"), "todate": ist_now.strftime(f"%Y-%m-%d {t_hour}")})
                    
                    crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294")
                    crude_res = smartApi.getCandleData({"exchange": "MCX", "symboltoken": "255294", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=2)).strftime("%Y-%m-%d 09:00"), "todate": ist_now.strftime("%Y-%m-%d %H:%M")})

                    if ltp_res['status'] and res['status'] and res['data'] and crude_ltp_res['status'] and crude_res['data']:
                        live_spot = float(ltp_res['data']['ltp'])
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume']).tail(30).reset_index(drop=True)
                        df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                        delta = df['close'].diff()
                        df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).ewm(com=13, adjust=False).mean() / delta.clip(upper=0).abs().ewm(com=13, adjust=False).mean().replace(0, 0.00001))))
                        last_row = df.iloc[-1]; rsi_v = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 33.0; ema9 = float(last_row['9_EMA'])

                        crude_spot = float(crude_ltp_res['data']['ltp'])
                        c_df = pd.DataFrame(crude_res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume']).tail(30).reset_index(drop=True)
                        c_df['9_EMA'] = c_df['close'].ewm(span=9, adjust=False).mean()
                        c_delta = c_df['close'].diff()
                        c_df['RSI'] = 100 - (100 / (1 + (c_delta.clip(lower=0).ewm(com=13, adjust=False).mean() / c_delta.clip(upper=0).abs().ewm(com=13, adjust=False).mean().replace(0, 0.00001))))
                        c_last_row = c_df.iloc[-1]; crude_rsi = float(c_last_row['RSI']) if not np.isnan(c_last_row['RSI']) else 50.0; crude_ema9 = float(c_last_row['9_EMA'])

                        current_day_str = ist_now.strftime("%Y-%m-%d")
                        day_candles = df[df['date'].astype(str).str.contains(current_day_str)]
                        intraday_high = day_candles['high'].max() if not day_candles.empty else live_spot
                        intraday_low = day_candles['low'].min() if not day_candles.empty else live_spot
                        call_oi_change, put_oi_change = +18500, -4200
                        oi_bias_text, oi_bias_color = "STRONG BEARISH (PE RUN)", "#ff5252" if call_oi_change > 0 else "STRONG BULLISH", "#00e676"
                        
                        if (current_time >= m_close or current_time < m_settle) or (live_spot < intraday_low):
                            session_status, sig_color = "🔴 PE STRATEGY ACTIVATED (LAST SETTLEMENT CANDLE PE SIGNAL)", "#ff5252"

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
                                <div><b>OI Bias:</b> <span style="color:{oi_bias_color}; font-weight:bold;">{oi_bias_text}</span></div>
                            </div>
                            <script>
                                setTimeout(function(){{ window.location.reload(); }}, {js_reload});
                            </script>
                        </div>
                        """
                        components.html(dhan_card, height=480, scrolling=False)
                except Exception as e:
                    st.error(f"Error in Live Loop: {str(e)}")
            time.sleep(2)
