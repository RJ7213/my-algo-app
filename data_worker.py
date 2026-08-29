# data_worker.py
import time, pyotp, json
import pandas as pd
from datetime import datetime, timedelta

# 🔐 अधिकृत सेशन्स क्रेडेंशियल्स
CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"

def start_backend_factory():
    from SmartApi import SmartConnect
    try:
        api = SmartConnect(api_key=AKEY, timeout=15)
        tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
        if not api.generateSession(CID, PIN, tok)['status']: return
        
        cached_candles = None
        last_candle_fetch = datetime.min
        
        while True:
            now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
            try:
                # ⚡ १. फक्त ३ सेकंदाला लाईव्ह स्पॉट भाव खेचणे
                ltp = api.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                if ltp and ltp.get('status') and ltp.get('data'):
                    spot = float(ltp['data']['ltp'])
                    
                    # ⚡ २. दर ६० सेकंदाला (१ मिनिट) कच्च्या कॅन्डल्स डाऊनलोड करणे
                    if cached_candles is None or (now_dt - last_candle_fetch).total_seconds() > 60:
                        from_d = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                        to_d = now_dt.strftime("%Y-%m-%d %H:%M")
                        res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_d, "todate": to_d})
                        if res and res.get('data'):
                            cached_candles = res['data']
                            last_candle_fetch = now_dt
                    
                    # ⚡ ३. नो कॅल्क्युलेशन - फक्त कच्चा डेटा फाईलमध्ये टाकणे
                    if cached_candles:
                        with open('data_raw.json', 'w') as f:
                            json.dump({
                                'live_spot': spot,
                                'candles': cached_candles,
                                'last_update': now_dt.strftime("%H:%M:%S")
                            }, f)
            except: pass
            time.sleep(3)
    except: time.sleep(10); start_backend_factory()

if __name__ == "__main__": start_backend_factory()
