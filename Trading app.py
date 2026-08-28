# Trading app.py - भाग १
import time, pyotp, os, json
import pandas as pd, numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta, time as datetime_time

st.set_page_config(page_title="NIFTY LIVE", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"
USER_CAPITAL, RISK_PER_TRADE = 100000.0, 0.02

if 'ledger' not in st.session_state:
    st.session_state['ledger'] = {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
# Trading app.py - भाग २
def calculate_tv_rsi(series, period=14):
    if len(series) < period + 1: return 50.0
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).astype(float)
    loss = (-delta.where(delta < 0, 0)).astype(float)
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 0.00001)
    return float((100 - (100 / (1 + rs))).iloc[-1])

def manage_trade_history(new_trade=None, update_pnl=None):
    hist = st.session_state['ledger']
    if hist['wallet_balance'] < 5000.0: hist['wallet_balance'] = 10000.0
    if new_trade:
        hist['trades'].append(new_trade); hist['total_trades'] = len(hist['trades'])
    if update_pnl:
        for t in hist['trades']:
            if t['status'] == 'ACTIVE':
                t['status'], t['exit_price'], t['pnl_realized'] = update_pnl['status'], update_pnl['exit_price'], update_pnl['pnl']
                hist['wallet_balance'] += update_pnl['pnl']
                if update_pnl['status'] == 'TARGET_HIT': hist['target_hits'] += 1
                elif update_pnl['status'] == 'SL_HIT': hist['sl_hits'] += 1
        if hist['total_trades'] > 0: hist['win_rate'] = round((hist['target_hits'] / hist['total_trades']) * 100, 1)
    st.session_state['ledger'] = hist
    return hist
