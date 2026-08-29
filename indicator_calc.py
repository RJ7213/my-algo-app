# indicator_calc.py - भाग १
import time, json, os
import pandas as pd, numpy as np
from datetime import datetime, timedelta, time as datetime_time

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
# indicator_calc.py - भाग २
def start_indicator_engine():
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if not os.path.exists('data_raw.json'):
            time.sleep(1); continue
        try:
            with open('data_raw.json', 'r') as f: raw = json.load(f)
            spot = raw['live_spot']
            df = pd.DataFrame(raw['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            
            rsi_v = calculate_tv_rsi(df['close'].astype(float), 14)
            ema9 = float(df['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
            
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['date'].astype(str).str.contains(today_str)].copy()
            high = float(df_t['high'].astype(float).max()) if not df_t.empty else 24188.30
            low = float(df_t['low'].astype(float).min()) if not df_t.empty else 24076.85
            
            psy_level = int(round(spot / 50) * 50)
            c_open, c_close, c_high, c_low = float(df['open'].iloc[-2]), float(df['close'].iloc[-2]), float(df['high'].iloc[-2]), float(df['low'].iloc[-2])
            c_size = abs(c_high - c_low) if abs(c_high - c_low) > 0 else 1.0
            top_wick, bot_wick = c_high - max(c_open, c_close), min(c_open, c_close) - c_low
            
            # 💎 कँडल शेंडी विश्लेषण फिल्टरेशन नियम [Claim]
            is_rejection = (abs(c_high - psy_level) <= 8 and top_wick >= (c_size * 0.5)) or (abs(c_low - psy_level) <= 8 and bot_wick >= (c_size * 0.5))
            is_pullback = (spot < 24190.0) and not is_rejection
# indicator_calc.py - भाग ३
            if is_rejection:
                otype, rsi_st, setup_name = ("PE" if top_wick > bot_wick else "CE"), "PASS", "Major Rejection"
            elif is_pullback:
                otype, rsi_st, setup_name = ("PE" if spot < ema9 else "CE"), ("PASS" if 30.0<=rsi_v<=55.0 else "FAIL"), "Pullback"
            else:
                otype = "CE" if rsi_v >= 60 else ("PE" if rsi_v <= 40 else "NONE")
                rsi_st, setup_name = ("PASS" if otype != "NONE" else "FAIL"), "Breakout"
            
            ttype = f"{otype}_BUY" if otype != "NONE" else "NONE"
            ema_dist = abs(spot - ema9)
            
            # ९ EMA अचूक ५-पॉईंट दिशा मॅपिंग [Claim]
            if is_rejection: ema_st = "PASS"
            else:
                if otype == "CE": ema_st = "PASS" if (spot >= (ema9 - 3) and ema_dist <= 22) else "FAIL"
                elif otype == "PE": ema_st = "PASS" if (spot <= (ema9 + 3) and ema_dist <= 22) else "FAIL"
                else: ema_st = "FAIL"
            
            df['vsma'] = df['volume'].astype(float).rolling(window=20, min_periods=1).mean()
            vol_ratio = round(float(df['volume'].iloc[-1]) / float(df['vsma'].iloc[-1]), 1) if float(df['vsma'].iloc[-1]) > 0 else 1.0
            vol_st = "PASS" if float(df['volume'].iloc[-1]) >= float(df['vsma'].iloc[-1]) else "FAIL"
            
            next_w = high if otype == "CE" else low
            if is_rejection: next_w = low if otype == "PE" else high
            run_df = abs(next_w - spot)
            runway_st = "PASS" if (run_df >= 25.0) else "FAIL"
            
            all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
            reason = f"⏸️ Analysing {setup_name} near {psy_level} (Runway: {run_df:.1f} pts)"
            
            # 📥 हा निर्णय इंजिन २बी कडे (paper_engine.py) जाणार [Claim]
            with open('strategy_signal.json', 'w') as f:
                json.dump({'live_spot': spot, 'rsi_v': rsi_v, 'ema9': ema9, 'rsi_status': rsi_st, 'ema_status': ema_st, 'vol_status': vol_st, 'runway_status': runway_st, 'vol_val': f"{vol_ratio}x SMA", 'runway_val': f"{run_df:.1f} pts", 'intraday_high': high, 'intraday_low': low, 'algo_reason': reason, 'signal_triggered': all_p, 'trade_type': ttype, 'otype': otype, 'next_w': next_w, 'run_df': run_df}, f)
        except: pass
        time.sleep(2)

if __name__ == "__main__": start_indicator_engine()
