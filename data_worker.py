import time
import pyotp
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta

# 🔐 क्रेडेंशियल्स
CID = "R990942"
AKEY = "c75cUJga"  
PIN = "8547"               
TKEY = "FQ7TSLI3L2UUKWZOC3TOJEFI6E" 

NIFTY_TOKEN = "99926000"

# 🛠️ ट्रेडिंगव्ह्यू अचूक RSI
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

def start_backend_factory():
    from SmartApi import SmartConnect
    try:
        smartApi = SmartConnect(api_key=AKEY, timeout=15)
        clean_tkey = TKEY.replace(" ", "").strip().upper()
        missing_padding = len(clean_tkey) % 8
        if missing_padding != 0: clean_tkey += '=' * (8 - missing_padding)
        totp_token = pyotp.TOTP(clean_tkey).now()
        
        if not smartApi.generateSession(CID, PIN, totp_token)['status']:
            return
            
        cached_nifty_df = None
        last_candle_fetch_time = datetime.min
        
        while True:
            now_dt = datetime.now() + timedelta(hours=5, minutes=30)
            from_time = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
            to_time = now_dt.strftime("%Y-%m-%d %H:%M")
            
            output_data = {
                'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 
                'nifty_status': 'Connecting', 'last_update': now_dt.strftime("%H:%M:%S")
            }
            
            try:
                # ⚡ फक्त १ एंडपॉईंट कॉल - नो रेट लिमिट ब्लॉक
                ltp_res = smartApi.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                if ltp_res and ltp_res.get('status') and ltp_res.get('data'):
                    live_spot = float(ltp_res['data']['ltp'])
                    
                    # कॅन्डल डेटा फक्त ५ मिनिटांनी एकदाच अपडेट होणार
                    if cached_nifty_df is None or (now_dt - last_candle_fetch_time).total_seconds() > 300:
                        res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
                        if res and res.get('data') and len(res['data']) > 0:
                            cached_nifty_df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                            last_candle_fetch_time = now_dt
                    
                    if cached_nifty_df is not None:
                        df_calc = cached_nifty_df.copy()
                        df_calc.iloc[-1, df_calc.columns.get_loc('close')] = live_spot
                        rsi_v = calculate_tv_rsi(df_calc['close'].astype(float), 14)
                        ema9 = float(df_calc['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                        output_data.update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'nifty_status': '🟢 Active'})
            except: pass

            with open('data_signal.json', 'w') as f:
                json.dump(output_data, f)
                
            time.sleep(3)  # सेफ ३ सेकंद पॉज
            
    except:
        time.sleep(10)
        start_backend_factory()

if __name__ == "__main__":
    start_backend_factory()
