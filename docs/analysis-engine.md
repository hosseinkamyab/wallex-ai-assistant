# Cryptocurrency analysis engine methodology

The deterministic engine lives in `wallex_assistant.analysis`; indicator and scoring code does not call an LLM. It uses actual Wallex OHLCV history via `GET /v1/udf/history`, requesting UDF resolutions `15`, `60`, `240`, `D`, and `W`. `MarketClient.get_history` returns UTC-sorted `Candle` objects. API failures are isolated per symbol/timeframe and surfaced in result warnings; failed or missing data is never substituted with synthetic values.

## Indicators and data sufficiency

RSI(14), ATR(14), and directional movement/ADX(14) use Wilder exponential smoothing. MACD is EMA(12)-EMA(26), with EMA(9) signal. EMA(9/21/50/200), SMA(20/50/200), and 20-period Bollinger Bands (2 population standard deviations) are calculated from close prices. Volume comparisons use a 20-candle mean, momentum is the 10-candle close-to-close change, and support/resistance are the low/high extremes over the latest 50 bars. Trend is bullish/bearish only when close, EMA21, and EMA50 align; ADX describes strength. Missing inputs remain null. A signal requires at least 50 candles in daily and one other timeframe; otherwise the signal and score are null. Long-period indicators (such as EMA200) stay null until enough bars exist.

## Score and recommendation

Scores map independent evidence-group values in [-1, 1] to [0, 100]. Defaults: trend 22%, momentum 18%, volume 10%, volatility 10%, timeframe agreement 18%, risk/reward 12%, market 10%. Weights are configurable with `ScoringWeights` and normalized at evaluation. RSI, MACD, and momentum form one momentum composite; moving-average structure forms one trend group, rather than treating correlated indicators as separate votes. Unavailable groups are omitted and the remaining weights renormalized. This score is not a probability or forecast. A bullish daily trend combined with a bearish 1h trend produces `WAIT FOR ENTRY`. Elevated market risk prevents a BUY recommendation. The BTC daily trend and cross-market daily breadth inform market conditions.

The rules are deterministic; `AnalysisResult.explanation` is generated from the structured evidence, not by an AI model. The application remains decision-support only and does not execute trades. Signals are not personalized financial advice.

## API

```python
from wallex_assistant.analysis import ScoringWeights, analyze_with_client
from wallex_assistant.market_client import MarketClient

client = MarketClient.from_settings()
try:
    context, results = analyze_with_client(client, ["BTCTMN", "ETHTMN"], bars=300,
                                           weights=ScoringWeights())
finally:
    client.close()
```
