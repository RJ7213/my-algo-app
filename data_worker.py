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
CRUDE_TOKEN = "256191"  # सप्टेंबर २०२६ चालू कॉन्ट्रॅक्ट [27-Aug-2026]

# 🛠️ अचूक ट्रेडिंगव्ह्यू RSI (Wilder's RMA)
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

# 🧮 मुख्य बॅकएंड रनर
def start_backend_factory():
    from SmartApi import SmartConnect
    try:
        smartApi = SmartConnect(api_key=AKEY, timeout=15)
        clean_tkey = TKEY.replace(" ", "").strip().upper()
        missing_padding = len(clean_tkey) % 8
        if missing_padding != 0: clean_tkey += '=' * (8 - missing_padding)
        totp_token = pyotp.TOTP(clean_tkey).now()
        
        if not smartApi.generateSession(CID, PIN, totp_token)['status']:
            print("❌ Backend Login Failed")
            return
            
        print("🟢 Backend Engine Connected to Angel One!")
        
        while True:
            now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
            from_time = (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
            to_time = now_dt.strftime("%Y-%m-%d %H:%M")
            
            # डिफॉल्ट सेफ डेटा स्ट्रक्चर
            output_data = {
                'live_spot': 24207.75, 'rsi_v': 38.17, 'ema9': 24241.76, 'nifty_status': 'Connecting',
                'crude_spot': 7670.0, 'crude_rsi': 47.9, 'crude_ema9': 7665.0, 'crude_status': 'Connecting',
                'last_update': now_dt.strftime("%H:%M:%S")
            }
            
            # 📈 NIFTY फेच आणि मॅथ इंजिन
            try:
                ltp_res = smartApi.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                if ltp_res and ltp_res.get('status') and ltp_res.get('data'):
                    live_spot = float(ltp_res['data']['ltp'])
                    res = smartApi.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
                    if res and res.get('data') and len(res['data']) > 0:
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df.iloc[-1, df.columns.get_loc('close')] = live_spot
                        rsi_v = calculate_tv_rsi(df['close'].astype(float), 14)
                        ema9 = float(df['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                        
                        output_data.update({'live_spot': live_spot, 'rsi_v': rsi_v, 'ema9': ema9, 'nifty_status': '🟢 Active'})
            except Exception as e: output_data['nifty_status'] = f'❌ Error: {str(e)}'

            # 🛢️ CRUDEOIL फेच आणि मॅथ इंजिन
            try:
                crude_ltp_res = smartApi.ltpData("MCX", "CRUDEOIL", CRUDE_TOKEN)
                if crude_ltp_res and crude_ltp_res.get('status') and crude_ltp_res.get('data'):
                    crude_spot = float(crude_ltp_res['data']['ltp'])
                    res_c = smartApi.getCandleData({"exchange": "MCX", "symboltoken": CRUDE_TOKEN, "interval": "FIVE_MINUTE", "fromdate": from_time, "todate": to_time})
                    if res_c and res_c.get('data') and len(res_c['data']) > 0:
                        df_c = pd.DataFrame(res_c['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df_c.iloc[-1, df_c.columns.get_loc('close')] = crude_spot
                        crude_rsi = calculate_tv_rsi(df_c['close'].astype(float), 14)
                        crude_ema9 = float(df_c['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                        
                        output_data.update({'crude_spot': crude_spot, 'crude_rsi': crude_rsi, 'crude_ema9': crude_ema9, 'crude_status': '🟢 Active'})
            except Exception as e: output_data['crude_status'] = f'❌ Error: {str(e)}'

            # 💾 निकाल JSON फोटोकॉपी फाईलमध्ये सेव्ह करणे (लिंकिंगचे माध्यम)
            with open('data_signal.json', 'w') as f:
                json.dump(output_data, f)
                
            time.sleep(2)  # २ सेकंदांचा सेफ सर्व्हर डिले
            
    except Exception as main_e:
        print(f"❌ Main Loop Error: {str(main_e)}")
        time.sleep(5)
        start_backend_factory()

if __name__ == "__main__":
    start_backend_factory()
