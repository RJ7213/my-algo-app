# data_worker.py
import time, pyotp, json, logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"

def start_backend_factory():
    from SmartApi import SmartConnect
    while True:
        try:
            logging.info("Angel One SmartConnect लाँच करत आहे...")
            api = SmartConnect(api_key=AKEY, timeout=15)
            tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
            
            session = api.generateSession(CID, PIN, tok)
            if not session or not session.get('status'):
                logging.error("API सेशन फेल झाले. १० सेकंदात पुन्हा प्रयत्न करत आहे...")
                time.sleep(10)
                continue
            
            cached_candles = None
            last_candle_fetch = datetime.min
            logging.info("सेशन यशस्वी! मार्केट डेटा सुरू झाला...")
            
            while True:
                now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
                try:
                    # १. दर ३ सेकंदाला स्पॉट भाव अपडेट
                    ltp = api.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                    if ltp and ltp.get('status') and ltp.get('data'):
                        spot = float(ltp['data']['ltp'])
                        
                        # २. दर ६० सेकंदाला ५-मिनिट कॅन्डल्स अपडेट
                        if cached_candles is None or (now_dt - last_candle_fetch).total_seconds() > 60:
                            from_d = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                            to_d = now_dt.strftime("%Y-%m-%d %H:%M")
                            res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_d, "todate": to_d})
                            if res and res.get('status') and res.get('data'):
                                cached_candles = res['data']
                                last_candle_fetch = now_dt
                                logging.info("कॅन्डल कॅश अपडेट झाली.")
                        
                        if cached_candles:
                            with open('data_raw.json', 'w') as f:
                                json.dump({'live_spot': spot, 'candles': cached_candles, 'last_update': now_dt.strftime("%H:%M:%S")}, f)
                    else:
                        logging.warning("LTP रिस्पॉन्स रिकामा आला.")
                except Exception as loop_err:
                    logging.error(f"लूप एरर: {loop_err}")
                time.sleep(3)
        except Exception as conn_err:
            logging.error(f"क्रिटिकल फेल्युअर: {conn_err}. १० सेकंदात रीस्टार्ट करत आहे...")
            time.sleep(10)

if __name__ == "__main__": start_backend_factory()
