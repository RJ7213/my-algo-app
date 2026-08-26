import time, pyotp, pandas as pd, numpy as np, streamlit as st, streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

st.set_page_config(page_title="ALGO REALTIME RENDER", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# 🔐 क्रेडेंशियल्स मेमरी (इथे तुमचे इंग्रजी आकडे आणि खरी की टाका)
CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" 

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None
if 'local_nifty_df' not in st.session_state: st.session_state['local_nifty_df'] = None
if 'local_crude_df' not in st.session_state: st.session_state['local_crude_df'] = None

if 'last_valid_data' not in st.session_state:
    st.session_state['last_valid_data'] = {
        'live_spot': 24207.75, 'rsi_v': 19.81, 'ema9': 24220.30,
        'intraday_high': 24334.55, 'intraday_low': 24115.45, 'prev_rsi': 22.00,
        'crude_spot': 6817.0, 'crude_rsi': 47.9, 'crude_ema9': 6812.0,
        'crude_high': 6850.0, 'crude_low': 6780.0, 'prev_crude_rsi': 47.0,
        'setup_detected': "Major Rejection", 'c_setup': "Pullback",
        'rsi_status': "FAIL", 'ema_status': "FAIL", 'vol_status': "FAIL", 'runway_status': "FAIL", 'oi_status': "FAIL", 'wall_status': "FAIL"
    }

st.title("⚡ ALGO LIVE")
st.sidebar.header("🔐 ALGO AUTOLOGIN")

if not st.session_state['is_connected']:
    if st.sidebar.button("START ALGO ENGINE"):
        from SmartApi import SmartConnect
        try:
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            clean_tkey = TKEY.replace(" ", "").strip().upper()
            missing_padding = len(clean_tkey) % 8
            if missing_padding != 0: clean_tkey += '=' * (8 - missing_padding)
            totp_token = pyotp.TOTP(clean_tkey).now()
            if smartApi.generateSession(CID, PIN, totp_token)['status']:
                st.session_state['is_connected'] = True; st.session_state['smartApi'] = smartApi
                st.sidebar.success("🟢 System Active!")
        except Exception as e: st.sidebar.error(f"Login Failed: {str(e)}")
else:
    st.sidebar.success("🟢 Algo Engine Running Smoothly")
    if st.sidebar.button("STOP ENGINE"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()
dhan_app_canvas = st.empty()
if st.session_state['is_connected']:
    while True:
        with dhan_app_canvas.container():
            try:
                ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                current_time = ist_now.time()
                current_day_str = ist_now.strftime("%Y-%m-%d")
                
                is_weekend = (ist_now.weekday() >= 5)
                is_nifty_active = (not is_weekend) and (datetime_time(9, 15) <= current_time <= datetime_time(15, 30))
                is_crude_active = (not is_weekend) and (datetime_time(9, 0) <= current_time <= datetime_time(23, 30))
                
                live_spot = st.session_state['last_valid_data']['live_spot']
                rsi_v = st.session_state['last_valid_data']['rsi_v']
                ema9 = st.session_state['last_valid_data']['ema9']
                intraday_high = st.session_state['last_valid_data']['intraday_high']
                intraday_low = st.session_state['last_valid_data']['intraday_low']
                
                crude_spot = st.session_state['last_valid_data']['crude_spot']
                crude_rsi = st.session_state['last_valid_data']['crude_rsi']
                crude_ema9 = st.session_state['last_valid_data']['crude_ema9']
                crude_high = st.session_state['last_valid_data']['crude_high']
                crude_low = st.session_state['last_valid_data']['crude_low']

                if st.session_state['smartApi']:
                    smartApi = st.session_state['smartApi']
                    
                    if is_nifty_active:
                        try:
                            ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                            if ltp_res and ltp_res.get('status'): live_spot = float(ltp_res['data']['ltp'])
                            if st.session_state['local_nifty_df'] is None or (ist_now.minute % 5 == 0 and ist_now.second <= 3):
                                from_time = (ist_now - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M")
                                res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                                if res and res.get('data'): st.session_state['local_nifty_df'] = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                            if st.session_state['local_nifty_df'] is not None:
                                df = st.session_state['local_nifty_df']
                                df.iloc[-1, df.columns.get_loc('close')] = live_spot
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
                    if is_crude_active:
                        try:
                            crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", "255294")
                            if crude_ltp_res and crude_ltp_res.get('status'): crude_spot = float(crude_ltp_res['data']['ltp'])
                            if st.session_state['local_crude_df'] is None or (ist_now.minute % 5 == 0 and ist_now.second <= 3):
                                from_time = (ist_now - timedelta(minutes=120)).strftime("%Y-%m-%d %H:%M")
                                res_c = smartApi.getCandleData({"exchange": "MCX", "symboltoken": "255294", "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                                if res_c and res_c.get('data'): st.session_state['local_crude_df'] = pd.DataFrame(res_c['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                            if st.session_state['local_crude_df'] is not None:
                                df_c = st.session_state['local_crude_df']
                                df_c.iloc[-1, df_c.columns.get_loc('close')] = crude_spot
                                df_c['close'] = df_c['close'].astype(float)
                                change_c = df_c['close'].diff()
                                gain_c = change_c.mask(change_c < 0, 0.0); loss_c = -change_c.mask(change_c > 0, 0.0)
                                avg_gain_c = gain_c.ewm(com=13, min_periods=14).mean(); avg_loss_c = loss_c.ewm(com=13, min_periods=14).mean()
                                rs_c = avg_gain_c / avg_loss_c.replace(0, 0.00001)
                                st.session_state['last_valid_data']['prev_crude_rsi'] = crude_rsi
                                crude_rsi = float(100 - (100 / (1 + rs_c)).iloc[-1])
                                crude_ema9 = float(df_c['close'].ewm(span=9, adjust=False).mean().iloc[-1])
                                crude_high = float(df_c['high'].astype(float).max()); crude_low = float(df_c['low'].astype(float).min())
                        except: pass

                setup = "Major Rejection" if rsi_v < 30 else "Pullback"
                c_setup = "Day High/Low" if crude_spot >= (crude_high - 10) else "Pullback"
                st.session_state['last_valid_data'].update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'intraday_high': intraday_high, 'intraday_low': intraday_low, 'setup_detected': setup, 'crude_spot': crude_spot, 'crude_rsi': crude_rsi, 'crude_ema9': crude_ema9, 'crude_high': crude_high, 'crude_low': crude_low, 'c_setup': c_setup})
                tab_nifty, tab_crude = st.tabs(["📈 NIFTY 50", "🛢️ CRUDEOIL"])
                t_map = lambda s: '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s=="PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
                s_active = lambda act, s_name: "background:#00e67620;border:1px solid #00e676;color:#00e676;" if act == s_name else "background:#111422;opacity:0.3;color:#8f96a3;"
                
                with tab_nifty:
                    r_st = "PASS" if rsi_v < 30 else "FAIL"
                    e_st = "PASS" if live_spot > ema9 else "FAIL"
                    dhan_card_n = f"""
                    <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136;">
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
                            <div style="{s_active(setup, "Morning Box")} padding:6px; border-radius:6px;">Morning Box</div>
                            <div style="{s_active(setup, "Pullback")} padding:6px; border-radius:6px;">Pullback</div>
                            <div style="{s_active(setup, "Day High/Low")} padding:6px; border-radius:6px;">Day High/Low</div>
                            <div style="{s_active(setup, "Major Rejection")} padding:6px; border-radius:6px;">Major Rejection</div>
                        </div>
                        <div style="background-color:#00e67610; border:1px solid #00e67650; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
                            <h1 style="font-size:36px; margin:4px 0; color:#00e676; font-weight:bold;">{live_spot:.2f}</h1>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
                                <div style="background:#111422; padding:5px; border-radius:4px;"><b>Nifty RSI:</b> {rsi_v:.1f}</div>
                                <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> {ema9:.2f}</div>
                            </div>
                        </div>
                        <div style="background:#111422; padding:12px; border-radius:10px; font-size:12px; border:1px solid #1c2136; line-height:1.6;">
                            <div>1. True RSI <b>({rsi_v:.1f})</b>: {t_map(r_st)}</div>
                            <div>2. Institutional 9 EMA: {t_map(e_st)}</div>
                        </div>
                        <div style="margin-top:10px; height:180px; border-radius:8px; overflow:hidden;"><iframe src="https://tradingview.com" style="width:100%; height:100%; border:none;"></iframe></div>
                    </div>"""
                    components.html(dhan_card_n, height=540, scrolling=False)

                with tab_crude:
                    cr_st = "PASS" if crude_rsi > 55 else "FAIL"
                    ce_st = "PASS" if crude_spot > crude_ema9 else "FAIL"
                    dhan_card_c = f"""
                    <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136;">
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:10px;">
                            <div style="{s_active(c_setup, "Morning Box")} padding:6px; border-radius:6px;">Morning Box</div>
                            <div style="{s_active(c_setup, "Pullback")} padding:6px; border-radius:6px;">Pullback</div>
                            <div style="{s_active(c_setup, "Day High/Low")} padding:8px; border-radius:8px;">Day High/Low</div>
                            <div style="{s_active(c_setup, "Major Rejection")} padding:6px; border-radius:6px;">Major Rejection</div>
                        </div>
                        <div style="background-color:#ffb30010; border:1px solid #ffb30050; padding:12px; border-radius:10px; text-align:center; margin-bottom:10px;">
                            <h1 style="font-size:36px; margin:4px 0; color:#ffb300; font-weight:bold;">₹ {crude_spot:.2f}</h1>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:11px;">
                                <div style="background:#111422; padding:5px; border-radius:4px;"><b>Crude RSI:</b> {crude_rsi:.1f}</div>
                                <div style="background:#111422; padding:5px; border-radius:4px;"><b>9 EMA:</b> ₹{crude_ema9:.1f}</div>
                            </div>
                        </div>
                        <div style="background:#111422; padding:15px; border-radius:10px; font-size:12px; border:1px solid #1c2136; line-height:1.6;">
                            <div>1. 5-Min True RSI <b>({crude_rsi:.1f})</b>: {t_map(cr_st)}</div>
                            <div>2. Institutional 9 EMA: {t_map(ce_st)}</div>
                        </div>
                        <div style="margin-top:10px; height:180px; border-radius:8px; overflow:hidden;"><iframe src="https://tradingview.com" style="width:100%; height:100%; border:none;"></iframe></div>
                    </div>"""
                    components.html(dhan_card_c, height=540, scrolling=False)
            except: pass
        time.sleep(1); st.rerun()
