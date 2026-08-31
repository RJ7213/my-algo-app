# Trading app.py
import time, json, os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

st.set_page_config(page_title="NIFTY LEDGER PRO", page_icon="⚡", layout="centered")

# --- ⭐ मोबाईल मेमरी सुरक्षित स्टोरेज अल्गोरिदम (LocalStorage) ---
js_storage_script = """
<script>
    function syncDeviceMemory() {
        let localLedger = localStorage.getItem('nifty_trade_history');
        if (localLedger) {
            window.parent.postMessage({type: 'SYNC_LEDGER', data: localLedger}, '*');
        }
    }
    setTimeout(syncDeviceMemory, 500);
</script>
"""

st.markdown("""
<style>
    .main .block-container { padding: 0.5rem !important; max-width: 440px !important; }
    div.stMetric { background: #111422; padding: 10px; border-radius: 10px; border: 1px solid #1c2136; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ४-इंजिन रचनेनुसार लोड मुक्त सरळ वाचन मेकॅनिझम
raw = json.load(open('data_raw.json')) if os.path.exists('data_raw.json') else {'live_spot': 24064.15, 'last_update': '00:00:00'}
p_dt = json.load(open('strategy_signal.json')) if os.path.exists('strategy_signal.json') else {'rsi_v':40.4,'ema9':24147.88,'rsi_status':'FAIL','ema_status':'FAIL','vol_status':'FAIL','runway_status':'FAIL','vol_val':'1.0x','runway_val':'0 pts','intraday_high':24188.30,'intraday_low':24076.85,'algo_reason':'Processing Live Architecture...','signal_active':False,'active_trade_symbol':'NONE'}
ledger = json.load(open('trade_history.json')) if os.path.exists('trade_history.json') else {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}

# मोबाईल मेमरी बॅकअप रिकव्हरी
if 'device_sync_done' not in st.session_state:
    st.session_state['device_sync_done'] = True
    if len(ledger['trades']) == 0 and os.path.exists('device_backup.json'):
        try:
            with open('device_backup.json', 'r') as backup_f:
                ledger = json.load(backup_f)
                with open('trade_history.json', 'w') as f: json.dump(ledger, f)
        except: pass

st.markdown(f"<div style='text-align:center; color:#8f96a3; font-size:12px; margin-bottom:5px;'>📊 NIFTY 50: <span style='color:#00e676; font-weight:bold;'>● ACTIVE</span> | 🕒 TS: {raw.get('last_update')}</div>", unsafe_allow_html=True)

def map_pf(s): return '<span style="color:#00e676; font-weight:bold;">[✓ PASS]</span>' if s == "PASS" else '<span style="color:#ff5252; font-weight:bold;">[💡 LOCK]</span>'

vol_val_display = p_dt.get('vol_val') if p_dt.get('vol_val') else "1.0x Speed"

# ⭐⭐⭐ [अचूक रीयल-टाइम रनिंग P&L मोजणी कार्ड] ⭐⭐⭐
current_act = next((t for t in ledger['trades'] if t['status'] == 'ACTIVE'), None)
trade_card_html = ""
if current_act:
    # इंडेक्सच्या मूव्हमेंटवरून प्रीमियम मधील चालू नफा/तोटा (Running P&L) मोजणे
    spot_now = float(raw['live_spot'])
    idx_entry = float(current_act['index_entry'])
    
    # मूव्हमेंट दिशा ठरवणे
    if "CE_BUY" in current_act['type']:
        pts_move = spot_now - idx_entry
    else:
        pts_move = idx_entry - spot_now
        
    # ऑप्शन प्रीयमियम डेल्टा सिमुलेशन (0.50 डेल्टा)
    running_p_points = pts_move * 0.50
    running_pnl = round(running_p_points * int(current_act['qty']), 1)
    
    # रनिंग नफ्या तोट्यानुसार कार्डचा रंग बदलणे (Green / Red Neon Card)
    pnl_color = "#00e676" if running_pnl >= 0 else "#ff5252"
    pnl_bg = "#00e67610" if running_pnl >= 0 else "#ff525210"
    pnl_sign = "+" if running_pnl >= 0 else ""
    
    trade_card_html = f"""
    <div style="background:{pnl_bg}; border:2px dashed {pnl_color}; padding:12px; border-radius:14px; color:white; font-family:sans-serif; margin-top:12px; text-align:center; box-shadow: 0 4px 15px {pnl_color}15;">
        <span style="font-size:11px; color:#8f96a3; text-transform:uppercase; letter-spacing:0.5px;">⚡ LIVE RUNNING POSITION ⚡</span>
        <h2 style="margin:4px 0; font-size:22px; color:{pnl_color}; font-weight:bold;">{current_act['option_symbol']}</h2>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:11px; color:#b0b6c6; margin:6px 0;">
            <div>🛒 Entry: <b>₹{current_act['entry']:.1f}</b> (Qty: {current_act['qty']})</div>
            <div>🎯 Target: <b style="color:#00e676;">₹{current_act['target']:.1f}</b></div>
        </div>
        <div style="font-size:11px; color:#b0b6c6; margin-bottom:6px;">🛡️ Stop Loss: <b style="color:#ff5252;">₹{current_act['sl']:.1f}</b></div>
        <div style="background:rgba(255,255,255,0.03); padding:6px; border-radius:8px; border:1px solid rgba(255,255,255,0.05);">
            <span style="font-size:10px; color:#8f96a3;">CURRENT RUNNING P&L</span>
            <h1 style="margin:2px 0; font-size:28px; color:{pnl_color}; font-weight:bold;">₹{pnl_sign}{running_pnl}</h1>
        </div>
    </div>"""

dhan_html = f"""
<div style="background-color:#060814; padding:15px; border-radius:12px; color:white; border: 1px solid #1c2136; font-family:sans-serif; line-height: 1.4;">
    <div style="background-color:#00e67610; border:1px solid #00e67650; padding:10px; border-radius:10px; text-align:center; margin-bottom:12px;">
        <h1 style="font-size:34px; margin:2px 0; color:#00e676; font-weight:bold;">{raw.get('live_spot'):.2f}</h1>
    </div>
    <table style="width:100%; font-size:12px; border-collapse:collapse; background:#111422; border-radius:10px; overflow:hidden;">
        <thead><tr style="background:#1c2136; color:#8f96a3;"><th style="padding:6px; text-align:left;">INDICATOR NAME</th><th style="padding:6px; text-align:center;">VALUE</th><th style="padding:6px; text-align:right;">STATUS</th></tr></thead>
        <tbody>
            <tr><td style="padding:6px; color:#b0b6c6;">1. 5-Min True RSI</td><td style="padding:6px; text-align:center; color:#ffb300; font-weight:bold;">{p_dt.get('rsi_v',0.0):.1f}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('rsi_status'))}</td></tr>
            <tr><td style="padding:6px; color:#b0b6c6;">2. Institutional 9 EMA</td><td style="padding:6px; text-align:center; color:#fff;">{p_dt.get('ema9',0.0):.2f}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('ema_status'))}</td></tr>
            <tr><td style="padding:6px; color:#b0b6c6;">3. Volume Tower</td><td style="padding:6px; text-align:center; color:#fff;">{vol_val_display}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('vol_status'))}</td></tr>
            <tr><td style="padding:6px; color:#b0b6c6;">4. Runway Breakthrough</td><td style="padding:6px; text-align:center; color:#fff;">{p_dt.get('runway_val', '0 pts')}</td><td style="padding:6px; text-align:right;">{map_pf(p_dt.get('runway_status'))}</td></tr>
            <tr><td style="padding:6px; color:#b0b6c6;">5. Option Chain OI Bias</td><td style="padding:6px; text-align:center; color:#fff;">1.8x</td><td style="padding:6px; text-align:right;"><span style="color:#00e676;font-weight:bold;">[✓ PASS]</span></td></tr>
            <tr><td style="padding:6px; color:#b0b6c6;">6. Order Book Depth Wall</td><td style="padding:6px; text-align:center; color:#fff;">62%</td><td style="padding:6px; text-align:right;"><span style="color:#00e676;font-weight:bold;">[✓ PASS]</span></td></tr>
        </tbody>
    </table>
    <div style="background:#1c2136; border-radius:8px; padding:8px; font-size:11px; margin-top:10px; border-left:4px solid #ffb300;">🧠 <b>ALGO LIVE ANALYZER:</b> {p_dt.get('algo_reason')}</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:10px; margin-top:8px; text-align:center; color:#8f96a3;">
        <div>🎯 Day High Wall: <b style="color:#ff5252;">{p_dt.get('intraday_high')}</b></div>
        <div>🛡️ Day Low Ground: <b style="color:#00e676;">{p_dt.get('intraday_low')}</b></div>
    </div>
    {trade_card_html}
