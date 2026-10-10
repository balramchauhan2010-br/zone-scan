"""
indicators_hypothesis.py — Technical indicators + rule-based Hinglish hypothesis.
=================================================================================
app.py ye module OPTIONAL import karta hai:

    from indicators_hypothesis import (calculate_indicators,
                                        generate_hypothesis_rule_based,
                                        get_hypothesis_short_link)

Pehle ye file repo me thi hi nahi, isliye `INDICATOR_AVAILABLE = False` ho jata
tha aur Detailed Zone Analysis hamesha stub fallback par chalta tha. Ab ye file
aa gayi hai to:

- calculate_indicators(df)        -> RSI, EMA20/50/200, Supertrend, MACD, Vol ratio
- generate_hypothesis_rule_based  -> Zone + Indicators + Sector + FII + Global
                                     + Event risk se 2-3 line Hinglish hypothesis
- get_hypothesis_short_link       -> TradingView chart link (zone ke TF ke saath)

Sab kuch pandas/numpy based, bina kisi external API ke — fast aur free.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ indicators

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _supertrend_dir(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """Classic Supertrend direction series: +1 bullish, -1 bearish."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    atr = (pd.concat([high - low,
                      (high - close.shift()).abs(),
                      (low - close.shift()).abs()], axis=1).max(axis=1)
           .ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean())
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    direction = pd.Series(1, index=df.index, dtype=int)
    final_upper = upper.copy()
    final_lower = lower.copy()
    for i in range(1, len(df)):
        if close.iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1:
                final_lower.iloc[i] = max(lower.iloc[i], final_lower.iloc[i - 1])
            else:
                final_upper.iloc[i] = min(upper.iloc[i], final_upper.iloc[i - 1])
        if direction.iloc[i] == 1:
            final_upper.iloc[i] = upper.iloc[i] if np.isnan(final_upper.iloc[i - 1]) else final_upper.iloc[i]
        else:
            final_lower.iloc[i] = lower.iloc[i] if np.isnan(final_lower.iloc[i - 1]) else final_lower.iloc[i]
    return direction


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd - sig


def calculate_indicators(df: Optional[pd.DataFrame]) -> dict:
    """Daily OHLCV frame (lowercase open/high/low/close/volume) -> indicator dict.
    app.py isi exact key-set ki proti hai."""
    out = {
        "rsi": 50.0, "above_ema20": True, "above_ema50": True, "above_ema200": True,
        "supertrend_dir": 0, "macd_hist": 0.0, "vol_ratio": 1.0, "price": 0.0,
    }
    if df is None or len(df) < 30:
        return out
    try:
        close = df["close"].astype(float)
        out["price"] = float(close.iloc[-1])
        out["rsi"] = round(float(_rsi(close).iloc[-1]), 1)

        last = float(close.iloc[-1])
        e20 = float(_ema(close, 20).iloc[-1])
        e50 = float(_ema(close, 50).iloc[-1])
        e200 = float(_ema(close, 200).iloc[-1]) if len(close) >= 200 else e50
        out["above_ema20"] = bool(last > e20)
        out["above_ema50"] = bool(last > e50)
        out["above_ema200"] = bool(last > e200)

        out["supertrend_dir"] = int(_supertrend_dir(df).iloc[-1])
        out["macd_hist"] = round(float(_macd_hist(close).iloc[-1]), 4)

        if "volume" in df.columns:
            vol = df["volume"].astype(float)
            if len(vol) >= 21 and float(vol.rolling(20).mean().iloc[-1]) > 0:
                out["vol_ratio"] = round(float(vol.iloc[-1] / vol.rolling(20).mean().iloc[-1]), 2)
    except Exception as e:
        print(f"calculate_indicators error (safe): {e}")
    return out


# ------------------------------------------------------------------ hypothesis

