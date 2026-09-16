# NIFTY Paper Engine — Implementation Notes

## Final 6-file package

1. `indicator_calc.py` — completed-candle technical calculations, setup identification inputs, Pullback logic and exact selected-option volume tracking.
2. `paper_engine.py` — strategy decision, configurable gate evaluation and paper execution. No live orders.
3. `market_structure.py` — OI, support/resistance, option order-flow and futures structure only. It does not create trade signals.
4. `Trading app.py` — compact/mobile-style Streamlit dashboard with MARKET, TRADE, HISTORY and STRATEGY tabs.
5. `strategy_config.json` — single source for gate modes and strategy thresholds.
6. `IMPLEMENTATION_NOTES.md` — this document.

## Gate configuration

Every gate is controlled by `strategy_config.json` and can be changed from the STRATEGY tab:

- `HARD`: a failed gate blocks entry.
- `SOFT`: a failed gate is reported as a warning but does not block entry.
- `OFF`: the gate is ignored for entry decisions.

Configured gates:

- RSI
- EMA
- Volume
- Runway
- Candle Size
- Opposite Wick
- OI
- Flow

There is no permanent `Volume = SOFT` rule in the Python decision logic. The current default is stored in JSON so it can be changed to `HARD`, `SOFT` or `OFF` from the dashboard.

## Pullback change

The previous 45–55 RSI band is removed.

Pullback RSI is directional and configurable:

- CE Pullback: RSI >= `pullback.ce_rsi_min`
- PE Pullback: RSI <= `pullback.pe_rsi_max`
- Price must remain within `pullback.ema_tolerance` points of EMA9.

Current JSON defaults are CE >= 60, PE <= 40 and EMA9 distance <= 15 points.

## Option volume

The volume gate is tied to the **exact selected option contract** (`strike:CE` or `strike:PE`), not NIFTY futures volume.

The broker field is cumulative day volume. The indicator engine tracks cumulative snapshots by 5-minute bucket and converts them into bucket-volume deltas. The latest completed bucket is compared with previous completed buckets to produce the volume ratio.

After a restart, there may be insufficient option-volume history. In that case the value is reported as `DATA WAIT`/invalid rather than pretending that cumulative day volume is a 5-minute candle volume.

## Candle timing

Entries are based on the latest completed 5-minute candle. The currently forming candle is display-only and cannot create a new entry.

## Paper execution

`paper_engine.py` remains paper-only. It uses the actual selected option quote from the raw option chain and requires a fresh option quote before creating an entry. No broker order placement is added.

## Dashboard ownership

The dashboard displays engine outputs. It does not independently calculate RSI, EMA, OI, flow, setup or trade decisions.

The STRATEGY tab only edits `strategy_config.json`. The paper engine remains the authority for entry decisions.

## Deployment

Keep `data_worker.py`, `run.sh`, `requirements.txt` and any existing persistence module from the current deployment alongside these six files. This six-file package is the strategy/dashboard layer requested here; it does not replace the raw-data worker.
