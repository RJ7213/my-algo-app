NIFTY DATA PIPELINE FIX

1. data_worker.py now builds live NIFTY 5-minute OHLC candles directly from Angel One WebSocket ticks.
2. data_worker.py now builds NIFTY futures 5-minute volume from cumulative day-volume deltas.
3. indicator_calc.py gives local WebSocket-built candles/volume priority over stale historical API data.
4. Historical candle API is backfill only and is throttled to reduce Angel rate-limit errors.
5. Strategy architecture is unchanged: no CALL/PUT or BUY/SELL decisions in either worker or indicator_calc.
6. paper_engine.py remains the only decision/paper execution engine.
7. RSI/EMA are still calculated from 5-minute NIFTY closes; LIVE values now include the locally built current candle even when historical API is rate-limited.
8. Volume completed-candle ratio uses locally accumulated futures volume when available.
