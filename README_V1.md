NIFTY ALGO — ONLY FILES TO REPLACE

BACKEND (project root):
1. data_worker.py
2. indicator_calc.py
3. paper_engine.py
4. api_server.py
5. strategy_config.json

FLUTTER:
6. flutter/main.dart -> replace your Flutter project's lib/main.dart

DO NOT replace:
- market_structure.py
- persistent_store.py
- start.sh

Backend: commit/push these files and redeploy Render.
Flutter: run flutter clean, flutter pub get, flutter run.

Paper-only architecture remains. No live broker orders are sent.
