"""Market-cap tier lookup for the scan-universe size selector.

Backed by a bundled JSON snapshot (market_cap_tiers.json) built offline by
build_market_cap_tiers.py - NOT fetched live, so this is instant and never
blocked by any exchange/API rate-limit at app runtime.
"""
import json
from pathlib import Path
from typing import Dict, List

TIERS_PATH = Path(__file__).parent / "market_cap_tiers.json"

TIER_ORDER = [
    "Large Cap (Top 50)",
    "Large-Mid Cap (51-100)",
    "Mid Cap (101-200)",
    "Small Cap (200+)",
    "Unknown",
]


def load_tiers() -> Dict[str, dict]:
    if not TIERS_PATH.exists():
        return {}
    with open(TIERS_PATH) as f:
        return json.load(f)


def top_n_tickers(tickers: List[str], n: int) -> List[str]:
    """Return the top-N tickers by market cap rank (capital size), from the
    bundled snapshot. If a ticker has no rank info it's placed at the end."""
    tiers = load_tiers()
    if not tiers:
        return tickers[:n]
    ranked = sorted(tickers, key=lambda t: (tiers.get(t, {}).get("rank") is None,
                                             tiers.get(t, {}).get("rank") or 9999))
    return ranked[:n]


def filter_tickers_by_tier(tickers: List[str], selected_tiers: List[str]) -> List[str]:
    tiers = load_tiers()
    if not tiers:
        return tickers
    out = [t for t in tickers if tiers.get(t, {}).get("tier", "Unknown") in selected_tiers]
    out.sort(key=lambda t: (tiers.get(t, {}).get("rank") is None, tiers.get(t, {}).get("rank") or 9999))
    return out


def tier_counts(tickers: List[str]) -> Dict[str, int]:
    tiers = load_tiers()
    counts = {t: 0 for t in TIER_ORDER}
    for t in tickers:
        tier = tiers.get(t, {}).get("tier", "Unknown")
        counts[tier] = counts.get(tier, 0) + 1
    return counts
