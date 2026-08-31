# Trading app.py
import time, json, os
import streamlit as st
import pandas as pd

st.set_page_config(page_title="NIFTY LEDGER PRO", page_icon="⚡", layout="centered")
st.markdown("<style>.main .block-container { padding: 0.5rem !important; max-width: 440px !important; }</style>", unsafe_allow_html=True)

raw = json.load(open('data_raw.json')) if os.path.exists('data_raw.json') else {'live_spot': 24064.15, 'last_update': '00:00:00'}
p_dt = json.load(open('strategy_signal.json')) if os.path.exists('strategy_signal.json') else {'rsi_v':40.4,'ema9':24147.88,'rsi_status':'FAIL','ema_status':'FAIL','vol_status':'FAIL','runway_status':'FAIL','vol_val':'1.0x','runway_val':'0 pts','intraday_high':24188.30,'intraday_low':24076.85,'algo_reason':'Processing Live Architecture...','signal_active':False,'active_trade_symbol':'NONE'}
ledger = json.load(open('trade_history.json')) if os.path.exists('trade_history.json') else {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}

st.info(f"📊 NIFTY 50: 🟢 Active | 🕒 TS: {raw.get('last_update')}")

st.markdown("### 🧮 VIRTUAL WALLET LEDGER")
c1, c2, c3 = st.columns(3)
with c1: st.metric("💰 Wallet Bal", f"₹{ledger['wallet_balance']:.1f}")
with c2: st.metric("🎯 Win Rate", f"{ledger['win_rate']}%")
with c3: st.metric("🏁 Total Trade", f"{ledger['total_trades']}")

st.markdown("### 📋 RECENT TRADES HISTORY")
if ledger['trades']:
    df_history = pd.DataFrame(ledger['trades']).tail(10)
    # डॅशबोर्डवर P&L आणि Strategy Used कॉलम जोडला आहे
    st.dataframe(df_history[['time', 'strategy_used', 'type', 'option_symbol', 'qty', 'entry', 'pnl_realized', 'status']], 
                 use_container_width=True, 
                 hide_index=True,
                 column_config={"time": "O-Time", "strategy_used": "Strategy", "type": "Type", "pnl_realized": "P&L (₹)"})
else:
    st.caption("⏳ No trades recorded yet. Waiting for market setup...")
time.sleep(2); st.rerun()
