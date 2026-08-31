# indicator_calc.py
import time, json, os, logging
import pandas as pd, numpy as np
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def calculate_tv_rsi(series, period=14):
    if len(series) < period + 1: return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).astype(float)
    loss = (-delta.where(delta < 0, 0.0)).astype(float)
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 0.00001)
    # ⭐ लाईव्ह मार्केट चार्टशी तंतोतंत मॅच करण्यासाठी शेवटची लाईव्ह कँडल (-1) वापरणे
    return float((100 - (100 / (1 + rs))).iloc[-1])

def start_indicator_engine():
    logging.info("अल्गो इंडिकेटर मेंदू इंजिन सुरू झाले आहे...")
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if not os.path.exists('data_raw.json'):
            time.sleep(1); continue
        try:
            with open('data_raw.json', 'r') as f: raw = json.load(f)
            spot = float(raw['live_spot'])
            if not raw.get('candles') or len(raw['candles']) < 2:
                time.sleep(1); continue
                
            df = pd.DataFrame(raw['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            df['datetime'] = pd.to_datetime(df['date'])
            
            # ⭐ शेवटच्या लाईव्ह कँडलवरून गणिते करणे जेणेकरून चार्टशी आकडे मॅच होतील
            rsi_v = calculate_tv_rsi(df['close'], 14)
            ema9 = float(df['close'].ewm(span=9, adjust=False).mean().iloc[-1])
            
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['datetime'].dt.strftime('%Y-%m-%d') == today_str].copy()
            
            if not df_t.empty:
                high = float(df_t['high'].max())
                low = float(df_t['low'].min())
            else:
                high = 24188.30
                low = 24076.85
            
            psy_level = int(round(spot / 50.0) * 50)
            
            # कॅन्डल बॉडी विश्लेषणासाठी चालू कँडल (-1) चा वापर
            c_open, c_close = df['open'].iloc[-1], df['close'].iloc[-1]
            c_high, c_low = df['high'].iloc[-1], df['close'].iloc[-1]
            
            c_size = abs(c_high - c_low) if abs(c_high - c_low) > 0 else 1.0
            top_wick = c_high - max(c_open, c_close)
            bot_wick = min(c_open, c_close) - c_low
            
            is_rejection = (abs(c_high - psy_level) <= 8 and top_wick >= (c_size * 0.5)) or (abs(c_low - psy_level) <= 8 and bot_wick >= (c_size * 0.5))
            is_pullback = (spot < 24190.0) and not is_rejection
            
            if is_rejection:
                otype = "PE" if top_wick > bot_wick else "CE"
                rsi_st, setup_name = "PASS", "Major Rejection"
            elif is_pullback:
                otype = "PE" if spot < ema9 else "CE"
                rsi_st = "PASS" if (30.0 <= rsi_v <= 55.0) else "FAIL"
                setup_name = "Pullback"
            else:
                otype = "CE" if rsi_v >= 60.0 else ("PE" if rsi_v <= 40.0 else "NONE")
                rsi_st = "PASS" if otype != "NONE" else "FAIL"
                setup_name = "Breakout"
                
            ttype = f"{otype}_BUY" if otype != "NONE" else "NONE"
            ema_dist = abs(spot - ema9)
            
            if is_rejection: ema_st = "PASS"
            else:
                if otype == "CE": ema_st = "PASS" if (spot >= (ema9 - 3) and ema_dist <= 22) else "FAIL"
                elif otype == "PE": ema_st = "PASS" if (spot <= (ema9 + 3) and ema_dist <= 22) else "FAIL"
                else: ema_st = "FAIL"
            
            df['vsma'] = df['volume'].rolling(window=20, min_periods=1).mean()
            last_vol = float(df['volume'].iloc[-1])
            last_vsma = float(df['vsma'].iloc[-1]) if float(df['vsma'].iloc[-1]) > 0 else 1.0
            
            vol_ratio = round(last_vol / last_vsma, 1)
            vol_st = "PASS" if last_vol >= last_vsma else "FAIL"
            
            next_w = high if otype == "CE" else low
            if is_rejection: next_w = low if otype == "PE" else high
            
            run_df = abs(next_w - spot)
            runway_st = "PASS" if (run_df >= 25.0) else "FAIL"
            
            all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
            reason = f"⏸ ... {setup_name} near {psy_level} (Runway: {run_df:.1f} pts)"
            
            with open('strategy_signal.json', 'w') as f:
                json.dump({
                    'live_spot': spot, 'rsi_v': rsi_v, 'ema9': ema9, 'rsi_status': rsi_st, 'ema_status': ema_st, 
                    'vol_status': vol_st, 'runway_status': runway_st, 'vol_val': f"{vol_ratio}x SMA", 
                    'runway_val': f"{run_df:.1f} pts", 'intraday_high': high, 'intraday_low': low, 
                    'algo_reason': reason, 'signal_triggered': all_p, 'trade_type': ttype, 'otype': otype, 
                    'next_w': next_w, 'run_df': run_df, 'c_low': c_low, 'c_high': c_high
                }, f)
        except Exception as err: pass
        time.sleep(2)

if __name__ == "__main__": start_indicator_engine()
