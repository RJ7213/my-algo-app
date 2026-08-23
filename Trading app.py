# ==============================================================================
# MASTER BLUEPRINT V20.6 — MULTI-PROVIDER STABLE TERMINAL
# ==============================================================================
import time
import pyotp
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta
from SmartApi import SmartConnect

st.set_page_config(page_title="Master Algo Terminal", page_icon="⚡", layout="wide")

# CSS पॅडिंग आणि डिजिटल कार्ड्स
st.markdown("""
    <style>
    .main .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    div[data-testid="stMetric"] {
        background-color: #1e222d !important;
        border: 1px solid #2a2e39 !important;
        border-radius: 8px !important;
        padding: 8px !important;
        text-align: center !important;
    }
    div[data-testid="stMetricValue"] { font-size: 20px !important; font-weight: bold !important; color: #00e676 !important; }
    div[data-testid="stMetricLabel"] { font-size: 11px !important; color: #9b9b9b !important; }
    </style>
""", unsafe_allow_html=True)

st.sidebar.header("🔐 MASTER APP SECURITY")
master_password = st.sidebar.text_input("Master Password", type="password")

if master_password == "Roshan@715":

    if 'is_connected' not in st.session_state:
        st.session_state['is_connected'] = False
        st.session_state['smartApi'] = None

    st.sidebar.subheader("🔌 BROKER CONNECTION")
    with st.sidebar.form("login_form"):
        CID = st.text_input("Client ID", value="R990942").strip()
        AKEY = st.text_input("SmartAPI Key", type="password").strip()
        PIN = st.text_input("4-Digit MPIN", type="password", max_chars=4).strip()
        TKEY = st.text_input("TOTP Key/Seed", type="password").strip()
        btn_connect = st.form_submit_button("CONNECT BROKER")

    if btn_connect:
        try:
            totp_code = pyotp.TOTP(TKEY).now()
            smartApi = SmartConnect(api_key=AKEY, timeout=15)
            session = smartApi.generateSession(CID, PIN, totp_code)

            if session.get('status'):
                st.sidebar.success("🟢 Connected!")
                st.session_state['is_connected'] = True
                st.session_state['smartApi'] = smartApi
            else:
                st.sidebar.error(f"🛑 {session.get('message', 'Failed')}")
                st.session_state['is_connected'] = False

        except Exception as e:
            st.sidebar.error(f"🛑 Login Error: {str(e)}")
            st.session_state['is_connected'] = False

    if st.session_state['is_connected'] and st.session_state['smartApi']:
        smartApi = st.session_state['smartApi']

        try:
            res = smartApi.getCandleData({
                "exchange": "NSE",
                "symboltoken": "99926000",
                "interval": "FIVE_MINUTE",
                "fromdate": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d 09:15"),
                "todate": datetime.now().strftime("%Y-%m-%d 15:30")
            })

            if res and res.get('status') and res.get('data'):
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])

                # Indicators
                df['9_EMA'] = df['close'].ewm(span=9, adjust=False).mean()
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                df['RSI'] = 100 - (100 / (1 + (gain / loss)))

                last_row = df.iloc[-1]
                prev_5_vol = df.iloc[-6:-1]['volume'].mean()
                live_p, rsi_v, ema_v, vol_v = last_row['close'], last_row['RSI'], last_row['9_EMA'], last_row['volume']
                is_vol_tower = (vol_v >= 1.5 * prev_5_vol)

                st.subheader(f"⚡ NIFTY 50 LIVE: ₹ {live_p:.2f}")

                tab1, tab2 = st.tabs(["⚡ DIGITAL DASHBOARD", "📊 LIVE CHART TERMINAL"])

                # ================= TAB 1: DIGITAL DASHBOARD =================
                with tab1:
                    if is_vol_tower and abs(live_p - ema_v) <= 10.0 and abs(live_p - last_row['open']) <= 20.0:
                        if rsi_v > 60.0:
                            st.success(f"🟢 **CALL TRIGGERED** | Target: {live_p + 20.0:.1f} | SL: Last Swing Low")
                        elif rsi_v < 40.0:
                            st.error(f"🔴 **PUT TRIGGERED** | Target: {live_p - 20.0:.1f} | SL: Last Swing High")
                    else:
                        st.info("⏳ **ALGO SCANNING...** PRICE ACTION NORMAL.")

                    c1, c2 = st.columns(2)
                    c1.metric("5-MIN RSI", f"{rsi_v:.1f}",
                              delta="BULLISH" if rsi_v > 60 else ("BEARISH" if rsi_v < 40 else "NEUTRAL"))
                    c2.metric("9 EMA LEVEL", f"₹ {ema_v:.1f}", delta=f"{live_p - ema_v:.1f}")

                    c3, c4 = st.columns(2)
                    c3.metric("CANDLE VOLUME", f"{vol_v:,}")
                    c4.metric("VOL TOWER", "1.5x ACTIVE 🚀" if is_vol_tower else "NORMAL")

                # ================= TAB 2: LIVE CHART PROVIDERS =================
                with tab2:
                    chart_provider = st.radio("Select Chart Engine:",
                                              ["TradingView (NSE:NIFTY)", "Yahoo Finance Chart"], horizontal=True)

                    if chart_provider == "TradingView (NSE:NIFTY)":
                        tv_widget = """
                        <div class="tradingview-widget-container" style="height:480px;width:100%">
                          <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_chart&symbol=NSE%3ANIFTY&interval=5&hidesidetoolbar=0&symboledit=1&saveimage=0&toolbarbg=f1f3f6&studies=%5B%5D&theme=dark&style=1&timezone=Asia%2FKolkata" style="width: 100%; height: 100%; border: none;"></iframe>
                        </div>
                        """
                        st.components.v1.html(tv_widget, height=500)

                    elif chart_provider == "Yahoo Finance Chart":
                        yf_chart = """
                        <iframe src="https://s.yimg.com/rq/darla/4.6.0/html/r-sf.html" style="width: 100%; height: 480px; border: none;"></iframe>
                        <div style="background:#1e222d; padding:10px; border-radius:8px; text-align:center;">
                            <a href="https://finance.yahoo.com/chart/%5ENSEI" target="_blank" style="color:#00e676; font-weight:bold; text-decoration:none;">
                                🚀 Click Here to Open Live Yahoo Nifty 50 Interactive Chart
                            </a>
                        </div>
                        """
                        st.components.v1.html(yf_chart, height=520)

            else:
                st.warning("⚠️ Market Closed / Data Offline.")

        except Exception as e:
            st.warning(f"⚠️ Connecting to Angel One... ({str(e)})")

        time.sleep(15)
        st.rerun()

else:
    st.warning("🔒 Enter Master Password in Sidebar to activate Mobile App Terminal.")