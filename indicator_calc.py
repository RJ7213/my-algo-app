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
    logging.info("कडक रीस्ट्रक्चर्ड इंडिकेटर इंजिन सुरू झाले...")
    while True:
        now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if not os.path.exists('data_raw.json'):
            time.sleep(1); continue
        try:
            with open('data_raw.json', 'r') as f: raw = json.load(f)
            spot = float(raw['live_spot'])
            if not raw.get('candles') or len(raw['candles']) < 3:
                time.sleep(1); continue
                
            df = pd.DataFrame(raw['candles'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            df['datetime'] = pd.to_datetime(df['date'])
            
            rsi_v = calculate_tv_rsi(df['close'], 14)
            ema9 = float(df['close'].ewm(span=9, adjust=False).mean().iloc[-1])
            
            today_str = now_dt.strftime("%Y-%m-%d")
            df_t = df[df['datetime'].dt.strftime('%Y-%m-%d') == today_str].copy()
            high = float(df_t['high'].max()) if not df_t.empty else spot + 50.0
            low = float(df_t['low'].min()) if not df_t.empty else spot - 50.0
            
            psy_level = int(round(spot / 50.0) * 50)
            
            c_open, c_close = df['open'].iloc[-2], df['close'].iloc[-2]
            c_high, c_low = df['high'].iloc[-2], df['low'].iloc[-2]
            current_candle_time = str(df['date'].iloc[-1]) # ओव्हर-ट्रेडिंग ब्लॉक करण्यासाठी
            
            c_size = abs(c_high - c_low) if abs(c_high - c_low) > 0 else 1.0
            top_wick = c_high - max(c_open, c_close)
            bot_wick = min(c_open, c_close) - c_low
            
            # ⭐ रिजेक्शन पॅटर्न: २५ पॉईंट्स रेंज आणि मजबूत कँडल शेंडी
            is_rejection = (abs(c_high - psy_level) <= 25 and top_wick >= (c_size * 0.45)) or \
                           (abs(c_low - psy_level) <= 25 and bot_wick >= (c_size * 0.45))
            
            is_pullback = not is_rejection and (abs(spot - ema9) <= 20.0)
            
            # ⭐ कडक सिस्टीम नियम वर्गीकरण [Updated based on your criteria]
            if is_rejection:
                otype = "PE" if top_wick > bot_wick else "CE"
                # रिजेक्शनला लॅगिंग इंडिकेटर (RSI आणि EMA) पूर्णपणे बायपास (नेहमी PASS)
                rsi_st = "PASS"
                ema_st = "PASS"
                setup_name = "Major Rejection"
            elif is_pullback:
                otype = "PE" if spot < ema9 else "CE"
                # पुलबॅकसाठी कडक आरएसआय नियम: CE साठी ४५ ते ५५, PE साठी ४५ ते ५५
                rsi_st = "PASS" if (45.0 <= rsi_v <= 55.0) else "FAIL"
                ema_st = "PASS" if (abs(spot - ema9) <= 15.0) else "FAIL"
                setup_name = "Pullback"
            else:
                otype = "CE" if spot > ema9 else "PE"
                # ब्रेकआऊटसाठी कडक मोमेंटम आरएसआय: CE साठी ६०+, PE साठी ४०-
                rsi_st = "PASS" if (rsi_v >= 60.0 if otype=="CE" else rsi_v <= 40.0) else "FAIL"
                ema_st = "PASS"
                setup_name = "Breakout"
                
            ttype = f"{otype}_BUY" if otype != "NONE" else "NONE"
            
            # मोमेंटम आधारित व्हॉल्यूम सिमुलेशन
            df['candle_body'] = (df['close'] - df['open']).abs()
            avg_body = df['candle_body'].rolling(window=20, min_periods=1).mean().iloc[-2]
            vol_st = "PASS" if abs(c_close - c_open) >= (avg_body * 0.7) else "FAIL"
            vol_ratio = round(abs(c_close - c_open) / avg_body, 1) if avg_body > 0 else 1.0
            
            run_df = abs((high if otype == "CE" else low) - spot)
            runway_st = "PASS" if (run_df >= 15.0) else "FAIL"
            
            all_p = (rsi_st == "PASS" and ema_st == "PASS" and vol_st == "PASS" and runway_st == "PASS")
            reason = f"⏸ ... {setup_name} near {psy_level} (Runway: {run_df:.1f} pts)"
            
            with open('strategy_signal.json', 'w') as f:
                json.dump({
                    'live_spot': spot, 'rsi_v': rsi_v, 'ema9': ema9, 'rsi_status': rsi_st, 'ema_status': ema_st, 
                    'vol_status': vol_st, 'runway_status': runway_st, 'vol_val': f"{vol_ratio}x Speed", 
                    'runway_val': f"{run_df:.1f} pts", 'intraday_high': high, 'intraday_low': low, 
                    'algo_reason': reason, 'signal_triggered': all_p, 'trade_type': ttype, 'otype': otype, 
                    'next_w': high if otype == "CE" else low, 'run_df': run_df, 'c_low': c_low, 'c_high': c_high,
                    'strategy_used': setup_name, 'candle_time': current_candle_time
                }, f)
        except Exception as err: pass
        time.sleep(2)

if __name__ == "__main__": start_indicator_engine()
