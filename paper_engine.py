# paper_engine.py
# Paper engine NEVER calls Angel One directly. It consumes option LTP published by data_worker.py.

import json
import logging
import os
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)


def manage_ledger(new_t=None, update_trade_id=None, update_pnl=None):
    f_name = "trade_history.json"
    default = {
        "wallet_balance": 10000.0,
        "starting_balance": 10000.0,
        "trades": [],
        "total_trades": 0,
        "target_hits": 0,
        "sl_hits": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
    }
    dt = load_json(f_name, default)
    for k, v in default.items():
        dt.setdefault(k, v)

    if new_t:
        dt["trades"].append(new_t)
        dt["total_trades"] = len(dt["trades"])

    if update_pnl and update_trade_id:
        for t in dt["trades"]:
            if t.get("trade_id") == update_trade_id and t.get("status") == "ACTIVE":
                t.update(update_pnl)
                dt["wallet_balance"] = round(float(dt["wallet_balance"]) + float(update_pnl.get("pnl_realized", 0.0)), 2)
                dt["total_pnl"] = round(float(dt["wallet_balance"]) - float(dt["starting_balance"]), 2)
                if update_pnl.get("status") == "TARGET_HIT":
                    dt["target_hits"] += 1
                elif update_pnl.get("status") == "SL_HIT":
                    dt["sl_hits"] += 1
                break

    closed = [t for t in dt["trades"] if t.get("status") != "ACTIVE"]
    wins = sum(1 for t in closed if float(t.get("pnl_realized", 0)) > 0)
    dt["win_rate"] = round((wins / len(closed)) * 100, 1) if closed else 0.0
    atomic_write_json(f_name, dt)
    return dt


def next_trade_id(trades):
    return f"T{len(trades) + 1:06d}"


