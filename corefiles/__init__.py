# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - __init__.py
#  Core files package initialization
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

from . import config
from . import error_handler

# Import other modules only when needed to avoid dependency issues
# from . import based
# from . import integrity
# from . import passion  
# from . import purge

__all__ = ['config', 'error_handler'] 