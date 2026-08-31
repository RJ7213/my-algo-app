# data_worker.py
import time, pyotp, json, logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_SPOT_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"

# नमुना म्हणून निफ्टी ऑप्शन्सचे चालू वीकली क्रेडेंशियल्स टोकन्स (लाईव्हमध्ये हे स्ट्राइकनुसार सिंक होतील)
NIFTY_CE_TOKEN = "142500"  # Example NIFTY CE Token
NIFTY_PE_TOKEN = "142501"  # Example NIFTY PE Token

def start_backend_factory():
    from SmartApi import SmartConnect
    while True:
        try:
            logging.info("Angel One स्पॉट आणि ऑप्शन्स व्हॉल्यूम पंप सुरू होत आहे...")
            api = SmartConnect(api_key=AKEY, timeout=15)
            tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
            
            session = api.generateSession(CID, PIN, tok)
            if not session or not session.get('status'):
                logging.error("API सेशन फेल. १० सेकंदात पुन्हा प्रयत्न...")
                time.sleep(10)
                continue
            
            cached_candles = None
            opt_candles = None
            last_candle_fetch = datetime.min
            
            while True:
                now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
                try:
                    # १. निफ्टी स्पॉट भाव मिळवणे
                    ltp = api.ltpData("NSE", "NIFTY", NIFTY_SPOT_TOKEN)
                    if ltp and ltp.get('status') and ltp.get('data'):
                        spot = float(ltp['data']['ltp'])
                        
                        # २. स्पॉट ५-मिनिट कॅन्डल्स आणि थेट ऑप्शन्स प्रीमियम कॅन्डल्स (व्हॉल्यूम डेटासह) फेच करणे
                        if cached_candles is None or (now_dt - last_candle_fetch).total_seconds() > 60:
                            from_d = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
                            to_d = now_dt.strftime("%Y-%m-%d %H:%M")
                            
                            # स्पॉट चार्ट डेटा
                            res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_SPOT_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_d, "todate": to_d})
                            # ऑप्शन चार्ट डेटा (ज्यात खरा प्रीमियम व्हॉल्यूम आहे)
                            res_opt = api.getCandleData({"exchange": "NFO", "symboltoken": NIFTY_CE_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_d, "todate": to_d})
                            
                            if res and res.get('status') and res.get('data'):
                                cached_candles = res['data']
                            if res_opt and res_opt.get('status') and res_opt.get('data'):
                                opt_candles = res_opt['data']
                                
                            last_candle_fetch = now_dt
                            logging.info("स्पॉट आणि ऑप्शन प्रीमियम व्हॉल्यूम डेटा यशस्वीरित्या सिंक झाला.")
                        
                        if cached_candles and opt_candles:
                            with open('data_raw.json', 'w') as f:
                                json.dump({
                                    'live_spot': spot, 
                                    'candles': cached_candles, 
                                    'opt_candles': opt_candles, # खरा व्हॉल्यूम असलेली ऑप्शन फाईल
                                    'last_update': now_dt.strftime("%H:%M:%S")
                                }, f)
                except Exception as loop_err:
                    logging.error(f"लूप एरर: {loop_err}")
                time.sleep(3)
        except Exception as conn_err:
            logging.error(f"क्रिटिकल एरर: {conn_err}. १० सेकंदात रीस्टार्ट...")
            time.sleep(10)

if __name__ == "__main__": start_backend_factory()
