"""
gemini_analyzer.py - Gemini REST client (2026-ready, SDK-free)

KYU BADLA: purana code `gemini-1.5-flash` model + `google-generativeai` SDK
use karta tha. Google ne Gemini 1.5 models Sept-2025 me shut down kar diye
aur wo SDK bhi deprecated hai - isliye AI features kaam hi nahi kar rahe the.

AB: koi SDK dependency nahi - seedha Gemini REST API (requests pehle se
dependency hai). Default model: **gemini-3.5-flash** (stable).

Model badalna ho to (.streamlit/secrets.toml me, gitignored):
    [gemini]
    api_key = "AIza..."
    model   = "gemini-3.8-flash"     # ya env var GEMINI_MODEL

PUBLIC API same rakhi gayi hai (app.py ke purane calls bina badle chalenge):
- GeminiZoneAnalyzer(api_key=..., model=...)  -> .model.generate_content(prompt).text
- .analyze_single_zone(), .analyze_batch_zones(), .market_overview_analysis()
- get_gemini(), quick_hindi_translate(), get_gemini_hypothesis_for_news()
"""

import json
import os
from typing import Optional

import pandas as pd
import requests

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash"   # stable; purana gemini-1.5-flash band ho chuka hai
REQUEST_TIMEOUT = 30


def get_model_name() -> str:
    """secrets [gemini].model -> env GEMINI_MODEL -> DEFAULT_MODEL"""
    try:
        import streamlit as st
        val = st.secrets["gemini"]["model"]
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    val = os.getenv("GEMINI_MODEL")
    if val and val.strip():
        return val.strip()
    return DEFAULT_MODEL


def _post_generate(api_key: str, model: str, prompt: str) -> str:
    """REST call -> generated text (fail par informative exception)."""
    url = f"{API_BASE}/{model}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(
        url,
        params={"key": api_key},
        json=payload,
        timeout=REQUEST_TIMEOUT,
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini API unexpected response: {str(data)[:200]}")


class _RestResponse:
    """Purane SDK jaisa object - sirf .text attribute chahiye."""
    def __init__(self, text: str):
        self.text = text


class _RestModel:
    """Backward-compat: app.py kahin-kahin `gemini_client.model.generate_content(prompt).text`
    directly call karta hai - ye wrapper wahi interface deta hai."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model_name = model

    def generate_content(self, prompt: str) -> _RestResponse:
        return _RestResponse(_post_generate(self.api_key, self.model_name, prompt))


def _extract_json(text: str):
    """Markdown code-block hata kar JSON parse karo (nahi to raw dict)."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


