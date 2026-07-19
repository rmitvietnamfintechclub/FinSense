"""
scraper/config.py

Cấu hình dùng chung cho các adapter trong scraper/adapters/ — tránh
lặp lại TIMEOUT/HEADERS ở từng file adapter riêng lẻ.
"""

TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}