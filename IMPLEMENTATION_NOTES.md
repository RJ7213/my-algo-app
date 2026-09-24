NIFTY ALGO — Strategy Settings Integration

WHAT THIS VERSION DOES
1. Flutter STRATEGY tab loads GET /api/strategy.
2. Major Rejection, Pullback and Breakout have separate gate settings.
3. Each gate can be HARD / SOFT / OFF.
4. Threshold settings are saved through PUT /api/strategy.
5. paper_engine.py selects the configuration of the strategy it actually detected.
6. Paper engine remains the authority for the actual entry decision.
7. No broker order placement is added; mode remains PAPER_ONLY.

RENDER FILES TO REPLACE
- api_server.py
- paper_engine.py
- strategy_config.json

FLUTTER FILE
- Replace lib/main.dart with main.dart.

IMPORTANT
- Keep the existing run/start script.
- Flask/flask-cors are already required by the current API migration.
- Before deploying, make a backup of the current paper_engine.py and strategy_config.json.
- The existing trade ledger/state files are not deleted by these changes.

OPTIONAL SECURITY
The PUT /api/strategy endpoint supports an environment variable:
STRATEGY_API_KEY

If you set STRATEGY_API_KEY in Render, run Flutter with:
--dart-define=STRATEGY_API_KEY=YOUR_KEY

For a paper-only personal test, the endpoint works without this variable, but a public PUT endpoint can be changed by anyone who discovers it. Setting the key is recommended.

DEPLOY ORDER
1. Replace api_server.py
2. Replace paper_engine.py
3. Replace strategy_config.json
4. Commit + push to GitHub
5. Render redeploy
6. Verify:
   /api/health
   /api/dashboard
   /api/strategy
7. Replace Flutter lib/main.dart
8. Run:
   flutter clean
   flutter pub get
   flutter run

BEHAVIOR
When Pullback settings are saved, only the Pullback configuration is used when the paper engine identifies a Pullback setup.
When Breakout settings are saved, only Breakout configuration is used for a Breakout setup.
When Major Rejection settings are saved, only Major Rejection configuration is used for that setup.

The setup-detection algorithms themselves remain the existing ones. The new independent configuration controls the gates and thresholds already consumed by paper_engine.py.
