#!/bin/bash
python data_worker.py &
python indicator_calc.py &
python paper_engine.py &
streamlit run "Trading app.py" --server.port $PORT --server.address 0.0.0.0