def start_paper_engine():
    state_file = "paper_engine_state.json"
    state = load_json(state_file, {"last_processed_candle": "", "last_signal_key": ""})
    last_processed_candle = state.get("last_processed_candle", "")
    last_signal_key = state.get("last_signal_key", "")

    while True:
        strat = load_json("strategy_signal.json", None)
        if not strat:
            time.sleep(1)
            continue

        try:
            raw = load_json("data_raw.json", {})
            hist = manage_ledger()
            spot = float(raw.get("live_spot", strat.get("live_spot", 0)))
            option_quote = raw.get("option_quote") or {}
            candle_time = str(strat.get("candle_time", ""))
            signal_key = f"{candle_time}|{strat.get('trade_type')}|{strat.get('option_strike')}"

            active = next((t for t in hist["trades"] if t.get("status") == "ACTIVE"), None)

            if active:
                # Exit trigger remains index-structure based, but actual P&L uses actual option LTP.
                opt_ltp = None
                if option_quote.get("tradingsymbol") == active.get("option_symbol"):
                    try:
                        opt_ltp = float(option_quote["ltp"])
                    except (TypeError, ValueError):
                        pass

                current_pnl = 0.0
                if opt_ltp is not None:
                    direction = 1 if active["type"] == "CE_BUY" or active["type"] == "PE_BUY" else 1
                    current_pnl = round((opt_ltp - float(active["entry"])) * int(active["qty"]) * direction, 2)

                active["current_option_ltp"] = opt_ltp
                active["running_pnl"] = current_pnl
                active["last_quote_time"] = option_quote.get("timestamp")
                # Save running state without changing realized wallet.
                atomic_write_json("trade_history.json", hist)

                is_ce_target = active["type"] == "CE_BUY" and spot >= float(active["index_target"])
                is_pe_target = active["type"] == "PE_BUY" and spot <= float(active["index_target"])
                is_ce_sl = active["type"] == "CE_BUY" and spot <= float(active["index_sl"])
                is_pe_sl = active["type"] == "PE_BUY" and spot >= float(active["index_sl"])

                if is_ce_target or is_pe_target or is_ce_sl or is_pe_sl:
                    # Never invent an option exit price. Wait for a fresh option quote.
                    quote_age = 999.0
                    if option_quote.get("timestamp"):
                        try:
                            qt = datetime.fromisoformat(option_quote["timestamp"])
                            quote_age = (datetime.now(qt.tzinfo) - qt).total_seconds()
                        except Exception:
                            pass
                    if opt_ltp is None or quote_age > 5:
                        active["exit_pending"] = True
                        active["exit_trigger"] = "TARGET_HIT" if (is_ce_target or is_pe_target) else "SL_HIT"
                        atomic_write_json("trade_history.json", hist)
                        time.sleep(0.5)
                        continue

                    exit_reason = "TARGET_HIT" if (is_ce_target or is_pe_target) else "SL_HIT"
                    exit_price = opt_ltp
                    pnl = round((exit_price - float(active["entry"])) * int(active["qty"]), 2)
                    update = {
                        "status": exit_reason,
                        "exit_time": (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S"),
                        "exit_price": exit_price,
                        "option_exit_ltp": exit_price,
                        "pnl_realized": pnl,
                        "exit_reason": "INDEX_TARGET" if exit_reason == "TARGET_HIT" else "INDEX_STOP",
                        "index_exit": spot,
                        "running_pnl": 0.0,
                    }
                    manage_ledger(update_trade_id=active["trade_id"], update_pnl=update)
                    last_processed_candle = active["candle_time"]
                    last_signal_key = signal_key
                    atomic_write_json(state_file, {"last_processed_candle": last_processed_candle, "last_signal_key": last_signal_key})

            else:
                # Observation phase: NO daily trade limit. Still avoid duplicate execution of the same signal/candle.
                if strat.get("signal_triggered") and candle_time != last_processed_candle and signal_key != last_signal_key:
                    desired_symbol_type = strat.get("otype")
                    desired_strike = int(float(strat.get("option_strike", round(spot / 50.0) * 50)))
                    quote_matches = (
                        option_quote.get("option_type") == desired_symbol_type
                        and abs(float(option_quote.get("strike", -999999)) - desired_strike) < 0.01
                        and option_quote.get("tradingsymbol")
                    )

                    # Do not create a trade with a fake ₹100 premium. Wait for a fresh real option LTP from Data Worker.
                    if quote_matches:
                        try:
                            p_entry = float(option_quote["ltp"])
                        except (TypeError, ValueError):
                            p_entry = 0.0

                        quote_time = option_quote.get("timestamp")
                        quote_age = 999.0
                        if quote_time:
                            try:
                                qt = datetime.fromisoformat(quote_time)
                                quote_age = (datetime.now(qt.tzinfo) - qt).total_seconds()
                            except Exception:
                                pass

                        if p_entry > 0 and quote_age <= 5:
                            idx_sl = float(strat.get("c_low", spot - 15) if desired_symbol_type == "CE" else strat.get("c_high", spot + 15))
                            idx_target = float(strat.get("next_w", spot + 15 if desired_symbol_type == "CE" else spot - 15))
                            idx_sl_dist = abs(spot - idx_sl)
                            premium_sl_dist = max(5.0, min(idx_sl_dist * 0.50, max(5.0, p_entry * 0.50)))
                            premium_target_dist = max(10.0, abs(idx_target - spot) * 0.50)

                            max_allowed_risk = float(hist["wallet_balance"]) * 0.15
                            qty_final = max(65, int((max_allowed_risk / max(premium_sl_dist, 1.0)) / 65) * 65)

                            trade = {
                                "trade_id": next_trade_id(hist["trades"]),
                                "time": (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M:%S"),
                                "type": strat["trade_type"],
                                "option_symbol": option_quote["tradingsymbol"],
                                "option_token": option_quote["symboltoken"],
                                "option_strike": desired_strike,
                                "option_type": desired_symbol_type,
                                "option_expiry": option_quote.get("expiry"),
                                "qty": qty_final,
                                "entry": p_entry,
                                "option_entry_ltp": p_entry,
                                "sl": round(max(0.05, p_entry - premium_sl_dist), 2),
                                "target": round(p_entry + premium_target_dist, 2),
                                "target_dist": premium_target_dist,
                                "sl_dist": premium_sl_dist,
                                "index_entry": spot,
                                "index_sl": idx_sl,
                                "index_target": idx_target,
                                "status": "ACTIVE",
                                "pnl_realized": 0.0,
                                "running_pnl": 0.0,
                                "strategy_used": strat["strategy_used"],
                                "candle_time": candle_time,
                                "entry_reason": strat.get("algo_reason", ""),
                                "rsi": strat.get("rsi_v"),
                                "ema9": strat.get("ema9"),
                                "ema20": strat.get("ema20"),
                                "volume_ratio": strat.get("vol_val"),
                                "runway": strat.get("run_df"),
                                "trend": strat.get("trend", "UNKNOWN"),
                                "option_quote_time": quote_time,
                            }
                            manage_ledger(new_t=trade)
                            last_signal_key = signal_key
                            atomic_write_json(state_file, {"last_processed_candle": last_processed_candle, "last_signal_key": last_signal_key})
        except Exception as exc:
            logging.exception("Paper engine error: %s", exc)

        time.sleep(0.5)


if __name__ == "__main__":
    start_paper_engine()
