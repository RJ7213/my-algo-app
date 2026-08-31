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
    return float((100 - (100 / (1 + rs))).iloc[-1])

def start_indicator_engine():
    logging.info("अचूक ऑप्शन्स व्हॉल्यूम कॅल्क्युलेटर मेंदू सुरू झाला...")
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if not os.path.exists('data_raw.json'):
            time.sleep(1); continue
        try:
            with open('data_raw.json', 'r') as f: raw = json.load(f)
            spot = float(raw['live_spot'])
            if not raw.get('candles') or not raw.get('opt_candles'):
                time.sleep(1); continue
                
            df = pd.DataFrame(raw['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            # वर्करकडून आलेला खऱ्या ऑप्शन्सचा डेटा लोड करणे
            df_opt = pd.DataFrame(raw['opt_candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            
            for d in [df, df_opt]:
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    d[col] = d[col].astype(float)
                d['datetime'] = pd.to_datetime(d['date'])
            
            # इंडेक्स स्पॉट गणीत
            rsi_v = calculate_tv_rsi(df['close'], 14)
            ema9 = float(df['close'].ewm(span=9, adjust=False).mean().iloc[-1])
            
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['datetime'].dt.strftime('%Y-%m-%d') == today_str].copy()
            high = float(df_t['high'].max()) if not df_t.empty else 24188.30
            low = float(df_t['low'].min()) if not df_t.empty else 24076.85
            
            psy_level = int(round(spot / 50.0) * 50)
            c_open, c_close = df['open'].iloc[-2], df['close'].iloc[-2]
            c_high, c_low = df['high'].iloc[-2], df['low'].iloc[-2]
            
            c_size = abs(c_high - c_low) if abs(c_high - c_low) > 0 else 1.0
            top_wick = c_high - max(c_open, c_close)
            bot_wick = min(c_open, c_close) - c_low
            
            is_rejection = (abs(c_high - psy_level) <= 25 and top_wick >= (c_size * 0.4)) or (abs(c_low - psy_level) <= 25 and bot_wick >= (c_size * 0.4))
            is_pullback = not is_rejection and (abs(spot - ema9) <= 30.0)
            
            if is_rejection:
                otype = "PE" if top_wick > bot_wick else "CE"
                rsi_st, setup_name = "PASS", "Major Rejection"
            elif is_pullback:
                otype = "PE" if spot < ema9 else "CE"
                rsi_st = "PASS" if (rsi_v >= 45.0 if otype=="CE" else rsi_v <= 55.0) else "FAIL"
                setup_name = "Pullback"
            else:
                otype = "CE" if spot > ema9 else "PE"
                rsi_st = "PASS" if (rsi_v >= 60.0 if otype=="CE" else rsi_v <= 40.0) else "FAIL"
                setup_name = "Breakout"
                
            ttype = f"{otype}_BUY" if otype != "NONE" else "NONE"
            ema_dist = abs(spot - ema9)
            
            if is_rejection or setup_name == "Breakout": ema_st = "PASS"
            else:
                if otype == "CE": ema_st = "PASS" if (spot >= (ema9 - 5) and ema_dist <= 25) else "FAIL"
                elif otype == "PE": ema_st = "PASS" if (spot <= (ema9 + 5) and ema_dist <= 25) else "FAIL"
                else: ema_st = "FAIL"
            
            # ⭐⭐⭐ [खरा आणि मूळ ऑप्शन्स प्रीमियम व्हॉल्यूम नियम] ⭐⭐⭐
            # इथे आपण इंडेक्स स्पॉट ऐवजी थेट वर्करने आणलेल्या ऑप्शन्सचा व्हॉल्यूम मोजत आहोत!
            df_opt['vsma'] = df_opt['volume'].rolling(window=20, min_periods=1).mean()
            last_vol = float(df_opt['volume'].iloc[-2]) # बंद झालेली ऑप्शन कँडल
            last_vsma = float(df_opt['vsma'].iloc[-2]) if float(df_opt['vsma'].iloc[-2]) > 0 else 1.0
            
            vol_ratio = round(last_vol / last_vsma, 1)
            # मूळ नियम: ऑप्शन प्रीमियमचा व्हॉल्यूम २० सरासरीपेक्षा जास्त असेल तरच PASS!
            vol_st = "PASS" if last_vol >= last_vsma else "FAIL"
            # ⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐⭐
            
            next_w = high if otype == "CE" else low
            if is_rejection: next_w = low if otype == "PE" else high
            
            run_df = abs(next_w - spot)
            runway_st = "PASS" if (run_df >= 15.0) else "FAIL"
            
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
