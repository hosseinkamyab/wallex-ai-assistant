    def get_history(
        self, symbol: str, resolution: str, start: int, end: int
    ) -> list[Candle]:
        """Fetch historical OHLCV candles from Wallex's UDF endpoint.

        ``start`` and ``end`` are Unix seconds and ``resolution`` follows the
        TradingView UDF contract (15, 60, 240, D, W).
        """
        if start >= end:
            raise ValueError("start must be earlier than end")
        payload = self._http.get(
            "/v1/udf/history",
            params={"symbol": symbol, "resolution": str(resolution), "from": start, "to": end},
        )
        candles = self._candles_from_udf(payload, symbol)
        return sorted(candles, key=lambda candle: candle.open_time)

