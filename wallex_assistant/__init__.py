"""Wallex AI Assistant -- a read-only cryptocurrency portfolio assistant.

This package is deliberately READ-ONLY: it retrieves balances, transactions
and market data, and explains them. It contains no code that can place
orders, withdraw funds, or transfer anything.
"""

__version__ = "0.2.0"
__all__ = [
    "__version__",
    "config",
    "account_client",
    "market_client",
    "errors",
    "http",
    "i18n",
    "readonly",
    "portfolio",
    "llm_client",
    "buy_opportunity",
]

