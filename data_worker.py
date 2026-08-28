# data_worker.py
import time, pyotp, json
import pandas as pd, numpy as np
from datetime import datetime, timedelta

CID, AKEY, PIN = "R990942", "c75cUJga", "8547"
TKEY, NIFTY_TOKEN = "FQ7TSLI3L2UUKWZOC3TOJEFI6E", "99926000"

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
        api = SmartConnect(api_key=AKEY, timeout=15)
        tok = pyotp.TOTP(TKEY.replace(" ", "").strip().upper()).now()
        if not api.generateSession(CID, PIN, tok)['status']: return
        while True:
            now_dt = datetime.utcnow() + timedelta(hours=5, minutes=30)
            try:
                ltp = api.ltpData("NSE", "NIFTY", NIFTY_TOKEN)
                if ltp and ltp.get('status'):
                    spot = float(ltp['data']['ltp'])
                    res = api.getCandleData({"exchange": "NSE", "symboltoken": NIFTY_TOKEN, "interval": "FIVE_MINUTE", "fromdate": (now_dt - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"), "todate": now_dt.strftime("%Y-%m-%d %H:%M")})
                    if res and res.get('data'):
                        df = pd.DataFrame(res['data'], columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                        df.iloc[-1, df.columns.get_loc('close')] = spot
                        rsi_v = calculate_tv_rsi(df['close'].astype(float), 14)
                        ema9 = float(df['close'].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
                        with open('data_signal.json', 'w') as f:
                            json.dump({'live_spot': spot, 'rsi_v': rsi_v, 'ema9': ema9, 'candles': res['data'], 'last_update': now_dt.strftime("%H:%M:%S")}, f)
            except: pass
            time.sleep(3)
    except: time.sleep(10); start_backend_factory()

if __name__ == "__main__": start_backend_factory()
