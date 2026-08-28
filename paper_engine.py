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
    if dt['wallet_balance'] < 5000.0: dt['wallet_balance'] = 10000.0
    if new_t: dt['trades'].append(new_t); dt['total_trades'] = len(dt['trades'])
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
            time.sleep(1); continue
        try:
            with open('data_signal.json', 'r') as f: data = json.load(f)
            hist = manage_ledger()
            spot, rsi_v, ema9 = data['live_spot'], data['rsi_v'], data['ema9']
            
            df = pd.DataFrame(data['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['date'].astype(str).str.contains(today_str)].copy()
            
            high = float(df_t['high'].astype(float).max()) if not df_t.empty else 24188.30
            low = float(df_t['low'].astype(float).min()) if not df_t.empty else 24076.85
            
            act = next((t for t in hist['trades'] if t['status'] == 'ACTIVE'), None)
            if act:
                if spot >= act['index_target'] if act['type']=="CE_BUY" else spot <= act['index_target']:
                    manage_ledger(update_pnl={'status': 'TARGET_HIT', 'exit_price': act['target'], 'pnl': 30.0 * act['qty']})
                elif spot <= act['index_sl'] if act['type']=="CE_BUY" else spot >= act['index_sl']:
                    manage_ledger(update_pnl={'status': 'SL_HIT', 'exit_price': act['sl'], 'pnl': -15.0 * act['qty']})
                reason, rsi_st, ema_st, vol_st, runway_st = f"🏃 Jackpot Riding: {act['option_symbol']}", "LOCK", "LOCK", "LOCK", "LOCK"
                vol_ratio, run_df = 1.0, 0.0
            else:
                # 🧱 ५० आणि १०० च्या सायकॉलॉजिकल लेव्हल्स लाईव्ह शोधणे
                psy_level = int(round(spot / 50) * 50)
                
                # 💎 कँडल शेंडी विश्लेषण (Wick Analysis Filter) [Claim]
                c_open, c_close, c_high, c_low = float(df['open'].iloc[-2]), float(df['close'].iloc[-2]), float(df['high'].iloc[-2]), float(df['low'].iloc[-2])
                c_size = abs(c_high - c_low)
                top_wick = c_high - max(c_open, c_close)
                bot_wick = min(c_open, c_close) - c_low
                
                # 🚨 सेटअप डिटेक्टर इंजिन (३ सिस्टीम ट्रॅकर) [Claim]
                is_rejection = (abs(c_high - psy_level) <= 8 and top_wick >= (c_size * 0.5)) or (abs(c_low - psy_level) <= 8 and bot_wick >= (c_size * 0.5))
                is_pullback = (spot < 24190.0) and not is_rejection
                
                if is_rejection:
                    # सायकॉलॉजिकल लेव्हलवरून मोठी शेंडी बनवून फिरल्यास कडक रिव्हर्सल ट्रेड [Claim]
                    otype = "PE" if top_wick > bot_wick else "CE"
                    rsi_st = "PASS" # रिजेक्शनला आरएसआय अट शिथिल [Claim]
                    setup_name = "Major Rejection"
                elif is_pullback:
                    otype = "PE" if spot < ema9 else "CE"
                    rsi_st = "PASS" if (30<=rsi_v<=55) else "FAIL"
                    setup_name = "Pullback"
                else:
                    otype = "CE" if rsi_v >= 60 else ("PE" if rsi_v <= 40 else "NONE")
                    rsi_st = "PASS" if otype != "NONE" else "FAIL"
                    setup_name = "Breakout"
                
                ttype = f"{otype}_BUY" if otype != "NONE" else "NONE"
                
                # ९ EMA मॅपिंग
                ema_dist = abs(spot - ema9)
                if is_rejection: ema_st = "PASS" # रिजेक्शनला ईएमए अंतर ब्लॉक मुक्त [Claim]
                else:
                    if otype == "CE": ema_st = "PASS" if (spot>=(ema9-3) and ema_dist<=22) else "FAIL"
                    elif otype == "PE": ema_st = "PASS" if (spot<=(ema9+3) and ema_dist<=22) else "FAIL"
                    else: ema_st = "FAIL"
                
                df['vsma'] = df['volume'].astype(float).rolling(20, min_periods=1).mean()
                vol_ratio = round(float(df['volume'].iloc[-1]) / float(df['vsma'].iloc[-1]), 1)
                vol_st = "PASS" if float(df['volume'].iloc[-1]) >= float(df['vsma'].iloc[-1]) else "FAIL"
                
                # रनवे अंतर हिशोब
                next_w = high if otype == "CE" else low
                if is_rejection: next_w = low if otype == "PE" else high # थेट मागच्या सपोर्ट/हाय पर्यंत ओपन रनवे [Claim]
                run_df = abs(next_w - spot)
                runway_st = "PASS" if (run_df >= 25) else "FAIL"
                
                all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
                reason = f"⏸️ Analysing {setup_name} near {psy_level} (True Runway: {run_df:.1f} pts)"
                
                if all_p:
                    strike = int(round(spot / 50) * 50)
                    o_sym = f"NIFTY {strike} {otype}"
                    manage_ledger(new_t={'time': now_dt.strftime("%H:%M:%S"), 'type': ttype, 'option_symbol': o_sym, 'option_token': "142500", 'entry': 100.0, 'sl': 85.0, 'target': 130.0, 'index_entry': spot, 'index_sl': spot-20 if otype=="CE" else spot+20, 'index_target': next_w, 'qty': 75, 'status': 'ACTIVE', 'exit_price': 0.0, 'pnl_realized': 0.0})
                    reason = f"🎯 {setup_name.upper()} TRIGGERED! Selected ATM: {o_sym}"
            
            with open('paper_signal.json', 'w') as f:
                json.dump({'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st, 'runway_status': runway_st, 'vol_val': f"{vol_ratio}x SMA", 'runway_val': f"{run_df:.1f} pts", 'intraday_high': high, 'intraday_low': low, 'algo_reason': reason, 'signal_active': act is not None, 'active_trade_symbol': act['option_symbol'] if act else 'NONE'}, f)
        except: pass
        time.sleep(2)

if __name__ == "__main__": start_paper_engine()
