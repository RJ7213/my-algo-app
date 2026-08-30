# indicator_calc.py
import time
import json
import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# रेंडर लॉग्स मॉनिटर करण्यासाठी सेटअप
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def calculate_tv_rsi(series, period=14):
    if len(series) < period + 1: 
        return 50.0
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).astype(float)
    loss = (-delta.where(delta < 0, 0.0)).astype(float)
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 0.00001)
    # स्थिर सिग्नलसाठी बंद झालेली कँडल (-2) चा वापर (No Repainting)
    return float((100 - (100 / (1 + rs))).iloc[-2])

def start_indicator_engine():
    logging.info("अल्गो इंडिकेटर मेंदू इंजिन (Indicator Engine) सुरू झाले आहे...")
    while True:
        # वेळ थेट भारतीय वेळेनुसार (IST) सिंक करणे
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        
        if not os.path.exists('data_raw.json'):
            time.sleep(1)
            continue
            
        try:
            with open('data_raw.json', 'r') as f: 
                raw = json.load(f)
            
            spot = float(raw['live_spot'])
            if not raw.get('candles') or len(raw['candles']) < 2:
                time.sleep(1)
                continue
                
            # डेटा फ्रेम स्ट्रक्चर तयार करणे
            df = pd.DataFrame(raw['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            # तारीख फॉरमॅट अचूक करणे
            df['datetime'] = pd.to_datetime(df['date'])
            
            # १. तांत्रिक गणिते (Technical Indicators)
            rsi_v = calculate_tv_rsi(df['close'], 14)
            ema9 = float(df['close'].ewm(span=9, adjust=False).mean().iloc[-2])
            
            # 📅 २. दिवसाचा खरा हाय / लो (DAY HIGH/LOW) काढण्याचे सुधारित लॉजिक
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['datetime'].dt.strftime('%Y-%m-%d') == today_str].copy()
            
            # जर आजच्या लाइव्ह कॅंडल्स सापडल्या तर लाईव्ह हाय/लो मोजणे, नाहीतर चार्टचे फिक्स आकडे वापरणे
            if not df_t.empty:
                high = float(df_t['high'].max())
                low = float(df_t['low'].min())
            else:
                high = 24188.30  # तुमचा चार्टवरील अधिकृत हाय (वरची हिरवी रेषा)
                low = 24076.85   # तुमचा चार्टवरील अधिकृत लो (खालची हिरवी रेषा)
            
            # ३. सायकॉलॉजिकल लेव्हल आणि कँडल शेंडी विश्लेषण (Wick Analysis)
            psy_level = int(round(spot / 50.0) * 50)
            
            # नुकतीच पूर्ण बंद झालेली कँडल index [-2]
            c_open, c_close = df['open'].iloc[-2], df['close'].iloc[-2]
            c_high, c_low = df['high'].iloc[-2], df['low'].iloc[-2]
            
            c_size = abs(c_high - c_low) if abs(c_high - c_low) > 0 else 1.0
            top_wick = c_high - max(c_open, c_close)
            bot_wick = min(c_open, c_close) - c_low
            
            # 💎 कँडल शेंडी विश्लेषण फिल्टरेशन नियम
            is_rejection = (abs(c_high - psy_level) <= 8 and top_wick >= (c_size * 0.5)) or \
                           (abs(c_low - psy_level) <= 8 and bot_wick >= (c_size * 0.5))
            is_pullback = (spot < 24190.0) and not is_rejection
            
            # ४. रणनीती वर्गीकरण (Strategy Classifier Setup)
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
            
            # ५. ९ EMA दिशा मॅपिंग नियम
            if is_rejection: 
                ema_st = "PASS"
            else:
                if otype == "CE": 
                    ema_st = "PASS" if (spot >= (ema9 - 3) and ema_dist <= 22) else "FAIL"
                elif otype == "PE": 
                    ema_st = "PASS" if (spot <= (ema9 + 3) and ema_dist <= 22) else "FAIL"
                else: 
                    ema_st = "FAIL"
            
            # ६. वॉल्यूम टॉवर व्हॅलिडेशन (Volume Tower)
            df['vsma'] = df['volume'].rolling(window=20, min_periods=1).mean()
            last_vol = float(df['volume'].iloc[-2])
            last_vsma = float(df['vsma'].iloc[-2]) if float(df['vsma'].iloc[-2]) > 0 else 1.0
            
            vol_ratio = round(last_vol / last_vsma, 1)
            vol_st = "PASS" if last_vol >= last_vsma else "FAIL"
            
            # ७. रनवे ब्रेकथ्रू अंतर मोजणे (Runway Points)
            next_w = high if otype == "CE" else low
            if is_rejection: 
                next_w = low if otype == "PE" else high
            
            run_df = abs(next_w - spot)
            runway_st = "PASS" if (run_df >= 25.0) else "FAIL"
            
            # सर्व अटींची अंतिम पडताळणी (Final Approval)
            all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
            reason = f"⏸️ Analysing {setup_name} near {psy_level} (Runway: {run_df:.1f} pts)"
            
            # 📥 हा निर्णय इंजिन २बी कडे (paper_engine.py) सुरक्षित पाठवणे (c_low, c_high सह)
            with open('strategy_signal.json', 'w') as f:
                json.dump({
                    'live_spot': spot, 
                    'rsi_v': rsi_v, 
                    'ema9': ema9, 
                    'rsi_status': rsi_st, 
                    'ema_status': ema_st, 
                    'vol_status': vol_st, 
                    'runway_status': runway_st, 
                    'vol_val': f"{vol_ratio}x SMA", 
                    'runway_val': f"{run_df:.1f} pts", 
                    'intraday_high': high, 
                    'intraday_low': low, 
                    'algo_reason': reason, 
                    'signal_triggered': all_p, 
                    'trade_type': ttype, 
                    'otype': otype, 
                    'next_w': next_w, 
                    'run_df': run_df,
                    'c_low': c_low,
                    'c_high': c_high
                }, f)
                
        except Exception as err:
            logging.error(f"इंजिन लूपमध्ये त्रुटी आढळली: {err}")
            
        time.sleep(2)

if __name__ == "__main__": 
    start_indicator_engine()
