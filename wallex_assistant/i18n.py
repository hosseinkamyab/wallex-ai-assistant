"""Minimal internationalisation (i18n) support: English and Persian.

Why this exists in Stage 0 rather than Stage 5:

Wiring translation in from the start is nearly free -- callers write
`t("total_value")` instead of `"Total value"`. Retrofitting it later means
hunting down every hard-coded string across the whole codebase. So the
scaffold goes in now, and grows as features are added.

Two details that make Persian genuinely work, not just "translated":

1. **Right-to-left layout.** Persian is RTL; English is LTR. `text_direction()`
   tells the UI layer which way to lay out.
2. **Numbers must not flip.** In an RTL context, digits and Latin ticker
   symbols (BTC, TMN) can be reordered by the renderer. `format_number()` and
   `format_money()` wrap values in Unicode isolates (U+2066 ... U+2069) so a
   number always reads correctly, whichever direction the page runs.

Translations that are missing fall back to English, then to the key itself,
so a forgotten string is visible but never crashes the app.
"""

from __future__ import annotations

from .config import VALID_LANGUAGES

DEFAULT_LANGUAGE = "en"

# Unicode directional isolates.
# Built with chr() on purpose: these characters are invisible, so a literal
# copy would be impossible to verify by eye and easy to corrupt. The hex code
# says exactly which character is meant.
_LRI = chr(0x2066)  # LEFT-TO-RIGHT ISOLATE
_PDI = chr(0x2069)  # POP DIRECTIONAL ISOLATE

LANGUAGE_NAMES = {
    "en": "English",
    "fa": "فارسی",
}

# --------------------------------------------------------------------------- #
# Translation catalogue
# --------------------------------------------------------------------------- #
# Keys are flat and dot-namespaced so they stay easy to grep.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # --- app / general ---
        "app.title": "Wallex AI Assistant",
        "app.subtitle": "Read-only portfolio insight",
        "app.language": "Language",
        "app.readonly_notice": (
            "This app is read-only. It cannot trade, withdraw, or transfer funds."
        ),
        "app.loading": "Loading…",
        "app.refresh": "Refresh",
        "app.error": "Something went wrong",
        # --- tabs ---
        "tab.overview": "Overview",
        "tab.balances": "Balances",
        "tab.market": "Market",
        "tab.analysis": "AI Analysis",
        # --- portfolio ---
        "portfolio.total_value": "Total value",
        "portfolio.asset": "Asset",
        "portfolio.quantity": "Quantity",
        "portfolio.price": "Price",
        "portfolio.value": "Value",
        "portfolio.allocation": "Allocation",
        "portfolio.empty": "No balances found.",
        # --- market ---
        "market.symbol": "Symbol",
        "market.last_price": "Last price",
        "market.change_24h": "24h change",
        "market.volume": "Volume",
        # --- analysis ---
        "analysis.run": "Analyse my portfolio",
        "analysis.running": "Analysing…",
        "analysis.empty": "No analysis yet. Click the button above to generate one.",
        "analysis.disclaimer": (
            "AI output is for information only and is not financial advice."
        ),
        # --- errors ---
        "error.config": "Configuration problem",
        "error.api": "Could not reach Wallex",
        "error.auth": "Wallex rejected the API key",
        "error.rate_limit": "Too many requests — please wait and try again",
        # --- units ---
        "unit.tmn": "TMN",
    },
    "fa": {
        # --- app / general ---
        "app.title": "دستیار هوشمند والکس",
        "app.subtitle": "تحلیل پرتفوی، فقط-خواندنی",
        "app.language": "زبان",
        "app.readonly_notice": (
            "این برنامه فقط خواندنی است؛ امکان معامله، برداشت یا انتقال وجه ندارد."
        ),
        "app.loading": "در حال بارگذاری…",
        "app.refresh": "به‌روزرسانی",
        "app.error": "خطایی رخ داد",
        # --- tabs ---
        "tab.overview": "نمای کلی",
        "tab.balances": "موجودی‌ها",
        "tab.market": "بازار",
        "tab.analysis": "تحلیل هوش مصنوعی",
        # --- portfolio ---
        "portfolio.total_value": "ارزش کل",
        "portfolio.asset": "دارایی",
        "portfolio.quantity": "مقدار",
        "portfolio.price": "قیمت",
        "portfolio.value": "ارزش",
        "portfolio.allocation": "سهم از پرتفوی",
        "portfolio.empty": "موجودی‌ای یافت نشد.",
        # --- market ---
        "market.symbol": "نماد",
        "market.last_price": "آخرین قیمت",
        "market.change_24h": "تغییر ۲۴ ساعته",
        "market.volume": "حجم",
        # --- analysis ---
        "analysis.run": "تحلیل پرتفوی من",
        "analysis.running": "در حال تحلیل…",
        "analysis.empty": "تحلیلی موجود نیست. برای ساخت، دکمه بالا را بزنید.",
        "analysis.disclaimer": (
            "خروجی هوش مصنوعی فقط جنبه اطلاع‌رسانی دارد و توصیه مالی نیست."
        ),
        # --- errors ---
        "error.config": "مشکل در تنظیمات",
        "error.api": "ارتباط با والکس برقرار نشد",
        "error.auth": "کلید API توسط والکس رد شد",
        "error.rate_limit": "درخواست‌ها بیش از حد مجاز است — کمی بعد تلاش کنید",
        # --- units ---
        "unit.tmn": "تومان",
    },
}


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
def normalize_language(language: str | None) -> str:
    """Return a supported language code, defaulting to English."""
    if language and language.strip().lower() in VALID_LANGUAGES:
        return language.strip().lower()
    return DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, /, **kwargs: object) -> str:
    """Translate `key` into `language`.

    Missing translations fall back: requested language -> English -> the key
    itself. That way a typo shows up as an obvious key in the UI instead of an
    exception or an empty label.

    Extra keyword arguments are substituted with `str.format`, so strings may
    contain `{name}`-style placeholders.

        >>> t("app.language", "fa")
        'زبان'
    """
    lang = normalize_language(language)
    catalogue = TRANSLATIONS.get(lang, {})
    text = catalogue.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # A malformed placeholder should not take the UI down.
            return text
    return text


