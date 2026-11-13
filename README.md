# Wallex AI Assistant

This repository is a Python-based, read-only cryptocurrency portfolio assistant for Wallex. It is designed to fetch account balances, market data, and portfolio metrics while preventing any trade, withdrawal, or transfer flow from being introduced into the codebase.

## Current status

The project already contains a fairly solid foundation for the initial architecture:

- Configuration loading and validation via `wallex_assistant/config.py`
- Secret-safe environment management using `.env` and masked values
- Read-only HTTP transport with retry logic and HTTP status mapping in `wallex_assistant/http.py`
- Security guardrails to block unsafe endpoints in `wallex_assistant/readonly.py`
- Wallex market data client for public quote data in `wallex_assistant/market_client.py`
- Wallex account client for balances/open orders/fills in `wallex_assistant/account_client.py`
- Portfolio aggregation helpers in `wallex_assistant/portfolio.py`
- AI analysis abstraction in `wallex_assistant/llm_client.py`
- English/Persian UI text support in `wallex_assistant/i18n.py`
- Offline unit tests covering config, HTTP, i18n, market, account, and read-only guard behavior

## What is already working

- Read-only access model is enforced in code and tested.
- Market data parsing is designed to be resilient to minor API shape differences.
- HTTP behavior includes retries, timeouts, and typed exceptions.
- Config supports `.env` values and masks secrets in logs.
- The codebase is intentionally modular and organized around domain concerns.

## Major issues and gaps

The repository is not complete yet. The most important blockers are:

1. Portfolio import failure
   - `wallex_assistant/portfolio.py` imported `get_balances` from `account_client.py`, but that symbol was not defined there.
   - This blocked imports and prevented the portfolio layer from being reliably used.

2. LLM integration is not fully wired correctly
   - `llm_client.py` still needs cleaner provider/model handling and more robust prompt-building.

3. Missing app/UI layer
   - There is no Streamlit app or dashboard entry point yet.

4. Missing portfolio analytics depth
   - The code has pricing and total value logic, but not yet a richer allocation, risk, or insight layer.

5. Cleanup and repo hygiene
   - The repository contains generated `__pycache__` files and the `requirements.txt` file should be normalized before relying on it fully.

## Status after step 1

The portfolio import blocker has been fixed and a focused set of tests was added to exercise the valuation and analysis flow.

## Recommended roadmap

### Phase 1: Stabilize the foundation
- Fix portfolio imports and the immediate runtime breakage.
- Ensure the AI analysis path can run in deterministic/mock mode without crashing.
- Add focused tests for the broken code paths.

### Phase 2: Connect the product experience
- Add a Streamlit dashboard that displays balances, market prices, portfolio valuation, and AI analysis.
- Add a clean user flow for refresh and language selection.

### Phase 3: Expand analysis capabilities
- Add allocation breakdowns.
- Add profit/loss and basic performance metrics when appropriate.
- Keep AI as an interpretation layer rather than a source of financial truth.

### Phase 4: Production polish
- Improve error messaging and recovery.
- Add project documentation and examples.
- Validate the full app with sample data and safe mock scenarios.

## Next step

The immediate next step is to correct the AI analysis path and provider handling, then move to the UI layer and richer portfolio metrics.

This README is intentionally a living document. It should be updated after each milestone to reflect what was implemented, what remains, and the next actionable step.

## Repo structure

- `wallex_assistant/` — core package
- `tests/` — unit tests
- `.env.example` — environment variable template
- `requirements.txt` — Python dependencies
- `test_request.json` — sample LLM request payload

## Security note

This project remains read-only by design. It does not place trades, withdraw funds, or transfer assets. Any future features must preserve this restriction.
