# paper_engine.py - भाग १
import time, json, os
from datetime import datetime, timedelta

def manage_ledger(new_t=None, update_pnl=None):
    f_name = 'trade_history.json'
    dt = {'wallet_balance': 10000.0, 'trades': [], 'total_trades': 0, 'target_hits': 0, 'sl_hits': 0, 'win_rate': 0.0}
    if os.path.exists(f_name):
        try:
            with open(f_name, 'r') as f: dt = json.load(f)
        except: pass
        
    # 🔄 कडक मेमरी नियम: वॉलेट ५,००० च्या खाली गेल्यास आपोआप १०,००० वर टॉप-अप करणे [Claim]
    if dt['wallet_balance'] < 5000.0:
        dt['wallet_balance'] = 10000.0
        
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
# paper_engine.py - भाग २
def start_paper_engine():
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if not os.path.exists('strategy_signal.json'):
            time.sleep(1); continue
        try:
            with open('strategy_signal.json', 'r') as f: strat = json.load(f)
            hist = manage_ledger()
            spot = strat['live_spot']
            
            act = next((t for t in hist['trades'] if t['status'] == 'ACTIVE'), None)
            
            if act:
                if spot >= act['index_target'] if act['type']=="CE_BUY" else spot <= act['index_target']:
                    pnl_calc = act['target_dist'] * act['qty']
                    manage_ledger(update_pnl={'status': 'TARGET_HIT', 'exit_price': act['target'], 'pnl': pnl_calc})
                elif spot <= act['index_sl'] if act['type']=="CE_BUY" else spot >= act['index_sl']:
                    pnl_calc = -act['sl_dist'] * act['qty']
                    manage_ledger(update_pnl={'status': 'SL_HIT', 'exit_price': act['sl'], 'pnl': pnl_calc})
            else:
                if strat['signal_triggered']:
                    strike = int(round(spot / 50) * 50)
                    o_sym = f"NIFTY {strike} {strat['otype']}"
                    
                    # 💎 कडक नियम: मार्केट स्ट्रक्चरनुसार इंडेक्स कँडलवरून प्रीमियम एसएल अंतर मोजणे [Claim]
                    idx_sl_dist = abs(spot - (strat['c_low'] if strat['otype']=="CE" else strat['c_high']))
                    p_sl_dist = max(10.0, min(idx_sl_dist * 0.50, 25.0)) # ऑप्शन प्रीमियम स्ट्रक्चरल एसएल [Claim]
                    
                    # 🚨 २% कॅपिटल कॅप लॉक नियम (₹१०,000 वॉलेटनुसार मॅक्स ₹२०० रिस्क) [Claim]
                    max_allowed_risk = hist['wallet_balance'] * 0.02
                    calculated_qty = int(max_allowed_risk / p_sl_dist)
                    qty_final = max(75, int(calculated_qty / 75) * 75) # कमीत कमी १ लॉट (७५ Qty)
                    
                    p_entry = 100.0
                    p_sl = p_entry - p_sl_dist
                    premium_target_points = max(30.0, strat['run_df'] * 0.50)
                    p_targ = p_entry + premium_target_points
                    
                    # जर एकूण ट्रेड रिस्क २% पेक्षा जास्त जात असेल तर ट्रेड फिल्टर लॉक करणे [Claim]
                    if (p_sl_dist * qty_final) <= (max_allowed_risk + 50.0):
                        manage_ledger(new_t={
                            'time': now_dt.strftime("%H:%M:%S"), 'type': strat['trade_type'], 
                            'option_symbol': o_sym, 'option_token': "142500", 'entry': p_entry, 
                            'sl': p_sl, 'target': p_targ, 'target_dist': premium_target_points, 'sl_dist': p_sl_dist,
                            'index_entry': spot, 'index_sl': strat['c_low'] if strat['otype']=="CE" else strat['c_high'], 
                            'index_target': strat['next_w'], 'qty': qty_final, 'status': 'ACTIVE', 
                            'exit_price': 0.0, 'pnl_realized': 0.0
                        })
            
            hist_latest = manage_ledger()
            current_act = next((t for t in hist_latest['trades'] if t['status'] == 'ACTIVE'), None)
            
            with open('paper_signal.json', 'w') as f:
                json.dump({
                    'rsi_status': strat['rsi_status'], 'ema_status': strat['ema_status'], 
                    'vol_status': strat['vol_status'], 'runway_status': strat['runway_status'], 
                    'vol_val': strat['vol_val'], 'runway_val': strat['runway_val'], 
                    'intraday_high': strat['intraday_high'], 'intraday_low': strat['intraday_low'], 
                    'algo_reason': f"🚀 JACKPOT STRUCURAL POSITION ACTIVE: {current_act['option_symbol']}!" if current_act else strat['algo_reason'], 
                    'signal_active': current_act is not None, 
                    'active_trade_symbol': current_act['option_symbol'] if current_act else 'NONE'
                }, f)
        except: pass
        time.sleep(2)

if __name__ == "__main__": start_paper_engine()