def is_rtl(language: str) -> bool:
    """True when the language should be laid out right-to-left."""
    return normalize_language(language) == "fa"


def text_direction(language: str) -> str:
    """CSS direction value: 'rtl' for Persian, else 'ltr'."""
    return "rtl" if is_rtl(language) else "ltr"


def isolate(value: object) -> str:
    """Wrap a value in a left-to-right Unicode isolate.

    This keeps numbers and ticker symbols (BTC, TMN, 1,234,567) reading the
    correct way round even inside a right-to-left page. Without it, a Persian
    sentence containing "1,234 TMN" can render with the digits misplaced.
    """
    return f"{_LRI}{value}{_PDI}"


def format_money(amount: float, language: str = DEFAULT_LANGUAGE) -> str:
    """Format a TMN amount with thousands separators, RTL-safe.

        >>> format_money(1234567.5, "en")
        '1,234,567.50'
    """
    try:
        text = f"{float(amount):,.2f}"
    except (TypeError, ValueError):
        text = "—"
    return isolate(text) if is_rtl(language) else text


def format_quantity(amount: float, language: str = DEFAULT_LANGUAGE) -> str:
    """Format an asset quantity, trimming trailing zeros, RTL-safe."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return "—"
    # Show up to 8 significant decimals (crypto assets can be very small),
    # then strip meaningless trailing zeros.
    text = f"{value:,.8f}".rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    return isolate(text) if is_rtl(language) else text


def format_percent(value: float, language: str = DEFAULT_LANGUAGE) -> str:
    """Format a percentage, e.g. 12.3 -> '12.30%', RTL-safe."""
    try:
        text = f"{float(value):,.2f}%"
    except (TypeError, ValueError):
        return "—"
    return isolate(text) if is_rtl(language) else text
