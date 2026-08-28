# paper_engine.py
import time, json, os
import pandas as pd
from datetime import datetime, timedelta, time as datetime_time

def manage_ledger(new_t=None, update_pnl=None):
    f_name = 'trade_history.json'
    dt = {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    if os.path.exists(f_name):
        try:
            with open(f_name, 'r') as f: dt = json.load(f)
        except: pass
    if dt['wallet_balance'] < 5000.0: dt['wallet_balance'] = 10000.0  # १०,००० ऑटो-टॉपअप नियम [Claim]
    if new_t:
        dt['trades'].append(new_t); dt['total_trades'] = len(dt['trades'])
    if update_pnl:
        for t in dt['trades']:
            if t['status'] == 'ACTIVE':
                t['status'], t['exit_price'], t['pnl_realized'] = update_pnl['status'], update_pnl['exit_price'], update_pnl['pnl']
                dt['wallet_balance'] += update_pnl['pnl']
                if update_pnl['status'] == 'TARGET_HIT': dt['target_hits'] += 1
                elif update_pnl['status'] == 'SL_HIT': dt['sl_hits'] += 1
        if dt['total_trades'] > 0: dt['win_rate'] = round((dt['target_hits'] / dt['total_trades']) * 100, 1)
    with open(f_name, 'w') as f: json.dump(dt, f)
    return dt

def start_paper_engine():
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        is_open = (now_dt.weekday() < 5) and (datetime_time(9, 15) <= now_dt.time() <= datetime_time(15, 30))
        if not is_open or not os.path.exists('data_signal.json'):
            time.sleep(3); continue
        try:
            with open('data_signal.json', 'r') as f: data = json.load(f)
            hist = manage_ledger()
            spot, rsi_v, ema9 = data['live_spot'], data['rsi_v'], data['ema9']
            df = pd.DataFrame(data['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df_t = df[df['date'].astype(str).str.contains(now_dt.strftime("%Y-%m-%d"))].copy()
            high = float(df_t['high'].astype(float).max()) if not df_t.empty else 24297.45
            low = float(df_t['low'].astype(float).min()) if not df_t.empty else 24090.85
            
            act = next((t for t in hist['trades'] if t['status'] == 'ACTIVE'), None)
            if act:
                # 🏃 लाईव्ह ट्रेड ट्रॅकिंग (प्रीमियम ३० पॉईंट्स मॅनेजमेंट सिम्युलेटर)
                if spot >= act['index_target'] if act['type']=="CE_BUY" else spot <= act['index_target']:
                    manage_ledger(update_pnl={'status': 'TARGET_HIT', 'exit_price': act['target'], 'pnl': 30.0 * act['qty']})
                elif spot <= act['index_sl'] if act['type']=="CE_BUY" else spot >= act['index_sl']:
                    manage_trade_history(update_pnl={'status': 'SL_HIT', 'exit_price': act['sl'], 'pnl': -15.0 * act['qty']})
                reason, rsi_st, ema_st, vol_st, runway_st = "🏃 Jackpot Ride Active!", "LOCK", "LOCK", "LOCK", "LOCK"
                vol_ratio, run_df = 1.0, 0.0
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
                reason = f"⏸️ Side-ways (RSI: {rsi_v:.1f})" if ttype == "NONE" else f"🔍 Setup Formed for {ttype}"
                
                if all_p:
                    strike = int(round(spot / 50) * 50)
                    o_sym = f"NIFTY {strike} {'CE' if ttype=='CE_BUY' else 'PE'}"
                    # कडक १५ पॉईंट्सचा SL आणि जॅकपॉट ओपन टार्गेट लॉक [Claim]
                    manage_ledger(new_t={'time': now_dt.strftime("%H:%M:%S"), 'type': ttype, 'option_symbol': o_sym, 'option_token': "142500", 'entry': 100.0, 'sl': 85.0, 'target': 130.0, 'index_entry': spot, 'index_sl': spot-20 if ttype=="CE_BUY" else spot+20, 'index_target': next_w, 'qty': 75, 'status': 'ACTIVE', 'exit_price': 0.0, 'pnl_realized': 0.0})
                    reason = f"🎯 POSITION PUNCHED: {o_sym}"
            
            with open('paper_signal.json', 'w') as f:
                json.dump({'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st, 'runway_status': runway_st, 'vol_val': f"{vol_ratio}x SMA", 'runway_val': f"{run_df:.1f} pts", 'intraday_high': high, 'intraday_low': low, 'algo_reason': reason, 'signal_active': act is not None, 'active_trade_symbol': act['option_symbol'] if act else 'NONE'}, f)
        except: pass
        time.sleep(3)

if __name__ == "__main__": start_paper_engine()
