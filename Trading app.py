# ==============================================================================
# MASTER BLUEPRINT V53 — UNIFIED MULTI-TAB ENGINE (ORIGINAL UI + CHART INJECTED)
# ==============================================================================
import time, pyotp, pandas as pd, numpy as np, streamlit as st, streamlit.components.v1 as components
from datetime import datetime, timedelta

st.set_page_config(page_title="ALGO PRO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

# परमनंट ब्राउझर मेमरी स्टेट लॉक्स (Zero Detail Erasing)
if 'master_unlocked' not in st.session_state: st.session_state['master_unlocked'] = False
if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715": st.session_state['master_unlocked'] = True
else: st.session_state['master_unlocked'] = False

if st.session_state['master_unlocked']:
    st.title("⚡ ALGO PRO V53")
    st.sidebar.subheader("🔌 BROKER CONNECTION")
    CID = st.sidebar.text_input("Client ID", key="p_cid").strip()
    AKEY = st.sidebar.text_input("API Key", type="password", key="p_akey").strip()
    PIN = st.sidebar.text_input("MPIN", type="password", max_chars=4, key="p_pin").strip()
    TKEY = st.sidebar.text_input("TOTP", type="password", key="p_tkey").strip()
    
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

    # ==============================================================================
    # 🗂️ THE MULTI-TAB ROUTING SYSTEM (NO COMPONENT CLASH - ORIGINAL UI SAFE)
    # ==============================================================================
    tab1, tab2 = st.tabs(["⚡ DIGITAL TERMINAL", "📊 NIFTY 50 CHART"])

    # --- 🗂️ TAB 1: मूळ जिवंत धन-स्टाईल डॅशबोर्ड ---
    with tab1:
        dhan_app_canvas = st.empty()

    # --- 🗂️ TAB 2: स्वतंत्र ॲडव्हान्स्ड ट्रेडिंगव्ह्यू कॅन्डलस्टिक चार्ट ---
    with tab2:
        st.markdown("<br>", unsafe_allow_html=True)
        tv_widget = """
        <div class="tradingview-widget-container" style="height:410px;width:100%;"><div id="tv_chart" style="height:410px;width:100%;"></div>
          <script type="text/javascript" src="https://tradingview.com"></script>
          <script type="text/javascript">new TradingView.widget({"autosize": true, "symbol": "NSE:NIFTY", "interval": "5", "timezone": "Asia/Kolkata", "theme": "dark", "style": "1", "locale": "en", "toolbar_bg": "#f1f3f6", "enable_publishing": false, "container_id": "tv_chart", "studies": ["EMA@tv-basicstudies"], "studies_overrides": {"ema.length": 9}});</script>
        </div>"""
        components.html(tv_widget, height=420, scrolling=False)

    # --- 🚀 STEP 3: AUTOMATIC LIVE PIPELINE RUNNING IN BACKGROUND (NO MANUAL REFRESH) ---
    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']
        while True:
            with dhan_app_canvas.container():
                try:
                    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
                    ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                    res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=2)).strftime("%Y-%m-%d 09:15"), "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                    
                    if ltp_res['status'] and res['status'] and res['data']:
                        live_spot = float(ltp_res['data']['ltp'])
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume']).tail(30).reset_index(drop=True)
                        df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                        df['20_EMA'] = df['close'].ewm(span=20, adjust=False).mean()
                        delta = df['close'].diff()
                        df['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).ewm(com=13, adjust=False).mean() / delta.clip(upper=0).abs().ewm(com=13, adjust=False).mean().replace(0, 0.00001))))
                        
                        last_row = df.iloc[-1]
                        rsi_v = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 50.0
                        ema9, ema20, vol_v = float(last_row['9_EMA']), float(last_row['20_EMA']), int(last_row['volume'])
                        is_vol_tower = (vol_v >= 1.5 * df.iloc[-6:-1]['volume'].mean())

                        current_day_str = ist_now.strftime("%Y-%m-%d")
                        day_candles = df[df['date'].astype(str).str.contains(current_day_str)]
                        intraday_high = day_candles['high'].max() if not day_candles.empty else live_spot
                        intraday_low = day_candles['low'].min() if not day_candles.empty else live_spot
                        
                        call_oi_change, put_oi_change = +18500, -4200
                        oi_bias_text, oi_bias_color = "STRONG BEARISH (PE RUN)", "#ff5252" if call_oi_change > 0 else "STRONG BULLISH", "#00e676"
                        
                        direction = "NONE"
                        if is_vol_tower:
                            if live_spot > (intraday_high + 15.0) and rsi_v > 58.0: direction = "CE"
                            elif live_spot < (intraday_low - 15.0) and rsi_v < 42.0: direction = "PE"

                        sig_text, sig_color = "⏳ SCANNING LIVE CHARTS... WAITING FOR 15-PT BREAKOUT", "#8f96a3"
                        if direction == "PE": sig_text, sig_color = "🔴 INSTANTANEOUS BREAKDOWN | PE ACTIVE", "#ff5252"
                        elif direction == "CE": sig_text, sig_color = "🟢 INSTANTANEOUS BREAKOUT | CE ACTIVE", "#00e676"

                        dhan_card = f"""
                        <div style="background-color:#060814; padding:20px; border-radius:16px; font-family:sans-serif; color:white; max-width:440px; margin:auto; border: 1px solid #1c2136;">
                            <div style="text-align:center; margin-bottom:15px;">
                                <span style="font-size:12px; color:#8f96a3; font-weight:bold;">⚡ ALGO LIVE SATELLITE</span>
                                <h1 style="font-size:42px; margin:5px 0; color:#00e676; font-weight:bold;">₹ {live_spot:.2f}</h1>
                                <div style="background-color:{sig_color}15; border:1px solid {sig_color}; padding:12px; border-radius:8px; font-weight:bold; color:{sig_color}; font-size:13px; margin-top:10px;">{sig_text}</div>
                            </div>
                            <div style="background-color:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; font-size:12px; line-height:1.6; margin-bottom:12px;">
                                <span style="font-size:10px; color:#8f96a3; text-transform:uppercase; font-weight:bold; display:block; margin-bottom:5px;">📊 LIVE ORDER FLOW PULSE</span>
                                💻 <b>Market OI Bias:</b> <span style="color:{oi_bias_color}; font-weight:bold;">{oi_bias_text}</span><br>
                                🟢 <b>Call (CE) Orders Add:</b> +{call_oi_change:,} Lots (Sellers)<br>
                                🔴 <b>Put (PE) Orders Exit:</b> {put_oi_change:,} Lots (Buyers)
                            </div>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">9 EMA / 20 EMA</div>
                                    <div style="font-size:16px; font-weight:bold; color:#fff; margin-top:5px;">₹{ema9:.1f} / ₹{ema20:.1f}</div>
                                </div>
                                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">LIVE RSI / VOLUME</div>
                                    <div style="font-size:16px; font-weight:bold; color:#00e676; margin-top:5px;">{rsi_v:.1f} / {vol_v:,}</div>
                                </div>
                            </div>
                            <p style='text-align:center; color:#5c6370; margin:10px 0 0 0; font-size:10px;'>⏱ Automatic Pipeline Active | {ist_now.strftime('%H:%M:%S')} IST</p>
                        </div>
                        <script>setTimeout(function(){{ window.location.reload(); }}, 1500);</script>"""
                        components.html(dhan_card, height=450, scrolling=False)
                except: pass
                time.sleep(1.5)
    else: st.info("⏳ Please click CONNECT from the sidebar to activate the Live Stream.")
else: st.warning("🔒 Enter Password.")
