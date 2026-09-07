if fh:

    future_candles = fh[-300:]

    # Re-add the currently forming futures candle
    # after historical futures candles are loaded.
    if (
        future_tick is not None
        and is_continuous_timestamp(
            future_tick.get("timestamp")
        )
    ):

        future_price = safe_float(
            future_tick.get("ltp")
        )

        if future_price is not None:

            future_candles = update_live_candle(
                future_candles,
                future_tick["timestamp"],
                future_price,
                future_tick.get(
                    "volume_increment",
                    0.0,
                ),
            )[-300:]

            future_live_candle = (
                future_candles[-1]
                if future_candles
                else None
            )

    save_cached_candles_file(
        FUTURE_CANDLE_CACHE_FILE,
        future_candles,
        now_dt.isoformat(),
    )

    logging.info(
        "NIFTY futures candles updated: %d",
        len(future_candles),
    )