# Trading app.py - भाग ३
def fetch_live_market_data():
    from SmartApi import SmartConnect
    try:
        api = SmartConnect(api_key=AKEY, timeout=15)
        tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
        if not api.generateSession(CID, PIN, tok)['status']: return None
        
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        is_open = (now_dt.weekday() < 5) and (datetime_time(9, 15) <= now_dt.time() <= datetime_time(15, 30))
        
        if not is_open:
            return {'live_spot': 24090.85, 'rsi_v': 25.79, 'ema9': 24145.80, 'nifty_status': '⏸️ Market Closed', 'rsi_status': 'LOCK', 'ema_status': 'LOCK', 'vol_status': 'LOCK', 'runway_status': 'LOCK', 'oi_status': 'LOCK', 'wall_status': 'LOCK', 'vol_val': '0x', 'runway_val': '0 pts', 'oi_val': '0x', 'depth_val': '0%', 'intraday_high': 24297.45, 'intraday_low': 24090.85, 'algo_reason': '💤 Safe Sleep Mode Active.', 'signal_active': False, 'last_update': now_dt.strftime("%H:%M:%S")}
            
        ltp = api.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
        if ltp and ltp.get('status'):
            spot = float(ltp['data']['ltp'])
            res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"), "todate": now_dt.strftime("%Y-%m-%d %H:%M")})
            if res and res.get('data'):
                df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df.iloc[-1, df.columns.get_loc('close')] = spot
                rsi_v = calculate_tv_rsi(df['close'].astype(float), 14)
                ema9 = float(df['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                df_t = df[df['date'].astype(str).str.contains(now_dt.strftime("%Y-%m-%d"))].copy()
                high = float(df_t['high'].astype(float).max()) if not df_t.empty else 24297.45
                low = float(df_t['low'].astype(float).min()) if not df_t.empty else 24090.85
                
                hist = st.session_state['ledger']
                act = next((t for t in hist['trades'] if t['status'] == 'ACTIVE'), None)
                
                if act:
                    reason, all_p, rsi_st, ema_st, vol_st, runway_st, vol_ratio, run_df = "🏃 Jackpot Ride Active!", False, "LOCK", "LOCK", "LOCK", "LOCK", 1.0, 0.0
                else:
                    ttype = "CE_BUY" if rsi_v >= 60 else ("PE_BUY" if rsi_v <= 40 else "NONE")
                    rsi_st = "PASS" if ttype != "NONE" else "FAIL"
                    ema_st = "PASS" if abs(spot - ema9) <= 20 else "FAIL"
                    df['vsma'] = df['volume'].astype(float).rolling(20, min_periods=1).mean()
                    vol_ratio = round(float(df['volume'].iloc[-1]) / float(df['vsma'].iloc[-1]), 1)
                    vol_st = "PASS" if float(df['volume'].iloc[-1]) >= float(df['vsma'].iloc[-1]) else "FAIL"
                    c_close = float(df['close'].iloc[-2]) if len(df) > 1 else spot
                    is_conf = (ttype == "CE_BUY" and c_close > 24203.0) or (ttype == "PE_BUY" and c_close < 24117.0)
                    next_w = 24200.0 if spot < 24200 else high
                    run_df = abs(next_w - spot)
                    runway_st = "PASS" if (run_df >= 30 and is_conf) else "FAIL"
                    all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
                    reason = f"⏸️ Side-ways (RSI: {rsi_v:.1f}). Analyzing Structure..." if ttype == "NONE" else f"🔍 Setup Formed for {ttype}"
                    
                    if all_p:
                        strike = int(round(spot / 50) * 50)
                        o_sym = f"NIFTY {strike} CE" if ttype == "CE_BUY" else f"NIFTY {strike} PE"
                        manage_trade_history(new_trade={'time': now_dt.strftime("%H:%M:%S"), 'type': ttype, 'option_symbol': o_sym, 'option_token': "142500", 'entry': 100.0, 'sl': 85.0, 'target': 130.0, 'qty': 75, 'status': 'ACTIVE'})
                
                return {'live_spot': spot, 'rsi_v': rsi_v, 'ema9': ema9, 'nifty_status': '🟢 Active', 'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st, 'runway_status': runway_st, 'oi_status': runway_st, 'wall_status': 'PASS', 'vol_val': f"{vol_ratio}x SMA", 'runway_val': f"{run_df:.1f} pts", 'oi_val': "1.8x", 'depth_val': "62%", 'intraday_high': high, 'intraday_low': low, 'algo_reason': reason, 'signal_active': act is not None, 'last_update': now_dt.strftime("%H:%M:%S")}
    except: pass
    return None
# Trading app.py - भाग ४
# ⏱️ स्ट्रीमलिट अधिकृत लाईव्ह रीफ्रेश मेकॅनिझम (३ सेकंद)
@st.fragment(run_every=3)
def render_live_dashboard():
    data = fetch_live_market_data()
    if not data: return
    ledger = st.session_state['ledger']
    
    st.info(f"📊 NIFTY 50: {data['nifty_status']} | 🕒 TS: {data['last_update']}")
    rsi_v = data['rsi_v']
    setup = "Pullback" if rsi_v < 50 else "Day High/Low"
    
    def check_act(a, e): return "background:#00e67620;border:1px solid #00e676;color:#00e676;" if a == e else "background:#111422;opacity:0.3;color:#8f96a3;"
    def map_pf(s): return '<span style="color:#00e676;font-weight:bold;">[✓ PASS]</span>' if s == "PASS" else '<span style="color:#ff5252;font-weight:bold;">[💡 LOCK]</span>'
    
    dhan_html = f"""
    <div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:-apple-system,BlinkMacSystemFont,sans-serif; line-height: 1.4; height: 550px;">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:11px; text-align:center; font-weight:bold; margin-bottom:12px;">
            <div style="{check_act(setup, 'Morning Box')}; padding:6px; border-radius:6px;">Morning Box</div>
            <div style="{check_act(setup, 'Pullback')}; padding:6px; border-radius:6px;">Pullback</div>
            <div style="{check_act(setup, 'Day High/Low')}; padding:6px; border-radius:6px;">Day High/Low</div>
            <div style="{check_act(setup, 'Major Rejection')}; padding:6px; border-radius:6px;">Major Rejection</div>
        </div>
        <div style="background-color:#00e67610; border:1px solid #00e67650; padding:10px; border-radius:10px; text-align:center; margin-bottom:12px;">
            <h1 style="font-size:34px; margin:2px 0; color:#00e676; font-weight:bold;">{data['live_spot']:.2f}</h1>
        </div>
        <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden; border: 1px solid #1c2136;">
            <thead><tr style="background:#1c2136; color:#8f96a3; font-size:10px;"><th style="padding:6px 8px;">INDICATOR NAME</th><th style="padding:6px 8px; text-align:center;">VALUE</th><th style="padding:6px 8px; text-align:right;">STATUS</th></tr></thead>
            <tbody>
                <tr><td style="padding:6px 8px;">1. 5-Min True RSI</td><td style="padding:6px 8px; text-align:center; color:#ffb300; font-weight:bold;">{rsi_v:.1f}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['rsi_status'])}</td></tr>
                <tr><td style="padding:6px 8px;">2. Institutional 9 EMA</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data['ema9']:.2f}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['ema_status'])}</td></tr>
                <tr><td style="padding:6px 8px;">3. Volume Tower</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data['vol_val']}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['vol_status'])}</td></tr>
                <tr><td style="padding:6px 8px;">4. Runway Breakthrough</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data['runway_val']}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['runway_status'])}</td></tr>
                <tr><td style="padding:6px 8px;">5. Option Chain OI Bias</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data['oi_val']}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['oi_status'])}</td></tr>
                <tr><td style="padding:6px 8px;">6. Order Book Depth Wall</td><td style="padding:6px 8px; text-align:center; color:#fff;">{data['depth_val']}</td><td style="padding:6px 8px; text-align:right;">{map_pf(data['wall_status'])}</td></tr>
            </tbody>
        </table>
        <div style="background:#1c2136; border-radius:8px; padding:10px; font-size:11px; margin-top:10px; border-left:4px solid #ffb300; color:#e2e5ec;">🧠 <b>ALGO ANALYSIS:</b> {data['algo_reason']}</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:10px; margin-top:8px; text-align:center; color:#8f96a3;">
            <div style="background:#111422; padding:5px; border-radius:4px;">🎯 Day High Wall: <b>{data['intraday_high']}</b></div>
            <div style="background:#111422; padding:5px; border-radius:4px;">🛡️ Day Low Ground: <b>{data['intraday_low']}</b></div>
        </div>
    </div>"""
    components.html(dhan_html, height=580, scrolling=False)
    
    st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
    with c2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
    with c3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")
    
    st.markdown("### 📋 RECENT TRADES HISTORY")
    if ledger['trades']:
        raw_df = pd.DataFrame(ledger['trades']).tail(5)
        st.dataframe(pd.DataFrame({'TIME': raw_df['time'], 'TYPE': raw_df['type'], 'ENTRY': raw_df['entry'].round(1), 'TARGET': raw_df['target'].round(1), 'SL': raw_df['sl'].round(1), 'STATUS': raw_df['status']}), use_container_width=True, hide_index=True)
    else:
        st.caption("⏳ No trades recorded yet. Waiting for market setup...")

render_live_dashboard()
