# Scraper

- `engine.py`: orchestration, pools of Instagram accounts and collectors.
- `__init__.py`: small public API consumed by the routes.

The next extractions can happen without changing routes: browser lifecycle,
Instagram collectors and generic collectors are independent sections in
`engine.py` already.
