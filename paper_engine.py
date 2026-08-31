# paper_engine.py
import time, json, os, logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def manage_ledger(new_t=None, update_pnl=None):
    f_name = 'trade_history.json'
    dt = {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    if os.path.exists(f_name):
        try:
            with open(f_name, 'r') as f: dt = json.load(f)
        except: pass
        
    if dt.get('wallet_balance', 10000.0) < 5000.0:
        dt['wallet_balance'] = 10000.0
        
    if new_t:
        dt['trades'].append(new_t)
        dt['total_trades'] = len(dt['trades'])
    if update_pnl:
        for t in dt['trades']:
            if t['status'] == 'ACTIVE':
                t['status'] = update_pnl['status']
                t['exit_price'] = update_pnl['exit_price']
                t['pnl_realized'] = round(update_pnl['pnl'], 1)
                dt['wallet_balance'] = round(dt['wallet_balance'] + update_pnl['pnl'], 1)
                if update_pnl['status'] == 'TARGET_HIT': dt['target_hits'] += 1
                elif update_pnl['status'] == 'SL_HIT': dt['sl_hits'] += 1
        if dt['total_trades'] > 0:
            dt['win_rate'] = round((dt['target_hits'] / dt['total_trades']) * 100, 1)
            
    with open(f_name, 'w') as f: json.dump(dt, f)
    return dt

def start_paper_engine():
    # ओव्हर-ट्रेडिंग रोखण्यासाठी लास्ट ट्रेड कँडल टाईम ट्रॅक करणे
    last_processed_candle = "" 
    while True:
        if not os.path.exists('strategy_signal.json'):
            time.sleep(1); continue
        try:
            with open('strategy_signal.json', 'r') as f: strat = json.load(f)
            hist = manage_ledger()
            spot = float(strat['live_spot'])
            
            act = next((t for t in hist['trades'] if t['status'] == 'ACTIVE'), None)
            
            if act:
                is_ce_target = (act['type'] == "CE_BUY" and spot >= act['index_target'])
                is_pe_target = (act['type'] == "PE_BUY" and spot <= act['index_target'])
                is_ce_sl = (act['type'] == "CE_BUY" and spot <= act['index_sl'])
                is_pe_sl = (act['type'] == "PE_BUY" and spot >= act['index_sl'])
                
                if is_ce_target or is_pe_target:
                    pnl_calc = float(act['target_dist'] * act['qty'])
                    manage_ledger(update_pnl={'status': 'TARGET_HIT', 'exit_price': act['target'], 'pnl': pnl_calc})
                    last_processed_candle = act['candle_time'] # या कँडलचा ट्रेड संपला
                elif is_ce_sl or is_pe_sl:
                    pnl_calc = float(-act['sl_dist'] * act['qty'])
                    manage_ledger(update_pnl={'status': 'SL_HIT', 'exit_price': act['sl'], 'pnl': pnl_calc})
                    last_processed_candle = act['candle_time'] # या कँडलचा ट्रेड संपला
            else:
                # ⭐ नियम: जर या ५ मिनिटांच्या कँडलमध्ये आधीच ट्रेड झाला असेल, तर पुन्हा ट्रेड घ्यायचा नाही!
                if strat.get('signal_triggered') and strat.get('candle_time') != last_processed_candle:
                    strike = int(round(spot / 50.0) * 50)
                    o_sym = f"NIFTY {strike} {strat['otype']}"
                    
                    idx_sl_dist = abs(spot - (strat.get('c_low', spot-15) if strat['otype']=="CE" else strat.get('c_high', spot+15)))
                    p_sl_dist = max(10.0, min(idx_sl_dist * 0.50, 25.0))
                    
                    max_allowed_risk = float(hist['wallet_balance'] * 0.15)
                    qty_final = max(65, int((max_allowed_risk / p_sl_dist) / 65) * 65)
                    
                    p_entry = 100.0
                    premium_target_points = max(20.0, strat.get('run_df', 25.0) * 0.50)
                    
                    manage_ledger(new_t={
                        'time': datetime.utcnow().add(hours=5, minutes=30).strftime("%H:%M:%S") if hasattr(datetime.utcnow(), 'add') else (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S"), 
                        'type': strat['trade_type'], 'option_symbol': o_sym, 'entry': p_entry, 
                        'sl': p_entry - p_sl_dist, 'target': p_entry + premium_target_points, 
                        'target_dist': premium_target_points, 'sl_dist': p_sl_dist,
                        'index_entry': spot, 'index_sl': strat['c_low'] if strat['otype']=="CE" else strat['c_high'], 
                        'index_target': strat['next_w'], 'qty': qty_final, 'status': 'ACTIVE', 
                        'pnl_realized': 0.0, 'strategy_used': strat['strategy_used'], 'candle_time': strat['candle_time']
                    })
        except Exception as e: pass
        time.sleep(2)

if __name__ == "__main__": start_paper_engine()
