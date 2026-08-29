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
        logging.info("अकाउंट रिफिल केले (₹१०,००० वर).")
        
    if new_t:
        dt['trades'].append(new_t)
        dt['total_trades'] = len(dt['trades'])
    if update_pnl:
        for t in dt['trades']:
            if t['status'] == 'ACTIVE':
                t['status'] = update_pnl['status']
                t['exit_price'] = update_pnl['exit_price']
                t['pnl_realized'] = update_pnl['pnl']
                dt['wallet_balance'] += update_pnl['pnl']
                if update_pnl['status'] == 'TARGET_HIT': dt['target_hits'] += 1
                elif update_pnl['status'] == 'SL_HIT': dt['sl_hits'] += 1
        if dt['total_trades'] > 0:
            dt['win_rate'] = round((dt['target_hits'] / dt['total_trades']) * 100, 1)
            
    with open(f_name, 'w') as f: json.dump(dt, f)
    return dt

def start_paper_engine():
    logging.info("पेपर ट्रेडिंग इंजिन सुरू झाले...")
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
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
                elif is_ce_sl or is_pe_sl:
                    pnl_calc = float(-act['sl_dist'] * act['qty'])
                    manage_ledger(update_pnl={'status': 'SL_HIT', 'exit_price': act['sl'], 'pnl': pnl_calc})
            else:
                if strat.get('signal_triggered') and strat.get('otype') != "NONE":
                    strike = int(round(spot / 50.0) * 50)
                    o_sym = f"NIFTY {strike} {strat['otype']}"
                    
                    c_low_val = strat.get('c_low', spot - 15.0)
                    c_high_val = strat.get('c_high', spot + 15.0)
                    
                    idx_sl_dist = abs(spot - (c_low_val if strat['otype']=="CE" else c_high_val))
                    p_sl_dist = max(10.0, min(idx_sl_dist * 0.50, 25.0))
                    
                    # ⭐ कडक नियम: १५% मॅक्स ट्रेड रिस्क (₹१०,००० वर ₹१,५०० रिस्क लॉक)
                    max_allowed_risk = float(hist['wallet_balance'] * 0.15)
                    calculated_qty = int(max_allowed_risk / p_sl_dist)
                    
                    # ⭐ नवीन नियमानुसार ६५ च्या पटीत लॉट मोजणे
                    qty_final = int(calculated_qty / 65) * 65
                    if qty_final < 65: qty_final = 65 # मिनिमम १ लॉट (६५ Qty)
                    
                    p_entry = 100.0
                    p_sl = p_entry - p_sl_dist
                    premium_target_points = max(20.0, strat.get('run_df', 25.0) * 0.50)
                    p_targ = p_entry + premium_target_points
                    
                    # एकूण ट्रेड रिस्क १५% पेक्षा जास्त जात नसेल तरच ट्रेड घेणे
                    if (p_sl_dist * qty_final) <= (max_allowed_risk + 100.0):
                        manage_ledger(new_t={
                            'time': now_dt.strftime("%H:%M:%S"), 'type': strat['trade_type'], 
                            'option_symbol': o_sym, 'option_token': "142500", 'entry': p_entry, 
                            'sl': p_sl, 'target': p_targ, 'target_dist': premium_target_points, 'sl_dist': p_sl_dist,
                            'index_entry': spot, 'index_sl': c_low_val if strat['otype']=="CE" else c_high_val, 
                            'index_target': strat.get('next_w', spot + 30.0 if strat['otype']=="CE" else spot - 30.0), 
                            'qty': qty_final, 'status': 'ACTIVE', 'exit_price': 0.0, 'pnl_realized': 0.0
                        })
            
            hist_latest = manage_ledger()
            current_act = next((t for t in hist_latest['trades'] if t['status'] == 'ACTIVE'), None)
            
            with open('paper_signal.json', 'w') as f:
                json.dump({
                    'rsi_v': strat.get('rsi_v', 40.0), 'ema9': strat.get('ema9', spot),
                    'rsi_status': strat['rsi_status'], 'ema_status': strat['ema_status'], 
                    'vol_status': strat['vol_status'], 'runway_status': strat['runway_status'], 
                    'vol_val': strat['vol_val'], 'runway_val': strat['runway_val'], 
                    'intraday_high': strat['intraday_high'], 'intraday_low': strat['intraday_low'], 
                    'algo_reason': f"🚀 JACKPOT STRUCTURAL POSITION ACTIVE: {current_act['option_symbol']}!" if current_act else strat['algo_reason'], 
                    'signal_active': current_act is not None, 'active_trade_symbol': current_act['option_symbol'] if current_act else 'NONE'
                }, f)
        except Exception as e: pass
        time.sleep(2)

if __name__ == "__main__": start_paper_engine()
