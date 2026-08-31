# data_worker.py
import time, pyotp, json, logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_SPOT_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"

def start_backend_factory():
    from SmartApi import SmartConnect
    while True:
        try:
            logging.info("Angel One लाइव्ह डेटा पंप रीस्टार्ट होत आहे...")
            api = SmartConnect(api_key=AKEY, timeout=15)
            tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
            
            session = api.generateSession(CID, PIN, tok)
            if not session or not session.get('status'):
                logging.error("API सेशन फेल. १० सेकंदात पुन्हा प्रयत्न...")
                time.sleep(10)
                continue
            
            cached_candles = None
            last_candle_fetch = datetime.min
            logging.info("स्पॉट सिंक यशस्वी! सिस्टीम अनलॉक झाली...")
            
            while True:
                now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
                try:
                    # १. थेट निफ्टी स्पॉट डेटा फेच करणे
                    ltp = api.ltpData("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
                    if ltp and ltp.get('status') and ltp.get('data'):
                        spot = float(ltp['data']['ltp'])
                        
                        # २. ५-मिनिट कॅन्डल्स अपडेट करणे
                        if cached_candles is None or (now_dt - last_candle_fetch).total_seconds() > 60:
                            from_d = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                            to_d = now_dt.strftime("%Y-%m-%d %H:%M")
                            
                            res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_SPOT_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_d, "todate": to_d})
                            if res and res.get('status') and res.get('data'):
                                cached_candles = res['data']
                                last_candle_fetch = now_dt
                                logging.info("स्पॉट कॅन्डल डेटा यशस्वीरित्या अपडेट झाला.")
                        
                        if cached_candles:
                            with open('data_raw.json', 'w') as f:
                                json.dump({
                                    'live_spot': spot, 
                                    'candles': cached_candles, 
                                    'last_update': now_dt.strftime("%H:%M:%S")
                                }, f)
                    else:
                        logging.warning("LTP रिस्पॉन्स रिकामा आला.")
                except Exception as loop_err:
                    logging.error(f"लूप एरर: {loop_err}")
                time.sleep(3)
        except Exception as conn_err:
            logging.error(f"क्रिटिकल एरर: {conn_err}. १० सेकंदात रीस्टार्ट...")
            time.sleep(10)

if __name__ == "__main__": start_backend_factory()