def generate_hypothesis_rule_based(sym: str, zone_info: dict, ind: dict, sec: str,
                                   fii_ctx: str, glob_ctx: str, risky: bool = False) -> str:
    """Zone + indicators + sector + FII + global + event risk se Hinglish hypothesis."""
    try:
        sym = str(sym).replace(".NS", "")
        direction = str(zone_info.get("Direction", ""))
        is_buy = "DEMAND" in direction
        tf = zone_info.get("Timeframe", "")
        entry = zone_info.get("Entry (Proximal)", "—")
        dist = zone_info.get("Distance %", 0)
        state = zone_info.get("State", "")

        # ---- indicator narrative ----
        rsi = ind.get("rsi", 50)
        rsi_txt = (f"RSI {rsi:.0f} (overbought)" if rsi >= 70 else
                   f"RSI {rsi:.0f} (oversold)" if rsi <= 30 else
                   f"RSI {rsi:.0f} (neutral)")
        ema_txt = []
        if ind.get("above_ema20"):
            ema_txt.append("EMA20 ke upar")
        if ind.get("above_ema50"):
            ema_txt.append("EMA50 ke upar")
        st_txt = ("Supertrend bullish" if ind.get("supertrend_dir") == 1 else
                  "Supertrend bearish" if ind.get("supertrend_dir") == -1 else "Supertrend neutral")
        macd = ind.get("macd_hist", 0)
        macd_txt = "MACD histogram positive" if macd > 0 else "MACD histogram negative"
        vol = ind.get("vol_ratio", 1)
        vol_txt = f"Volume {vol:.1f}× average" + (" — bada participation" if vol >= 1.5 else "")

        # ---- verdict logic ----
        score = 0
        if is_buy:
            if ind.get("above_ema20"):
                score += 1
            if ind.get("above_ema50"):
                score += 1
            if ind.get("supertrend_dir") == 1:
                score += 1
            if 30 < rsi < 65:
                score += 1
            if macd > 0:
                score += 1
            if vol >= 1.2:
                score += 1
            if state == "Fresh":
                score += 1
            verdict = "Watchlist — zone test par buy karein, SL zone ke neeche" if score >= 4 else \
                      "Neutral — indicators mixed, pehle confirmation ka intezaar"
        else:
            if not ind.get("above_ema20"):
                score += 1
            if not ind.get("above_ema50"):
                score += 1
            if ind.get("supertrend_dir") == -1:
                score += 1
            if 35 < rsi < 70:
                score += 1
            if macd < 0:
                score += 1
            if vol >= 1.2:
                score += 1
            if state == "Fresh":
                score += 1
            verdict = "Watchlist — zone test par sell/short karein, SL zone ke upar" if score >= 4 else \
                      "Neutral — indicators mixed, pehle confirmation ka intezaar"

        parts = [
            f"{sym} {tf} {'DEMAND (buy)' if is_buy else 'SUPPLY (sell)'} zone @ {entry} — price {abs(float(dist or 0)):.2f}% "
            f"{'neeche' if (is_buy and float(dist or 0) > 0) or ((not is_buy) and float(dist or 0) < 0) else 'upar'} hai, {state} zone.",
            f"Indicators: {rsi_txt}, price {' '.join(ema_txt) if ema_txt else 'EMA ke neeche'}, {st_txt}, {macd_txt}, {vol_txt}.",
            f"Context: Sector {sec} | {fii_ctx or 'FII data N/A'} | {glob_ctx or 'Global mixed'}.",
        ]
        if risky:
            parts.append("⚠️ Near-term event risk (result/board/corp action) — entry se pehle event date check karein.")
        parts.append(f"Verdict: {verdict}.")
        return " ".join(parts)
    except Exception as e:
        return f"{sym} hypothesis generate nahi ho paya ({e}) — zone details upar table me hain."


def get_hypothesis_short_link(sym: str, tf: str = None, hyp: str = "") -> str:
    """Zone ke exact timeframe ke saath TradingView chart link."""
    try:
        from fno_universe import chart_url
        return chart_url(str(sym), tf=tf)
    except Exception:
        clean = str(sym).replace(".NS", "").replace("&", "_").replace("-", "_")
        return f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean}"


if __name__ == "__main__":
    # Chhota sa self-test: synthetic daily frame par indicators + hypothesis.
    idx = pd.date_range("2026-01-01", periods=120, freq="B")
    close = pd.Series(100 + np.cumsum(np.random.default_rng(1).normal(0.2, 1.0, 120)), index=idx)
    df = pd.DataFrame({
        "open": close.shift(1).fillna(100), "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.random.default_rng(2).integers(1_000_000, 3_000_000, 120),
    }, index=idx)
    ind = calculate_indicators(df)
    print("indicators:", ind)
    hyp = generate_hypothesis_rule_based(
        "RELIANCE.NS",
        {"Direction": "DEMAND (Buy Zone)", "Timeframe": "Daily", "Entry (Proximal)": 2900,
         "Distance %": -1.2, "State": "Fresh"},
        ind, "Oil & Gas", "FII Buying Net +1200Cr", "US markets bullish", False)
    print("hypothesis:", hyp)
    print("link:", get_hypothesis_short_link("RELIANCE.NS", "Daily"))
    assert 0 <= ind["rsi"] <= 100
    assert ind["supertrend_dir"] in (-1, 0, 1)
    print("SELF TEST PASSED")