class GeminiZoneAnalyzer:
    def __init__(self, api_key: str = None, model: str = None):
        """
        api_key: Gemini API key - https://aistudio.google.com/app/apikey
        model: default gemini-3.5-flash (fast, sasta). Pro chahiye to secrets me
               `model = "gemini-3-pro"` set karo ya yahan pass karo.
        """
        try:
            from secure_config import get_gemini_key  # secure: secrets/env only
            self.api_key = api_key or get_gemini_key()
        except Exception:
            self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY chahiye. https://aistudio.google.com/app/apikey se lo.")
        self.model_name = model or get_model_name()
        # IMPORTANT: attribute ka naam `.model` hi rakha hai taaki app.py ke
        # purane `gemini_client.model.generate_content(...)` calls na tootein.
        self.model = _RestModel(self.api_key, self.model_name)

    def analyze_single_zone(self, zone_info: dict, news_df: pd.DataFrame = None,
                            corp_actions: pd.DataFrame = None, market_breadth: dict = None) -> dict:
        """
        Ek zone ka deep analysis Gemini se

        zone_info: {"symbol","timeframe","direction","pattern","entry","sl",
                    "target","distance_pct","state","score","isHQ","legOutRR",
                    "pulse","trend","aligned"}
        """
        news_text = ""
        if news_df is not None and not news_df.empty:
            news_text = "\n".join([f"- {row.get('desc') or row.get('title')} ({row.get('date') or row.get('published')})"
                                   for _, row in news_df.head(5).iterrows()])
        else:
            news_text = "No recent news"

        corp_text = ""
        if corp_actions is not None and not corp_actions.empty:
            corp_text = "\n".join([f"- {row.get('purpose')} ex: {row.get('ex_date')}"
                                   for _, row in corp_actions.head(3).iterrows()])
        else:
            corp_text = "No corporate actions in next 30 days"

        breadth_text = ""
        if market_breadth:
            breadth_text = f"NSE F&O Breadth: Up {market_breadth.get('up')} Down {market_breadth.get('down')} Total {market_breadth.get('total')}"

        prompt = f"""
You are an expert NSE F&O Supply/Demand Zone trader and analyst. Analyze this zone with news, events, corporate actions.

ZONE DETAILS:
- Symbol: {zone_info.get('symbol')} | Timeframe: {zone_info.get('timeframe')} | Direction: {zone_info.get('direction')}
- Pattern: {zone_info.get('pattern')} | State: {zone_info.get('state')} | HQ: {zone_info.get('isHQ')} | Score: {zone_info.get('score')}
- Entry (Proximal): {zone_info.get('entry')} | SL: {zone_info.get('sl')} | Target: {zone_info.get('target')}
- Distance from Entry: {zone_info.get('distance_pct')}% | LegOut RR: {zone_info.get('legOutRR')} | Pulse: {zone_info.get('pulse')} Trend: {zone_info.get('trend')} Aligned: {zone_info.get('aligned')}

MARKET CONTEXT:
{breadth_text}

RECENT NEWS / ANNOUNCEMENTS:
{news_text}

CORPORATE ACTIONS (Dividend/Bonus/Split):
{corp_text}

TASK:
1. Is this zone tradable? Consider: Fresh? HQ? RR>=3? Pulse/Trend aligned? Distance% near?
2. News/events se koi risk hai kya? (Result, dividend, bonus ke aas paas zone risky hota hai)
3. Corporate action se price manipulation ka risk?
4. Market breadth se trend kya kehta hai?
5. Final Verdict: BUY/SELL/AVOID with confidence % and reasoning in Hindi + English mix (Hinglish), 3-4 lines.

Respond in JSON format:
{{
  "tradable": true/false,
  "confidence": 85,
  "risk": "Low/Medium/High",
  "sentiment": "Bullish/Bearish/Neutral",
  "reasoning_hinglish": "2-3 line me Hinglish me reason",
  "verdict": "BUY at proximal / WAIT for retest / AVOID due to event",
  "stop_loss_tip": "SL kaise manage kare",
  "news_impact": "News ka zone par kya impact"
}}
"""
        try:
            text = _post_generate(self.api_key, self.model_name, prompt).strip()
            try:
                return _extract_json(text)
            except Exception:
                return {"raw_response": text, "tradable": None, "confidence": 0}
        except Exception as e:
            return {"error": str(e), "tradable": None, "confidence": 0}

    def analyze_batch_zones(self, zones_df: pd.DataFrame, max_zones: int = 10,
                            news_fetcher=None, corp_fetcher=None, breadth: dict = None) -> pd.DataFrame:
        """
        Top N zones ka batch analysis - cost bachane ke liye sirf nearest zones ka karo
        zones_df: scanner ka combined DataFrame
        """
        if zones_df.empty:
            return pd.DataFrame()

        top_zones = zones_df.sort_values("Distance %", key=lambda s: s.abs()).head(max_zones)

        results = []
        for idx, row in top_zones.iterrows():
            zone_info = {
                "symbol": row.get("Ticker") or row.get("Symbol"),
                "timeframe": row.get("Timeframe"),
                "direction": row.get("Direction"),
                "pattern": row.get("Pattern"),
                "entry": row.get("Entry (Proximal)"),
                "sl": row.get("Stop Loss (Distal+Buffer)"),
                "target": row.get("Target (RR set)"),
                "distance_pct": row.get("Distance %"),
                "state": row.get("State"),
                "score": row.get("Score") or row.get("densityScore"),
                "isHQ": row.get("HQ Zone") or row.get("HQ Zone (Rule3 Boring-Colour)"),
                "legOutRR": row.get("LegOut RR"),
                "pulse": row.get("Pulse"),
                "trend": row.get("Trend"),
                "aligned": row.get("Aligned?"),
            }

            news_df = None
            corp_df = None
            if news_fetcher:
                try:
                    news_df = news_fetcher(zone_info["symbol"])
                except Exception:
                    pass
            if corp_fetcher:
                try:
                    corp_df = corp_fetcher(zone_info["symbol"])
                except Exception:
                    pass

            analysis = self.analyze_single_zone(zone_info, news_df, corp_df, breadth)

            results.append({
                "Symbol": zone_info["symbol"],
                "Timeframe": zone_info["timeframe"],
                "Direction": zone_info["direction"],
                "Entry": zone_info["entry"],
                "Distance %": zone_info["distance_pct"],
                "Tradable": analysis.get("tradable"),
                "Confidence": analysis.get("confidence"),
                "Risk": analysis.get("risk"),
                "Sentiment": analysis.get("sentiment"),
                "Verdict": analysis.get("verdict"),
                "Reasoning": analysis.get("reasoning_hinglish") or analysis.get("raw_response", "")[:200],
            })

        return pd.DataFrame(results)

    def market_overview_analysis(self, breadth: dict, nifty_zone: dict, top_zones: pd.DataFrame) -> str:
        """Poore market ka overview Gemini se - daily morning ke liye"""
        prompt = f"""
        You are NSE market expert. Give morning market overview in Hinglish.

        Market Breadth: NSE F&O 213 stocks me Up: {breadth.get('up')} Down: {breadth.get('down')} Flat: {breadth.get('flat')}
        Nifty Nearest Zone: {nifty_zone}
        Top 5 Nearest Zones:
        {top_zones.head(5).to_string() if not top_zones.empty else "No zones"}

        Task: 4-5 lines me Hinglish me batao:
        - Aaj market ka mood kya hai? (Breadth se)
        - Nifty ka nearest zone kya kehta hai?
        - Kaunse stocks me best opportunity hai?
        - Risk kya hai?

        Hinglish me, short and powerful.
        """
        try:
            return _post_generate(self.api_key, self.model_name, prompt)
        except Exception as e:
            return f"Error: {e}"


