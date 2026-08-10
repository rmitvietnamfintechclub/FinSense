"""Public entry point for closing-price lookups.

FS30 selected VNDirect (finfo API) as the primary provider; swap the import
here if the provider changes (fallback: TCBS, see docs/features/fs30).
"""

from backend.api.external.price.adapters.vndirect import get_closing_price

__all__ = ["get_closing_price"]
