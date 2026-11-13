# Wallex AI Assistant

A modular, read-only cryptocurrency market and portfolio assistant for Wallex. The project is designed to fetch public market data, optionally read account balances when a Wallex API key is configured, and surface evidence-based market intelligence without enabling trading actions.

## Overview

This repository is intended as a decision-support dashboard for cryptocurrency market intelligence. It focuses on:

- public Wallex market discovery and pricing
- market activity and trend summaries
- portfolio valuation from account balances when a key is connected
- read-only access safety and guardrails
- extensible technical-analysis and recommendation architecture
- deterministic multi-timeframe crypto analysis grounded in real OHLCV data

The app is deliberately read-only by design. It does not place orders, transfer funds, or withdraw assets.

## Cryptocurrency Analysis and Decision Engine

The repository now includes a deterministic cryptocurrency analysis engine in `wallex_assistant/analysis.py`.

It is designed to:

- fetch real historical OHLCV candles from Wallex via the official TradingView-style UDF endpoint
- analyze supported markets across multiple timeframes: 15m, 1h, 4h, 1d, and 1w
- calculate technical indicators including RSI(14), MACD, EMA/SMA, Bollinger Bands, ATR, ADX, and trend strength
- detect market context such as Bitcoin direction, breadth, volatility, risk conditions, and support/resistance zones
- compare short-, medium-, and long-term structure to avoid simplistic buy/sell outputs
- generate transparent signals such as STRONG BUY, BUY, WAIT FOR ENTRY, HOLD, TAKE PROFIT, SELL, STRONG SELL, and AVOID
- score evidence on a 0-100 scale using configurable weights while avoiding double-counting correlated indicators
- skip recommendations when data is insufficient and surface warnings for API failures or missing candles

The engine is intentionally separated from any AI generation layer. Indicator math and scoring are deterministic and reproducible; the narrative explanation is generated from structured data, not guessed.

### Signal methodology

The scoring uses configurable weights through `ScoringWeights` and normalizes the active evidence groups for the final score. The weights are designed to combine independent evidence groups such as:

- trend strength
- momentum
- volume confirmation
- volatility
- multi-timeframe agreement
- risk/reward context
- market conditions

Correlated indicators are grouped into a few evidence categories instead of being counted as multiple independent confirmations.

### Data sufficiency requirements

The engine will not produce a signal if insufficient historical data is available. For a symbol to receive a trade recommendation, a minimum number of candles is required on the daily timeframe and at least one additional timeframe. If data is missing or the API fails for some timeframe, the engine returns a warning and avoids inventing values.

### Example usage

```python
from wallex_assistant.analysis import ScoringWeights, analyze_with_client
from wallex_assistant.market_client import MarketClient

client = MarketClient.from_settings()
try:
    context, results = analyze_with_client(
        client,
        ["BTCTMN", "ETHTMN"],
        bars=300,
        weights=ScoringWeights(),
    )
    for item in results:
        print(item.symbol, item.signal, item.score)
        print(item.explanation)
finally:
    client.close()
```

### Documentation

Additional methodology notes are available in `docs/analysis-engine.md`.

## Official Wallex API endpoints

The project should use the documented Wallex endpoints and avoid deprecated or guessed routes.

Verified/publicly used endpoints for the application:

- Market discovery:
  - `GET https://api.wallex.ir/hector/web/v1/markets`
- Order book depth:
  - `GET https://api.wallex.ir/v1/depth?symbol=BTCTMN`
- Recent trades:
  - `GET https://api.wallex.ir/v1/trades?symbol=BTCTMN`
- Historical OHLC candles:
  - `GET https://api.wallex.ir/v1/udf/history?symbol=BTCTMN&resolution=60&from=...&to=...`
- Account balances:
  - `GET https://api.wallex.ir/v1/account/balances`
- Open orders:
  - `GET https://api.wallex.ir/v1/account/openOrders`