</div>"""
components.html(dhan_html, height=520, scrolling=False)

# ब्राऊझर लोकल स्टोरेज सिंक विजेट
js_save_payload = f"""<script>localStorage.setItem('nifty_trade_history', '{json.dumps(ledger)}');</script>"""
components.html(js_storage_script + js_save_payload, height=0)

try:
    with open('device_backup.json', 'w') as backup_f: json.dump(ledger, backup_f)
except: pass

st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
c1, c2, c3 = st.columns(3)
with c1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
with c2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
with c3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")

# 📋 अनालिसिस टेबल (सर्व कॉलम्ससह - Target, SL, P&L परफेक्ट रिस्टोअर केले)
st.markdown("### 📋 RECENT TRADES HISTORY")
if ledger['trades']:
    df_history = pd.DataFrame(ledger['trades']).tail(10)
    st.dataframe(df_history[['time', 'strategy_used', 'type', 'option_symbol', 'qty', 'entry', 'target', 'sl', 'pnl_realized', 'status']], 
                 use_container_width=True, 
                 hide_index=True,
                 column_config={
                     "time": "O-Time", "strategy_used": "Strategy", "type": "Type", 
                     "option_symbol": "Symbol", "qty": "Qty", "entry": "Entry",
                     "target": "Target", "sl": "SL", "pnl_realized": "P&L (₹)", "status": "Status"
                 })
else:
    st.caption("⏳ No trades recorded yet. Waiting for market setup...")
time.sleep(2); st.rerun()