# ---------- Streamlit Integration ----------
def get_gemini():
    """Cached analyzer (key na ho to None - app fast chalega, crash nahi)."""
    try:
        import streamlit as st

        @st.cache_resource(show_spinner=False)
        def _build():
            try:
                return GeminiZoneAnalyzer()
            except Exception:
                return None
        return _build()
    except Exception:
        return None


# ---------- Hindi Translation + News Hypothesis (for Bottom Big Box) ----------
def quick_hindi_translate(text: str, api_key: str = None) -> str:
    """NSE news ko Hindi me translate karo - Gemini secure, fast fallback"""
    try:
        from secure_config import get_gemini_key, is_gemini_configured
        if not is_gemini_configured() and not api_key:
            return text  # fallback English if no Gemini
        key = api_key or get_gemini_key()
        if not key:
            return text
        prompt = (f"Translate this NSE market news to Hindi in short headline style "
                  f"(max 25 words), keep symbol names in English:\n\n{text}\n\nHindi:")
        hindi = _post_generate(key, get_model_name(), prompt).strip()[:300]
        return hindi
    except Exception:
        return text  # fallback


def get_gemini_hypothesis_for_news(symbol: str, news_text: str, api_key: str = None) -> dict:
    """Har news ka AI hypothesis Hindi me - Bullish/Bearish/Neutral + Reason"""
    try:
        from secure_config import get_gemini_key, is_gemini_configured
        if not is_gemini_configured() and not api_key:
            return {"bias": "Neutral", "reason_hindi": "Gemini connect nahi hai - rule based analysis", "impact": "Medium"}
        key = api_key or get_gemini_key()
        if not key:
            return {"bias": "Neutral", "reason_hindi": "Gemini key nahi hai", "impact": "Medium"}
        prompt = f"""
You are NSE expert. Symbol: {symbol}, News: {news_text}

Task: Give trading hypothesis in Hindi (2 lines max).
Format JSON: {{"bias": "Bullish/Bearish/Neutral", "reason_hindi": "Hindi me reason 20 words", "impact": "High/Medium/Low"}}

Example: {{"bias": "Bullish 📈", "reason_hindi": "अच्छे नतीजों से खरीदारी बढ़ेगी, सपोर्ट जोन मजबूत", "impact": "High"}}

JSON only:
"""
        txt = _post_generate(key, get_model_name(), prompt).strip()
        try:
            return _extract_json(txt)
        except Exception:
            return {"bias": "Neutral", "reason_hindi": txt[:200], "impact": "Medium"}
    except Exception as e:
        return {"bias": "Neutral", "reason_hindi": f"Error: {e}", "impact": "Low"}

# ---------- Cost Saving Tips ----------
"""
1. gemini-3.5-flash use karo (pro se sasta, fast) - secrets me model badal sakte ho
2. Sirf Top 10 nearest zones ka analysis karo, 500 zones ka nahi
3. Cache karo: @st.cache_data(ttl=3600) se Gemini response ko 1 ghante tak cache
4. Batch me 1 hi prompt me 5 zones bhejo, alag-alag nahi (prompt me list de do)
5. Streamlit secrets me API key rakho, GitHub par push mat karo
"""
