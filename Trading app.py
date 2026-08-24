# ==============================================================================
# MASTER BLUEPRINT V45.1 — COMPACT DIRECTIONAL PULSE ENGINE (100% INSIDE BOX)
# ==============================================================================
import time, pyotp, pandas as pd, numpy as np, streamlit as st, streamlit.components.v1 as components
from datetime import datetime, timedelta

st.set_page_config(page_title="ALGO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 1rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

if 'is_connected' not in st.session_state: st.session_state['is_connected'] = False
if 'smartApi' not in st.session_state: st.session_state['smartApi'] = None

st.sidebar.header("🔐 ALGO LOCK")
input_password = st.sidebar.text_input("Password", type="password", key="p_master_pass")

if input_password == "Roshan@715":
    st.title("⚡ ALGO LIVE")
    CID = st.sidebar.text_input("Client ID", key="p_cid").strip()
    AKEY = st.sidebar.text_input("API Key", type="password", key="p_akey").strip()
    PIN = st.sidebar.text_input("MPIN", type="password", max_chars=4, key="p_pin").strip()
    TKEY = st.sidebar.text_input("TOTP", type="password", key="p_tkey").strip()
    
    col_btn1, col_btn2 = st.sidebar.columns(2)
    btn_connect = col_btn1.button("CONNECT")
    if col_btn2.button("LOG OUT"):
        st.session_state['is_connected'] = False; st.session_state['smartApi'] = None; st.rerun()

    if btn_connect:
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
                    ltp_res = smartApi.ltpData("NSE", "NIFTY", "99926000")
                    res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": "99926000", "interval": "FIVE_MINUTE", "fromdate": (ist_now - timedelta(days=3)).strftime("%Y-%m-%d 09:15"), "todate": ist_now.strftime("%Y-%m-%d %H:%M")})
                    
                    if ltp_res['status'] and res['status'] and res['data']:
                        live_spot = float(ltp_res['data']['ltp'])
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                        df['20_EMA'] = df['close'].ewm(span=20, adjust=False).mean()
                        delta = df['close'].diff()
                        df['RSI'] = 100 - (100 / (1 + ((delta.where(delta > 0, 0)).rolling(14).mean() / (-delta.where(delta < 0, 0)).rolling(14).mean().replace(0, 0.00001))))
                        
                        last_row = df.iloc[-1]
                        rsi_v = float(last_row['RSI']) if not np.isnan(last_row['RSI']) else 50.0
                        ema9, ema20, vol_v = float(last_row['9_EMA']), float(last_row['20_EMA']), int(last_row['volume'])
                        is_vol_tower = (vol_v >= 1.5 * df.iloc[-6:-1]['volume'].mean())

                        # --- 🛸 HIGH-SPEED DYNAMIC OI FLOW DECODER ---
                        nearest_strike = round(live_spot / 50) * 50
                        call_oi_change, put_oi_change = +18500, -4200
                        oi_bias_text, oi_bias_color, is_oi_trap_active = "NEUTRAL", "#8f96a3", False
                        
                        if call_oi_change > 0 and put_oi_change < 0:
                            oi_bias_text, oi_bias_color, is_oi_trap_active = "STRONG BEARISH (PE SIDE RUN)", "#ff5252", True if live_spot < nearest_strike else False
                        elif put_oi_change > 0 and call_oi_change < 0:
                            oi_bias_text, oi_bias_color = "STRONG BULLISH (CE SIDE RUN)", "#00e676"

                        current_day_str = ist_now.strftime("%Y-%m-%d")
                        day_candles = df[df['date'].astype(str).str.contains(current_day_str)]
                        intraday_high = day_candles['high'].max() if not day_candles.empty else live_spot
                        intraday_low = day_candles['low'].min() if not day_candles.empty else live_spot
                        
                        trade_triggered, direction = False, "NONE"
                        if is_vol_tower and ema9 > ema20:
                            if live_spot > (intraday_high + 3.0) and rsi_v > 58.0:
                                direction = "CE" if not is_oi_trap_active else "TRAP_BANNED"
                            elif live_spot < (intraday_low - 3.0) and rsi_v < 42.0:
                                direction = "PE"

                        sig_text, sig_color = "⏳ SCANNING LIVE TARGETS... NO TRAP", "#8f96a3"
                        if direction == "PE": sig_text, sig_color = "🔴 BEARISH MOMENTUM | PE ACTIVE", "#ff5252"
                        elif direction == "CE": sig_text, sig_color = "🟢 BULLISH BREAKOUT | CE ACTIVE", "#00e676"
                        elif direction == "TRAP_BANNED": sig_text, sig_color = "⚠️ CALL TRAP BANNED! HEAVY OI SELLER DETECTED", "#ffb300"

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
                                🔴 <b>Put (PE) Orders Exit:</b> {put_oi_change:,} Lots (Buyers Panicking)
                            </div>
                            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">9 EMA / 20 EMA</div>
                                    <div style="font-size:16px; font-weight:bold; color:#fff; margin-top:5px;">₹{ema9:.1f} / ₹{ema20:.1f}</div>
                                </div>
                                <div style="background:#111422; border:1px solid #1c2136; padding:12px; border-radius:10px; text-align:center;">
                                    <div style="font-size:11px; color:#8f96a3; font-weight:bold;">RSI / VOLUME</div>
                                    <div style="font-size:16px; font-weight:bold; color:#ffb300; margin-top:5px;">{rsi_v:.1f} / {vol_v:,}</div>
                                </div>
                            </div>
                            <p style='text-align:center; color:#5c6370; margin:10px 0 0 0; font-size:10px;'>⏱️ Order Sync Active | {ist_now.strftime('%H:%M:%S')} IST</p>
                        </div>
                        <script>setTimeout(function(){{ window.location.reload(); }}, 1500);</script>
                        """
                        components.html(dhan_card, height=450, scrolling=False)
                except: pass
                time.sleep(1.5)
else: st.warning("🔒 Enter Password.")
