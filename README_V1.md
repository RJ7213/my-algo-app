# NIFTY Paper App - Data Pipeline Fix

This package restores the data flow needed by the existing paper strategy without enabling live orders.

## Fixed
- Live NIFTY spot remains WebSocket-driven.
- Live 5-minute spot candles are retained across candle boundaries instead of resetting every tick.
- Historical spot REST backfill is no longer repeatedly called every minute, reducing Angel One rate-limit errors.
- NIFTY futures FULL/SNAP quote fields now expose buy quantity, sell quantity and OI.
- NIFTY futures 5-minute candles are maintained for the volume-ratio gate; startup history is requested once when available.
- Full NIFTY option chain (current master, up to 608 contracts in this project) is subscribed in SNAP_QUOTE mode and published into `data_raw.json`.
- Option LTP, OI, OI change, volume, total buy/sell and best-5 data are preserved for `market_structure.py`.
- `indicator_calc.py` now publishes the fields expected by `paper_engine.py`: completed candles, level engine, RSI/EMA aliases and signal volume ratio.
- Support/resistance levels are exposed in `processed_indicators.json` from day extremes, recent swing points and psychological levels. EMA is not used as a level.
- `paper_engine.py` now shows a complete NONE decision snapshot even when no setup exists, so the TRADE tab does not go blank while waiting for a setup.
- Existing paper-only execution and persistence behavior are retained.

## No live orders
`paper_engine.py` remains PAPER ONLY. No live order placement is added.


## v3 hotfix
- `data_worker.py` now publishes `market_status` and `worker_status`; WebSocket connectivity no longer masquerades as market-open status.
- `paper_engine.py` keeps a complete latest decision/gate snapshot visible after market close, while blocking new entries/exits.
- `Trading app.py` shows CLOSED when the exchange session is closed even if WebSocket remains connected.
