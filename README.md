# Wallex AI Assistant

A read-only Streamlit dashboard and Python toolkit for Wallex public market data, portfolio valuation, and deterministic cryptocurrency market analysis. It can display public market information without credentials and retrieve account balances after you enter a Wallex API key in the app.

> **Safety:** The project does not place orders, transfer funds, or withdraw assets. Market analysis is informational and is not financial advice or a guarantee of results.

## What is implemented

- **Streamlit dashboard** in `streamlit_app.py`, with an overview chart, balances table, portfolio summary, language selection (English/Persian), and analysis tab.
- **Wallex market client** (`wallex_assistant/market_client.py`) for public markets, ticker data, order book, recent trades, and UDF OHLCV history.
- **Account client** (`wallex_assistant/account_client.py`) for read-only account balance access using the Wallex API key.
- **Portfolio valuation** (`wallex_assistant/portfolio.py`) using `Decimal` arithmetic for holdings and TMN estimates.
- **Deterministic market-analysis library** (`wallex_assistant/analysis.py`) with technical indicators, multi-timeframe evidence scoring, warnings, and signals. This analysis engine is a Python library; the current dashboard's analysis tab displays portfolio analysis rather than presenting these market signals.
- **Portfolio analysis** with a deterministic fallback; OpenRouter-backed LLM analysis is supported when configured. Other provider names in configuration are not implemented as live integrations.
- **Read-only transport and guardrails** (`wallex_assistant/http.py`, `wallex_assistant/readonly.py`) with request timeouts, retry handling, and API error types.
- **Offline automated tests** under `tests/`.

### Not currently implemented in the dashboard

- Automated trading, order placement, withdrawals, or transfers (intentionally excluded).
- A UI for browsing ranked market-analysis signals; use the `wallex_assistant.analysis` Python API for deterministic market analysis.
- Live integrations for Anthropic, Gemini, and direct OpenAI LLM providers; selecting those names falls back to a deterministic summary.
- Backtesting or a guarantee that any signal is profitable.

## Architecture

```text
streamlit_app.py                 Streamlit UI and in-session API-key entry
wallex_assistant/
  account_client.py               Read-only account/balance API client
  analysis.py                     Indicators, market context, scoring and signals
  config.py                       Environment-backed settings and secret masking
  errors.py                       Typed API exceptions
  http.py                         Shared requests transport, timeouts and retries
  i18n.py                         English/Persian labels and formatting
  llm_client.py                   Portfolio-analysis provider/fallback logic
  logging_setup.py                Logging configuration
  market_client.py                Public markets, ticker, depth, trades and candles
  portfolio.py                    Portfolio access, valuation and analysis orchestration
  readonly.py                     Read-only API restrictions
 tests/                            Offline unit tests
 docs/analysis-engine.md           Market-analysis methodology notes
```

The UI is kept separate from API clients and business logic. Market-analysis calculations are deterministic and do not require an LLM. They need enough historical OHLCV data for the requested timeframe; when data is insufficient, the engine does not create a signal.

## Technologies

- Python 3.10 or newer
- Streamlit
- Requests
- NumPy and pandas (indicator calculations)
- python-dotenv (optional local environment-file loading)
- `unittest`-compatible tests (no test framework is required)

## Windows installation (PowerShell)

From the repository directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use the Python executable in the environment directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the application

```powershell
streamlit run streamlit_app.py
```

Streamlit prints a local URL (usually `http://localhost:8501`) to open in your browser. The app attempts to load public market data without an API key. Wallex account balances require a valid key.

## Enter a Wallex API key

1. Open the **API Configuration** section in the sidebar.
2. Enter the key in the password-masked **Wallex API key** field.
3. Select **Save & Connect**. The app validates it using the read-only `GET /v1/account/balances` endpoint.
4. Use **Clear key** to remove it from the current Streamlit session.

The app keeps the entered key in Streamlit session state for the current session; it does not write this in-app key to a project file. Public market data does not require the key. For local configuration outside the UI, `wallex_assistant/config.py` can also read `WALLEX_API_KEY` from the process environment or a local `.env` file. `.env` files are ignored by Git; do not commit credentials.

Use a Wallex key with only the permissions required to read account information. Do not share screenshots or logs that might contain sensitive account information. The key is sent to Wallex as the `x-api-key` HTTP header, not as a URL parameter.

## Wallex API communication

The shared transport in `wallex_assistant/http.py` performs GET requests with explicit timeouts, limited retries for transient errors, and typed errors. The market client uses the public markets route `/hector/web/v1/markets`, public market routes such as `/v1/depth` and `/v1/trades`, and TradingView-style history at `/v1/udf/history`. Account balances use `/v1/account/balances`. The API response parsers validate expected shapes. No live API call is guaranteed by the offline test suite.

## Market analysis and signals

`wallex_assistant/analysis.py` calculates RSI, MACD, moving averages, Bollinger Bands, ATR, ADX, volume metrics, trend, and support/resistance estimates from supplied Wallex candles. Its multi-timeframe analyzer combines weighted evidence groups and returns explainable signals and warnings. Scores are evidence scores, **not** probabilities or return forecasts. See `docs/analysis-engine.md` for methodology and a Python API example.

The dashboard currently does not invoke that signal engine as a market-signal UI. Its **Analysis** tab summarizes a connected portfolio through `wallex_assistant.portfolio.generate_analysis`; with no usable portfolio balances, it shows the empty-state message. If no configured LLM is available, a deterministic portfolio summary is used.

## Portfolio functionality

When authenticated, the app requests account balances and matches assets to public market statistics to estimate total portfolio value and show per-asset quantities, prices, and values in TMN. Locked and available balances are both included. These estimates depend on market data availability and are not an account statement.

## Tests and checks

Run all offline unit tests from the project root:

```powershell
python -m unittest discover -s tests -v
```

Compile the Python modules:

```powershell
python -m compileall -q wallex_assistant streamlit_app.py tests
```

Tests use mocked or local data and do not validate live credentials, current Wallex availability, or live response contracts.

## Security

- Never commit `.env`, API keys, tokens, or credential files. `.gitignore` excludes local environment secrets, Python caches, and common generated files.
- Entered UI keys are held in Streamlit session state and sent to Wallex via an HTTP header. This is session-scoped, not a persistent secrets vault; use trusted hosting and protect access to the app.
- `WALLEX_API_KEY` and optional LLM credentials may be loaded from environment variables for local use. Keep those values private.
- The application is intended to remain read-only. Review permissions and code carefully before any change involving mutating endpoints.

## Known limitations and roadmap

- Live Wallex API behavior and authenticated balance access have not been independently validated as part of this repository's offline tests; network access and a user-owned API key are needed for that verification.
- Historical-data availability and API response changes can limit or invalidate market calculations.
- Dashboard language selection exists, but some status, API-configuration, and error messages are currently English-only.
- The deterministic market signals are not currently surfaced in the dashboard UI. A useful next step is a read-only signal view with freshness and data-quality warnings, followed by additional mocked tests for key entry and API failures.
- Add more offline coverage for configuration, market response variants, and UI/API-key validation as those interfaces evolve.

## Disclaimer

Cryptocurrency markets are volatile. This project is provided for educational and informational purposes only, not as financial, investment, or trading advice. Signals and portfolio estimates can be incomplete, delayed, or wrong and do not guarantee profits or prevent losses. Make independent decisions and consult a qualified professional where appropriate.
