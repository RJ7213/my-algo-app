            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@app.get("/api/dashboard")
def dashboard():
    values = _load_dashboard_values()

    return jsonify({
        "api_version": 2,
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "raw": values["raw"],
        "indicators": values["indicators"],
        "market_structure": values["market_structure"],
        "paper": values["paper"],
        "source_files": {k: v.name for k, v in FILES.items()},
    })


def _trade_duration_seconds(trade: dict[str, Any]) -> float | None:
    """Calculate elapsed seconds from saved entry/exit timestamps when possible."""
    from datetime import datetime
    entry = trade.get("entry_time")
    exit_time = trade.get("exit_time")
    if not entry or not exit_time:
        return None
    try:
        start = datetime.fromisoformat(str(entry).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00"))
        if start.tzinfo is None and end.tzinfo is not None:
            start = start.replace(tzinfo=end.tzinfo)
        elif end.tzinfo is None and start.tzinfo is not None:
            end = end.replace(tzinfo=start.tzinfo)
        return max(0.0, round((end - start).total_seconds(), 3))
    except (TypeError, ValueError, OverflowError):
        return None


@app.get("/api/trade-history")
def trade_history():
    """Read saved paper trades; this endpoint never places broker orders or writes data."""
    ledger = None
    source = None
    try:
        bundle = load_supabase_bundle()
        if isinstance(bundle, tuple) and len(bundle) >= 1 and isinstance(bundle[0], dict):
            ledger = bundle[0]
            source = "supabase"
    except Exception:
        ledger = None

    # Fallback to the existing paper-engine output file if Supabase is unavailable.
    if not isinstance(ledger, dict):
        paper = load_file(FILES["paper"]) or {}
        if isinstance(paper, dict):
            candidate = paper.get("ledger")
            if isinstance(candidate, dict):
                ledger = candidate
                source = "local_paper_output"
            elif isinstance(paper.get("trades"), list):
                ledger = paper
                source = "local_paper_output"

    if not isinstance(ledger, dict):
        return jsonify({
            "status": "unavailable",
            "mode": "PAPER_ONLY",
            "source": None,
            "count": 0,
            "trades": [],
            "message": "No readable paper-trade ledger is currently available.",
        }), 503

    trades = ledger.get("trades", [])
    if not isinstance(trades, list):
        trades = []

    normalized = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        item = dict(trade)
        item["duration_seconds"] = _trade_duration_seconds(item)
        normalized.append(item)

    # Newest trade first; do not mutate or rewrite the saved ledger.
    normalized.sort(
        key=lambda t: str(t.get("entry_time") or t.get("time") or ""),
        reverse=True,
    )
    return jsonify({
        "status": "ok",
        "mode": "PAPER_ONLY",
        "live_orders": False,
        "source": source,
        "count": len(normalized),
        "summary": {
            "total_trades": ledger.get("total_trades", len(normalized)),
            "closed_trades": ledger.get("closed_trades", sum(1 for t in normalized if t.get("exit_time"))),
            "wins": ledger.get("wins"),
            "losses": ledger.get("losses"),
            "realized_pnl": ledger.get("realized_pnl", ledger.get("total_pnl")),
            "wallet_balance": ledger.get("wallet_balance"),
        },
        "trades": normalized,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
