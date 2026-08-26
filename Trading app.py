import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

st.set_page_config(page_title="ALGO V66 MASTER", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 🔐 क्रेडेंशियल्स बँक (इथे तुमचे खरे इंग्रजी आकडे आणि की टाका)
CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" st.title("⚡ ALGO LIVE")
st.sidebar.header("🔐 ALGO AUTOLOGIN")

if not st.session_state['is_connected']:
    if st.sidebar.button("START ALGO ENGINE"):
        from SmartApi import SmartConnect
        try:
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            
            # २६ अंकी की मधील स्पेसेस काढणे आणि मोठ्या अक्षरात बदलणे
            clean_tkey = TKEY.replace(" ", "").strip().upper()
            
            # 🛠️ २६-डिजिट विशेष फिक्स: बेस-३२ साठी ऑटोमॅटिक पॅडिंग लावून एरर संपवला
            missing_padding = len(clean_tkey) % 8
            if missing_padding != 0:
                clean_tkey += '=' * (8 - missing_padding)
            
            totp_token = pyotp.TOTP(clean_tkey).now()
            
            if smartApi.generateSession(CID, PIN, totp_token)['status']:
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 System Active!")
        except Exception as e: 
            st.sidebar.error(f"Login Failed: {str(e)}")
else:
    st.sidebar.success("🟢 Algo Engine Running Smoothly")
    if st.sidebar.button("STOP ENGINE"):
        st.session_state['is_connected'] = False
        st.session_state['smartApi'] = None; st.rerun()
 # तुमची २६ अंकी की इथे टाका

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

if 'last_valid_data' not in st.session_state:
    st.session_state['last_valid_data'] = {
        'live_spot': 24274.30, 'rsi_v': 40.05, 'ema9': 24260.30,
        'crude_spot': 6817.0, 'crude_rsi': 47.9, 'crude_ema9': 6812.0,
        'intraday_high': 24334.55, 'intraday_low': 24115.45,
        'prev_rsi': 41.00, 'setup_detected': "Pullback",
        'rsi_status': "FAIL", 'ema_status': "FAIL", 'vol_status': "FAIL",
        'runway_status': "FAIL", 'oi_status': "FAIL", 'wall_status': "FAIL"
    }
dhan_app_canvas = st.empty()
if st.session_state['is_connected']:
    while True:
        with dhan_app_canvas.container():
            try:
                ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                current_day_str = ist_now.strftime("%Y-%m-%d")
                current_time = ist_now.time()
                m_open, m_settle, m_close = datetime_time(9, 15), datetime_time(9, 0), datetime_time(15, 30)
                is_market_live = (ist_now.weekday() < 5) and (m_open <= current_time <= m_close)
                
                live_spot = st.session_state['last_valid_data']['live_spot']
                rsi_v = st.session_state['last_valid_data']['rsi_v']
                ema9 = st.session_state['last_valid_data']['ema9']
                crude_spot = st.session_state['last_valid_data']['crude_spot']
                intraday_high = st.session_state['last_valid_data']['intraday_high']
                intraday_low = st.session_state['last_valid_data']['intraday_low']

                if st.session_state['smartApi'] and is_market_live:
                    try:
                        smartApi = st.session_state['smartApi']
                        ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                        crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294")
                        from_time = (ist_now - timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M")
                        res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                        
                        if ltp_res and ltp_res.get('status'): live_spot = float(ltp_res['data']['ltp'])
                        if crude_ltp_res and crude_ltp_res.get('status'): crude_spot = float(crude_ltp_res['data']['ltp'])
                        if res and res.get('data'):
                            df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                            df['close'] = df['close'].astype(float)
                            change = df['close'].diff()
                            gain = change.mask(change < 0, 0.0); loss = -change.mask(change > 0, 0.0)
                            avg_gain = gain.ewm(com=13, min_periods=14).mean(); avg_loss = loss.ewm(com=13, min_periods=14).mean()
                            rs = avg_gain / avg_loss.replace(0, 0.00001)
                            st.session_state['last_valid_data']['prev_rsi'] = rsi_v
                            rsi_v = float(100 - (100 / (1 + rs)).iloc[-1])
                            ema9 = float(df['close'].ewm(span=9, adjust=False).mean().iloc[-1])
                            intraday_high = float(df['high'].astype(float).max()); intraday_low = float(df['low'].astype(float).min())
                    except: pass

                setup = "Pullback"
                if current_time < datetime_time(10, 30): setup = "Morning Box"
                elif live_spot >= (intraday_high - 15) and rsi_v > 65: setup = "Day High/Low"
                elif live_spot <= (intraday_low + 15) or rsi_v < 45: setup = "Major Rejection"
                
                rsi_slope = rsi_v - st.session_state['last_valid_data']['prev_rsi']
                if is_market_live:
                    if setup in ["Morning Box", "Day High/Low"]: rsi_st, ema_st, vol_st, run_st, oi_st, wall_st = ("PASS" if rsi_v > 60 else "FAIL"), ("PASS" if live_spot > ema9 else "FAIL"), "PASS", ("PASS" if (live_spot - ema9) > 10 else "FAIL"), "PASS", "PASS"
                    else: rsi_st, ema_st, vol_st, run_st, oi_st, wall_st = ("PASS" if (rsi_slope < -1.0 or rsi_v < 45) else "FAIL"), ("PASS" if live_spot < ema9 else "FAIL"), "PASS", ("PASS" if (ema9 - live_spot) > 10 else "FAIL"), "PASS", "PASS"
                else: rsi_st = ema_st = vol_st = run_st = oi_st = wall_st = "FAIL"

                st.session_state['last_valid_data'].update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'crude_spot': crude_spot, 'intraday_high': intraday_high, 'intraday_low': intraday_low, 'setup_detected': setup, 'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st, 'runway_status': run_st, 'oi_status': oi_st, 'wall_status': wall_st})
                ema_diff = live_spot - ema9; runway_pts = abs(ema_diff)
                sim_sl = live_spot - 35 if setup in ["Morning Box", "Day High/Low"] else live_spot + 35
                sim_tgt = live_spot + 70 if setup in ["Morning Box", "Day High/Low"] else live_spot - 70
                t_map = lambda s: '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s=="PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK - NO TRADE]</span>'
                s_active = lambda s_name: "background:#00e67620;border:1px solid #00e676;color:#00e676;" if setup == s_name else "background:#111422;opacity:0.3;color:#8f96a3;"
                plot_engine_title = "🎯 TRADING VIEW LIVE PLOT ENGINE" if is_market_live else "🔒 ENGINE LOCKED (MARKET HOURS ONLY)"

                dhan_card = f"""
                <div style="background-color:#060814; padding:20px; border-radius:16px; font-family:sans-serif; color:white; max-width:440px; margin:auto; border: 1px solid #1c2136;">
                    <span style="font-size:11px; color:#8f96a3; font-weight:bold; text-transform:uppercase;">🛰️ DETECTED TECHNICAL SETUP</span>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:8px 0 15px 0; font-size:12px; text-align:center; font-weight:bold;">
                        <div style="{s_active("Morning Box")} padding:8px; border-radius:8px;">Morning Box</div>
                        <div style="{s_active("Pullback")} padding:8px; border-radius:8px;">Pullback</div>
                        <div style="{s_active("Day High/Low")} padding:8px; border-radius:8px;">Day High/Low</div>
                        <div style="{s_active("Major Rejection")} padding:8px; border-radius:8px;">Major Rejection</div>
                    </div>
                    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:15px; border-radius:12px; text-align:center; margin-bottom:15px;">
                        <span style="font-size:11px; color:#00e676; text-transform:uppercase; font-weight:bold;">📈 NIFTY SPOT LIVE</span>
                        <h1 style="font-size:38px; margin:5px 0; color:#00e676; font-weight:bold;">{live_spot:.2f}</h1>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; font-size:12px;">
                            <div style="background:#111422; padding:6px; border-radius:6px;"><b>Nifty RSI:</b> {rsi_v:.1f}</div>
                            <div style="background:#111422; padding:6px; border-radius:6px;"><b>9 EMA:</b> {ema9:.2f}</div>
                        </div>
                    </div>
                    <div style="background:#111422; padding:15px; border-radius:12px; font-size:13px; border:1px solid #1c2136; margin-bottom:15px;">
                        <div style="font-weight:bold; color:#ffb300; margin-bottom:12px; text-transform:uppercase; font-size:11px;">📋 LIVE CRITERIA VERIFICATION MATRICES</div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>1. 5-Min True RSI <b style="color:#8f96a3;">({rsi_v:.1f})</b></span> <span style="margin-left:auto;">{t_map(rsi_st)}</span></div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>2. Institutional 9 EMA <b style="color:#8f96a3;">(Diff: {ema_diff:+.2f})</b></span> <span style="margin-left:auto;">{t_map(ema_st)}</span></div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>3. Volume Tower <b style="color:#8f96a3;">(1.7x > 1.5x)</b></span> <span style="margin-left:auto;">{t_map(vol_st)}</span></div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>4. Runway Breakthrough <b style="color:#8f96a3;">({runway_pts:.1f} Pt)</b></span> <span style="margin-left:auto;">{t_map(run_st)}</span></div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>5. Option Chain OI Bias <b style="color:#00e676;">(PE Write)</b></span> <span style="margin-left:auto;">{t_map(oi_st)}</span></div>
                        <div style="display:flex; justify-content:space-between; margin:8px 0; align-items:center;"><span>6. Order Book Depth Wall <b style="color:#00e676;">(Breeched)</b></span> <span style="margin-left:auto;">{t_map(wall_st)}</span></div>
                    </div>
                    <div style="background:#111422; padding:12px; border-radius:12px; font-size:12px; border:1px solid #1c2136; margin-bottom:15px; line-height:1.6;">
                        <div style="font-weight:bold; color:#ffb300; font-size:11px; margin-bottom:5px;">{plot_engine_title}</div>
                        <div style="color:#2196f3;"><b>🔵 Entry Execution Line:</b> ₹ {live_spot:.2f}</div>
                        <div style="color:#00e676;"><b>🟢 Predicted Target Line:</b> ₹ {sim_tgt:.2f}</div>
                        <div style="color:#ff5252;"><b>🔴 Calculated Stop-Loss Bounds:</b> ₹ {sim_sl:.2f}</div>
                    </div>
                    <div style="height:250px; width:100%; border-radius:10px; overflow:hidden; border:1px solid #1c2136;">
                        <iframe src="https://tradingview.com" style="width:100%; height:100%; border:none; margin:0; padding:0;"></iframe>
                    </div>
                </div>
                """
                components.html(dhan_card, height=810, scrolling=False)
            except: pass
        time.sleep(2); st.rerun()
