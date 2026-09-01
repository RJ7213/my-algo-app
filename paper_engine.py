# Paper engine: consumes data_raw.json + strategy_signal.json only.
import json, logging, os, time
from datetime import datetime, timezone, timedelta
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
IST=timezone(timedelta(hours=5,minutes=30))

def now_ist(): return datetime.now(IST)
def load_json(path,default):
    if not os.path.exists(path): return default
    try:
        with open(path,"r") as f:return json.load(f)
    except Exception as e:
        logging.warning("Could not read %s: %s",path,e);return default

def atomic_write_json(path,payload):
    tmp=f"{path}.tmp"
    with open(tmp,"w") as f:json.dump(payload,f,separators=(",",":"))
    os.replace(tmp,path)

def default_ledger(): return {"wallet_balance":10000.0,"starting_balance":10000.0,"trades":[],"total_trades":0,"target_hits":0,"sl_hits":0,"win_rate":0.0,"total_pnl":0.0}
def recalculate_ledger(dt):
    trades=dt.get("trades",[]); dt["total_trades"]=len(trades)
    closed=[t for t in trades if t.get("status")!="ACTIVE"]
    wins=sum(1 for t in closed if float(t.get("pnl_realized",0))>0)
    dt["target_hits"]=sum(1 for t in trades if t.get("status")=="TARGET_HIT")
    dt["sl_hits"]=sum(1 for t in trades if t.get("status")=="SL_HIT")
    dt["win_rate"]=round(wins/len(closed)*100,1) if closed else 0.0
    start=float(dt.get("starting_balance",10000)); wallet=float(dt.get("wallet_balance",start)); dt["total_pnl"]=round(wallet-start,2); return dt

def load_ledger():
    d=default_ledger(); dt=load_json("trade_history.json",d)
    for k,v in d.items():dt.setdefault(k,v)
    if not isinstance(dt.get("trades"),list):dt["trades"]=[]
    return recalculate_ledger(dt)
def save_ledger(dt):
    dt=recalculate_ledger(dt);atomic_write_json("trade_history.json",dt);return dt
def next_trade_id(trades):
    m=0
    for t in trades:
        s=str(t.get("trade_id",""))
        if s.startswith("T"):
            try:m=max(m,int(s[1:]))
            except ValueError:pass
    return f"T{m+1:06d}"
def quote_age_seconds(ts):
    if not ts:return 999999.0
    try:
        qt=datetime.fromisoformat(ts)
        if qt.tzinfo is None:qt=qt.replace(tzinfo=IST)
        return max(0,(datetime.now(qt.tzinfo)-qt).total_seconds())
    except Exception:return 999999.0
def find_active_trade(ledger):
    return next((t for t in ledger.get("trades",[]) if t.get("status")=="ACTIVE"),None)

