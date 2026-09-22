"""Scraping public API.

Routes should depend only on these functions, never on engine internals.
"""

from .engine import _abrir_browser, _fechar_browser, scrape_url

__all__ = ["scrape_url", "_abrir_browser", "_fechar_browser"]
