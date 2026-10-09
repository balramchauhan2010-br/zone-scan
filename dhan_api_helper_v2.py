"""
dhan_api_helper_v2.py - back-compat shim

app.py ke kuch sections `from dhan_api_helper_v2 import ...` karte hain,
lekin asli implementation dhan_api_helper.py me hai. Ye shim us import ko
poora karta hai (pehle ye module exist hi nahi karta tha -> Dhan fast path
chupchap fail ho jata tha aur data slow Yahoo par chalta tha).
"""

from dhan_api_helper import (  # noqa: F401
    load_dhan_master_fast,
    get_dhan_ltp_fast,
    get_dhan_market_watch_fast,
    is_dhan_fast_available,
    get_dhan_client,
)