def start_paper_engine():
    state_file="paper_engine_state.json"; state=load_json(state_file,{"last_processed_candle":"","last_signal_key":""})
    last_processed_candle=state.get("last_processed_candle",""); last_signal_key=state.get("last_signal_key","")
    logging.info("🟢 Paper trading engine started")
    while True:
        try:
            strat=load_json("strategy_signal.json",None); raw=load_json("data_raw.json",None)
            if not strat or not raw:time.sleep(.5);continue
            ledger=load_ledger(); spot=float(raw.get("live_spot",strat.get("live_spot",0))); q=raw.get("option_quote") or {}
            candle_time=str(strat.get("candle_time","")); trade_type=str(strat.get("trade_type","")); strike=str(strat.get("option_strike","")); signal_key=f"{candle_time}|{trade_type}|{strike}"
            active=find_active_trade(ledger)
            if active:
                active_symbol=str(active.get("option_symbol","")); quote_symbol=str(q.get("tradingsymbol","")); opt_ltp=None
                if quote_symbol==active_symbol:
                    try:opt_ltp=float(q["ltp"])
                    except (TypeError,ValueError):opt_ltp=None
                running=round((opt_ltp-float(active["entry"]))*int(active["qty"]),2) if opt_ltp is not None else 0.0
                active["current_option_ltp"]=opt_ltp;active["running_pnl"]=running;active["last_quote_time"]=q.get("timestamp");active["last_spot"]=spot;save_ledger(ledger)
                typ=str(active.get("type","")); target=float(active.get("index_target",spot)); sl=float(active.get("index_sl",spot))
                target_hit=(typ=="CE_BUY" and spot>=target) or (typ=="PE_BUY" and spot<=target); sl_hit=(typ=="CE_BUY" and spot<=sl) or (typ=="PE_BUY" and spot>=sl)
                if target_hit or sl_hit:
                    reason="TARGET_HIT" if target_hit else "SL_HIT"; qt=q.get("timestamp"); age=quote_age_seconds(qt)
                    if opt_ltp is None or age>5:
                        active["exit_pending"]=True;active["exit_trigger"]=reason;active["exit_trigger_spot"]=spot;active["exit_trigger_time"]=now_ist().isoformat();save_ledger(ledger);logging.warning("⏳ %s reached but waiting for fresh option LTP | %s",reason,active_symbol);time.sleep(.5);continue
                    entry=float(active["entry"]);qty=int(active["qty"]);pnl=round((opt_ltp-entry)*qty,2);active.update({"status":reason,"exit_time":now_ist().strftime("%H:%M:%S"),"exit_price":opt_ltp,"option_exit_ltp":opt_ltp,"pnl_realized":pnl,"running_pnl":0.0,"index_exit":spot,"exit_reason":"INDEX_TARGET" if reason=="TARGET_HIT" else "INDEX_STOP","exit_quote_time":qt,"exit_quote_age":round(age,2)})
                    ledger["wallet_balance"]=round(float(ledger["wallet_balance"])+pnl,2);save_ledger(ledger);last_processed_candle=str(active.get("candle_time",""));last_signal_key=signal_key;atomic_write_json(state_file,{"last_processed_candle":last_processed_candle,"last_signal_key":last_signal_key});logging.info("🔴 TRADE CLOSED | %s | Entry %.2f | Exit %.2f | Qty %d | P&L ₹%.2f | %s",active_symbol,entry,opt_ltp,qty,pnl,reason);time.sleep(.5);continue
            else:
                triggered=bool(strat.get("signal_triggered",False)); new_signal=triggered and candle_time and candle_time!=last_processed_candle and signal_key!=last_signal_key
                if new_signal:
                    typ=str(strat.get("otype","")).upper(); desired_strike=int(float(strat.get("option_strike",round(spot/50)*50))); qt=str(q.get("option_type","")).upper()
                    try:qs=float(q.get("strike",-999999))
                    except (TypeError,ValueError):qs=-999999
                    matches=typ in ("CE","PE") and qt==typ and abs(qs-desired_strike)<.01 and bool(q.get("tradingsymbol"))
                    if not matches:logging.info("🟡 Signal ready but waiting for correct option quote | wanted %s %s | got %s %s",desired_strike,typ,qs,qt)
                    else:
                        try:p=float(q["ltp"])
                        except (TypeError,ValueError):p=0.0
                        qt_time=q.get("timestamp");age=quote_age_seconds(qt_time)
                        if p<=0 or age>5:logging.info("🟡 Waiting for fresh option LTP | LTP=%.2f age=%.1fs",p,age)
                        else:
                            idx_sl=float(strat.get("c_low",spot-15)) if typ=="CE" else float(strat.get("c_high",spot+15))
                            idx_target=float(strat.get("next_w",spot+15)) if typ=="CE" else float(strat.get("next_w",spot-15))
                            idx_dist=abs(spot-idx_sl); premium_sl=max(5.0,min(idx_dist*.50,max(5.0,p*.50))); premium_target=max(10.0,abs(idx_target-spot)*.50)
                            wallet=float(ledger["wallet_balance"]);risk=wallet*.15;lot=65;lots=int(risk/max(premium_sl,1)/lot);qty=max(lot,lots*lot)
                            trade={"trade_id":next_trade_id(ledger["trades"]),"time":now_ist().strftime("%H:%M:%S"),"type":strat.get("trade_type"),"option_symbol":q["tradingsymbol"],"option_token":q.get("symboltoken"),"option_strike":desired_strike,"option_type":typ,"option_expiry":q.get("expiry"),"qty":qty,"entry":round(p,2),"option_entry_ltp":round(p,2),"sl":round(max(.05,p-premium_sl),2),"target":round(p+premium_target,2),"target_dist":round(premium_target,2),"sl_dist":round(premium_sl,2),"index_entry":spot,"index_sl":idx_sl,"index_target":idx_target,"status":"ACTIVE","pnl_realized":0.0,"running_pnl":0.0,"current_option_ltp":p,"strategy_used":strat.get("strategy_used","UNKNOWN"),"candle_time":candle_time,"entry_reason":strat.get("algo_reason",""),"rsi":strat.get("rsi_v"),"ema9":strat.get("ema9"),"ema20":strat.get("ema20"),"volume_ratio":strat.get("vol_val"),"runway":strat.get("run_df"),"trend":strat.get("trend","UNKNOWN"),"option_quote_time":qt_time,"entry_quote_age":round(age,2),"entry_spot":spot,"entry_signal_key":signal_key,"breakout_level":strat.get("breakout_resistance"),"breakout_level_source":strat.get("breakout_resistance_source",""),"order_flow_bias":strat.get("order_flow_bias","UNKNOWN")}
                            ledger["trades"].append(trade);last_signal_key=signal_key;save_ledger(ledger);atomic_write_json(state_file,{"last_processed_candle":last_processed_candle,"last_signal_key":last_signal_key});logging.info("🟢 PAPER ENTRY | %s | %s | Entry ₹%.2f | Qty %d | SL ₹%.2f | Target ₹%.2f | Strategy=%s",q["tradingsymbol"],trade_type,p,qty,trade["sl"],trade["target"],trade["strategy_used"])
        except Exception as exc:logging.exception("Paper engine error: %s",exc)
        time.sleep(.5)
if __name__=="__main__":start_paper_engine()