- Fills:
  - `GET https://api.wallex.ir/v1/account/fills`

The following route is not valid for Wallex and must not be used:

- `GET /v1/market-status` (this is the source of the live 404 currently seen in the app)

## Quick start on Windows

Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Connect a Wallex API key inside the app

You do not need to configure a key in PowerShell before launching the application.

1. Start the app with `streamlit run streamlit_app.py`.
2. Open the sidebar and go to API Settings.
3. Paste your Wallex API key into the password-masked field.
4. Click Connect.
5. The app validates the key using a safe read-only request.
6. Connection status is shown in the UI.
7. Invalid keys, permission issues, expired keys, and network failures are surfaced clearly.
8. You can disconnect and replace the key at any time.

Important:

- The key is stored only in Streamlit `session_state`.
- The full key is never displayed.
- The key is never written to source files, logs, or unencrypted config files.
- Public market data continues to work without a key.

## Features

### Public market overview

- latest prices
- 24h price changes
- trading volumes and market activity
- active symbols and market discovery
- market summary cards and charts

### Portfolio intelligence

- account balances when a valid Wallex key is connected
- total portfolio value calculations
- per-asset value breakdowns
- concentration and allocation awareness

### Technical analysis foundation

The project includes a modular technical-analysis architecture for:

- RSI
- MACD
- SMA and EMA
- Bollinger Bands
- ATR
- ADX
- support and resistance estimation
- volume and momentum analysis
- multi-timeframe analysis when historical data is available

### Investment recommendation framing

The dashboard supports evidence-based scoring for:

- trend direction
- momentum
- volume
- volatility
- multi-timeframe agreement
- risk and support/resistance context

Recommendations are designed to explain the evidence behind them, not to promise profits.

### AI market analyst architecture

The project separates:

- market-data collection
- technical calculations
- recommendation logic
- UI rendering
- AI interpretation layer

This keeps the AI grounded in structured market data instead of unsupported assumptions.

## Safety and security requirements

This application is designed as an investment decision-support tool, not an autonomous trading bot.

It intentionally avoids:

- automatic buy/sell order placement
- withdrawal functionality
- exposing API credentials in the UI or logs
- unsafe or mutating API routes

## Architecture notes

The project is organized into modular components:

- `wallex_assistant/config.py` for settings and secret handling
- `wallex_assistant/http.py` for HTTP transport and retries
- `wallex_assistant/market_client.py` for public market parsing and OHLCV history
- `wallex_assistant/analysis.py` for deterministic technical analysis and scoring
- `wallex_assistant/account_client.py` for account balance access
- `wallex_assistant/portfolio.py` for aggregation and valuation
- `wallex_assistant/readonly.py` for read-only enforcement
- `streamlit_app.py` for the dashboard UI

## Market candle response validation

Historical candles are parsed using the Wallex TradingView UDF response contract. A status of `ok` indicates data, `no_data` is a valid empty result, and unknown statuses are treated as API response errors rather than fabricated data.

## Testing

Run the default test suite with:

```powershell
python -m pytest
```

Focused checks can be run like this:

```powershell
python -m pytest tests/test_market_client.py
python -m pytest tests/test_analysis.py
python -m pytest tests/test_account_client.py
python -m pytest tests/test_readonly.py
python -m pytest tests/test_portfolio.py
```

A syntax-only check for the Python package and Streamlit entry point can also be run with:

```powershell
python -m compileall -q wallex_assistant streamlit_app.py
```

## Known limitations

- Public market data works without a key, but account data requires a valid Wallex API key.
- Some advanced analysis features depend on historical candle availability.
- API response shapes can vary slightly between endpoints or payload versions; the parser is purposely defensive.
- Signals are assistive and should not be treated as guaranteed predictions.
- The app does not include automated trading.

## Security note

This project remains read-only by design. It does not place trades, withdraw funds, or transfer assets. Any future features must maintain this restriction.
