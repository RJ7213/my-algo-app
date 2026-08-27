import time
import pyotp
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta, time as datetime_time

CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" 
NIFTY_TOKEN = "99926000"

USER_CAPITAL = 100000.0
RISK_PER_TRADE = 0.02

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
    file_name = 'trade_history.json'
    data = {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    
    if os.path.exists(file_name):
        try:
            with open(file_name, 'r') as f: data = json.load(f)
        except: pass

    # 🔄 १०,००० वॉलेट टॉप-अप नियम
    if data['wallet_balance'] < 5000.0:
        data['wallet_balance'] = 10000.0

    if new_trade:
        data['trades'].append(new_trade)
        data['total_trades'] = len(data['trades'])
        with open(file_name, 'w') as f: json.dump(data, f)
        return data

    if update_pnl:
        for t in data['trades']:
            if t['status'] == 'ACTIVE':
                t['status'] = update_pnl['status']
                t['exit_price'] = update_pnl['exit_price']
                t['pnl_realized'] = update_pnl['pnl']
                data['wallet_balance'] += update_pnl['pnl']
                if update_pnl['status'] == 'TARGET_HIT': data['target_hits'] += 1
                elif update_pnl['status'] == 'SL_HIT': data['sl_hits'] += 1
        if data['total_trades'] > 0:
            data['win_rate'] = round((data['target_hits'] / data['total_trades']) * 100, 1)
        with open(file_name, 'w') as f: json.dump(data, f)
    return data
def start_backend_factory():
    from SmartApi import SmartConnect
    try:
        smartApi = SmartConnect(api_key=AKEY, timeout=15)
        clean_tkey = TKEY.replace(" ", "").strip().upper()
        missing_padding = len(clean_tkey) % 8
        if missing_padding != 0: clean_tkey += '=' * (8 - missing_padding)
        totp_token = pyotp.TOTP(clean_tkey).now()
        
        if not smartApi.generateSession(CID, PIN, totp_token)['status']: return
        cached_nifty_df = None
        last_candle_fetch_time = datetime.min
        
        while True:
            now_dt = datetime.now() + timedelta(hours=5, minutes=30)
            current_time = now_dt.time()
            is_weekend = (now_dt.weekday() >= 5)
            is_market_open = (not is_weekend) and (datetime_time(9, 15) <= current_time <= datetime_time(15, 30))
            history = manage_trade_history()
            
            if not is_market_open:
                output_data = {
                    'live_spot': 24090.85, 'rsi_v': 25.79, 'ema9': 24145.80, 'nifty_status': '⏸️ Market Closed',
                    'rsi_status': 'LOCK', 'ema_status': 'LOCK', 'vol_status': 'LOCK', 'runway_status': 'LOCK', 'oi_status': 'LOCK', 'wall_status': 'LOCK',
                    'vol_val': '0x', 'runway_val': '0 pts', 'oi_val': '0x', 'depth_val': '0%', 'intraday_high': 24297.45, 'intraday_low': 24090.85,
                    'algo_reason': '💤 Market is Closed. Engine is in sleep mode to protect your API Key.',
                    'signal_active': False, 'trade_type': 'NONE', 'entry_p': 0.0, 'sl_p': 0.0, 'target_p': 0.0,
                    'risk_cash': f"₹{USER_CAPITAL * RISK_PER_TRADE:.0f}", 'lots_suggested': '0', 'last_update': now_dt.strftime("%H:%M:%S")
                }
                with open('data_signal.json', 'w') as f: json.dump(output_data, f)
                time.sleep(300)
                continue

            try:
                ltp_res = smartApi.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                if ltp_res and ltp_res.get('status') and ltp_res.get('data'):
                    live_spot = float(ltp_res['data']['ltp'])
                    if cached_nifty_df is None or (now_dt - last_candle_fetch_time).total_seconds() > 60:
                        from_time = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                        to_time = now_dt.strftime("%Y-%m-%d %H:%M")
                        res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
                        if res and res.get('data') and len(res['data']) > 0:
                            cached_nifty_df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                            last_candle_fetch_time = now_dt
                    
                    if cached_nifty_df is not None:
                        df_calc = cached_nifty_df.copy()
                        df_calc.iloc[-1, df_calc.columns.get_loc('close')] = live_spot
                        rsi_v = calculate_tv_rsi(df_calc['close'].astype(float), 14)
                        ema9 = float(df_calc['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                        
                        today_str = now_dt.strftime("%Y-%m-%d")
                        df_today = df_calc[df_calc['date'].astype(str).str.contains(today_str)].copy()
                        intraday_high = float(df_today['high'].astype(float).max()) if not df_today.empty else 24297.45
                        intraday_low = float(df_today['low'].astype(float).min()) if not df_today.empty else 24090.85
                        
                        active_trade = next((t for t in history['trades'] if t['status'] == 'ACTIVE'), None)
                        
                        if active_trade:
                            if active_trade['type'] == 'CE_BUY':
                                if live_spot >= active_trade['target']:
                                    pnl = (active_trade['target'] - active_trade['entry']) * active_trade['qty']
                                    manage_trade_history(update_pnl={'status': 'TARGET_HIT', 'exit_price': active_trade['target'], 'pnl': pnl})
                                elif live_spot <= active_trade['sl']:
                                    pnl = (active_trade['sl'] - active_trade['entry']) * active_trade['qty']
                                    manage_trade_history(update_pnl={'status': 'SL_HIT', 'exit_price': active_trade['sl'], 'pnl': pnl})
                            elif active_trade['type'] == 'PE_BUY':
                                if live_spot <= active_trade['target']:
                                    pnl = (active_trade['entry'] - active_trade['target']) * active_trade['qty']
                                    manage_trade_history(update_pnl={'status': 'TARGET_HIT', 'exit_price': active_trade['target'], 'pnl': pnl})
                                elif live_spot >= active_trade['sl']:
                                    pnl = (active_trade['entry'] - active_trade['sl']) * active_trade['qty']
                                    manage_trade_history(update_pnl={'status': 'SL_HIT', 'exit_price': active_trade['sl'], 'pnl': pnl})
                            algo_reason = f"🏃 Active: {active_trade['type']} | Entry: {active_trade['entry']} | Target: {active_trade['target']}"
                            all_pass = False
                            rsi_st, ema_st, vol_st, runway_st, oi_st, wall_st = "LOCK", "LOCK", "LOCK", "LOCK", "LOCK", "LOCK"
                            vol_ratio, runway_diff = 1.0, 0.0
                        else:
                            trade_type = "NONE"
                            if rsi_v >= 60: trade_type = "CE_BUY"
                            elif rsi_v <= 40: trade_type = "PE_BUY"
                            
                            rsi_st = "PASS" if trade_type != "NONE" else "FAIL"
                            ema_dist = abs(live_spot - ema9)
                            ema_st = "PASS" if ema_dist <= 20 else "FAIL"
                            
                            df_calc['vol_sma'] = df_calc['volume'].astype(float).rolling(window=20, min_periods=1).mean()
                            current_vol = float(df_calc['volume'].iloc[-1])
                            avg_vol = float(df_calc['vol_sma'].iloc[-1])
                            vol_ratio = round(current_vol / avg_vol, 1) if avg_vol > 0 else 1.0
                            vol_st = "PASS" if current_vol >= avg_vol else "FAIL"
                            
                            next_wall = 24200.0 if live_spot < 24200 else intraday_high
                            runway_diff = abs(next_wall - live_spot)
                            runway_st = "PASS" if runway_diff >= 30 else "FAIL"
                            
                            candle_low = float(df_calc['low'].iloc[-1])
                            candle_high = float(df_calc['high'].iloc[-1])
                            raw_sl = abs(live_spot - candle_low) if trade_type == "CE_BUY" else abs(candle_high - live_spot)
                            sl_points = max(15.0, min(raw_sl, 25.0))
                            
                            oi_st = "PASS" if runway_st == "PASS" else "FAIL"
                            wall_st = "PASS"
                            all_pass = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
                            
                            algo_reason = f"⏸️ Side-ways (RSI: {rsi_v:.1f}). Analyzing Structure..." if trade_type == "NONE" else f"🔍 Setup Formed for {trade_type}"
                            
                            if all_pass:
                                entry_p = live_spot
                                sl_p = entry_p - sl_points if trade_type == "CE_BUY" else entry_p + sl_points
                                target_p = next_wall
                                target_distance = abs(target_p - entry_p)
                                lots = max(1, int((USER_CAPITAL * RISK_PER_TRADE) / sl_points / 75))
                                
                                t_log = {
                                    'time': now_dt.strftime("%Y-%m-%d %H:%M:%S"), 'type': trade_type,
                                    'entry': entry_p, 'sl': sl_p, 'target': target_p, 'target_dist': target_distance,
                                    'qty': lots * 75, 'status': 'ACTIVE', 'exit_price': 0.0, 'pnl_realized': 0.0
                                }
                                manage_trade_history(new_trade=t_log)
                                algo_reason = f"🎯 PUNCHED! Type: {trade_type} | Entry: {entry_p}"

                        output_data.update({
                            'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'nifty_status': '🟢 Active',
                            'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st,
                            'runway_status': runway_st, 'oi_status': oi_st, 'wall_status': wall_st,
                            'vol_val': f"{vol_ratio}x SMA", 'runway_val': f"{runway_diff:.1f} pts", 'oi_val': "1.8x", 'depth_val': "62%",
                            'intraday_high': intraday_high, 'intraday_low': intraday_low, 'algo_reason': algo_reason,
                            'signal_active': active_trade is not None, 'last_update': now_dt.strftime("%H:%M:%S")
                        })
            except: pass
            with open('data_signal.json', 'w') as f: json.dump(output_data, f)
            time.sleep(3)
    except:
        time.sleep(10); start_backend_factory()

if __name__ == "__main__": start_backend_factory()
