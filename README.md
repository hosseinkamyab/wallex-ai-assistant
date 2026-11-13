# Wallex AI Assistant

This repository is a Python-based, read-only cryptocurrency portfolio assistant for Wallex. It is designed to fetch account balances, market data, and portfolio metrics while preventing any trade, withdrawal, or transfer flow from being introduced into the codebase.

## Current status

The project already contains a reasonably solid foundation for the initial architecture:

- configuration loading and validation via `wallex_assistant/config.py`
- secret-safe environment management using `.env` and masked values
- read-only HTTP transport with retry logic and HTTP status mapping
- guardrails to block unsafe endpoints in `wallex_assistant/readonly.py`
- public market-data and account-data clients
- portfolio aggregation helpers and a deterministic summary layer
- AI analysis module with graceful fallback behavior
- English/Persian UI text support
- offline tests covering config, HTTP, i18n, market, account, and read-only behavior

## Important milestones reached

1. Fixed the portfolio import issue and stabilized the core valuation logic.
2. Added focused tests for portfolio valuation and analysis behavior.
3. Hardened the AI analysis layer so it falls back safely when no model or key is configured.
4. Added a local Streamlit dashboard for the portfolio workflow.

## Major gaps still to address

- The app still needs richer portfolio metrics (allocation, P/L, and risk framing).
- The Streamlit UI should be expanded to show more detailed market and account insights.
- The repository still needs a bit of cleanup around generated cache files and packaging consistency.

## Run locally

Create a local environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then start the dashboard:

```bash
streamlit run streamlit_app.py
```

If you do not configure `WALLEX_API_KEY`, the app will work in public market-data mode only.

## Security note

This project remains read-only by design. It does not place trades, withdraw funds, or transfer assets. Any future features must preserve this restriction.
