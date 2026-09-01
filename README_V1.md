# NIFTY Algo V1 — Live Paper Observation Build

## Important
This is a paper-trading observation build. It does not place live orders.

## Data architecture
Only `data_worker.py` communicates with Angel One. It publishes:
- live NIFTY spot
- 5-minute historical candles
- resolved nearest-expiry NIFTY option contract
- live option LTP

`indicator_calc.py` creates signals and the option strike hint.
`paper_engine.py` consumes the published option LTP and records paper trades.
`Trading app.py` displays actual option-LTP-based running P&L.

## Environment variables
Copy `.env.example` into your deployment secrets/environment settings. Do not commit real credentials.

## Run order
1. data_worker.py
2. indicator_calc.py
3. paper_engine.py
4. streamlit run "Trading app.py"

## Paper P&L
Running and realized paper P&L use the actual NFO option LTP supplied by the Data Worker. No fixed ₹100 entry and no 0.50-delta running-P&L approximation are used.

The strategy's index target/stop still determines the exit trigger in this V1 observation build. The actual option LTP at the trigger is used as the option exit price for P&L.
