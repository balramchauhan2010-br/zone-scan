"""
gemini_analyzer.py
Gemini API se Zone + News + Events ka powerful analysis

Install: pip install google-generativeai
API Key: https://aistudio.google.com/app/apikey
"""

import os
from typing import List, Dict, Optional
import pandas as pd
import json

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

class GeminiZoneAnalyzer:
    def __init__(self, api_key: str = None, model: str = "gemini-1.5-flash"):
        """
        api_key: Gemini API key - https://aistudio.google.com/app/apikey
        model: gemini-1.5-flash (fast, cheap) ya gemini-1.5-pro (powerful)
        Streamlit secrets me rakho: st.secrets["GEMINI_API_KEY"]
        """
        if not GEMINI_AVAILABLE:
            raise ImportError("google-generativeai install karo: pip install google-generativeai")
        
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY chahiye. https://aistudio.google.com/app/apikey se lo.")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model)
        self.model_name = model
    
    def analyze_single_zone(self, zone_info: dict, news_df: pd.DataFrame = None, 
                            corp_actions: pd.DataFrame = None, market_breadth: dict = None) -> dict:
        """
        Ek zone ka deep analysis Gemini se
        
        zone_info: {
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "direction": "DEMAND (Buy Zone)",
            "pattern": "RBR",
            "entry": 2800.5,
            "sl": 2780.0,
            "target": 2860.0,
            "distance_pct": -0.8,
            "state": "Fresh",
            "score": 85,
            "isHQ": True,
            "legOutRR": 3.2,
            "pulse": 1,
            "trend": 1,
            "aligned": True
        }
        news_df: NSE announcements / global news
        corp_actions: dividend, bonus, split
        market_breadth: {"up": 120, "down": 93, "total": 213}
        """
        
        # Context banao
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
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            # Try to parse JSON, agar JSON nahi to raw text return
            try:
                # Remove markdown code blocks if present
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                result = json.loads(text)
                return result
            except:
                return {"raw_response": text, "tradable": None, "confidence": 0}
        except Exception as e:
            return {"error": str(e), "tradable": None, "confidence": 0}

    def analyze_batch_zones(self, zones_df: pd.DataFrame, max_zones: int = 10, 
                            news_fetcher=None, corp_fetcher=None, breadth: dict = None) -> pd.DataFrame:
        """
        Top N zones ka batch analysis - cost bachane ke liye sirf nearest zones ka karo
        zones_df: aapke scanner ka combined DataFrame
        """
        if zones_df.empty:
            return pd.DataFrame()
        
        # Sirf nearest 10 zones ka analysis (cost + time bachao)
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
            
            # Fetch news/corp for this symbol if fetcher provided
            news_df = None
            corp_df = None
            if news_fetcher:
                try:
                    news_df = news_fetcher(zone_info["symbol"])
                except:
                    pass
            if corp_fetcher:
                try:
                    corp_df = corp_fetcher(zone_info["symbol"])
                except:
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
            resp = self.model.generate_content(prompt)
            return resp.text
        except Exception as e:
            return f"Error: {e}"

# ---------- Streamlit Integration Example ----------
"""
import streamlit as st
from gemini_analyzer import GeminiZoneAnalyzer
from news_corporate_events import get_nse_announcements, get_nse_corporate_actions

# Secrets
GEMINI_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def get_gemini():
    return GeminiZoneAnalyzer(api_key=GEMINI_KEY, model="gemini-1.5-flash")

gemini = get_gemini()

# Jab user Validated Zones page par ho aur top 10 zones ka analysis chahiye
if st.button("🤖 Gemini se Top 10 Zones ka Analysis Karo"):
    with st.spinner("Gemini analysis chal raha hai..."):
        # Breadth
        breadth = {"up": 54, "down": 157, "flat": 2, "total": 213}
        
        # Batch analysis
        analysis_df = gemini.analyze_batch_zones(
            zones_df=combined_v,  # aapka validated combined DataFrame
            max_zones=10,
            news_fetcher=lambda sym: get_nse_announcements(symbol=sym, days=7),
            corp_fetcher=lambda sym: get_nse_corporate_actions(symbol=sym, days=30),
            breadth=breadth
        )
        
        st.dataframe(analysis_df, width="stretch")
        
        # Har zone ka detail expander
        for idx, row in analysis_df.iterrows():
            with st.expander(f"{row['Symbol']} - {row['Verdict']} (Confidence {row['Confidence']}%)"):
                st.write(row['Reasoning'])
                st.write(f"Risk: {row['Risk']} | Sentiment: {row['Sentiment']}")

# Market overview
if st.button("🌅 Aaj ka Market Overview Gemini se"):
    overview = gemini.market_overview_analysis(breadth, nifty_zone, combined_v)
    st.info(overview)
"""

# ---------- Hindi Translation + News Hypothesis (for Bottom Big Box) ----------
def quick_hindi_translate(text: str, api_key: str = None) -> str:
    """NSE news ko Hindi me translate karo - Gemini secure, fast fallback"""
    try:
        from secure_config import get_gemini_key, is_gemini_configured
        if not is_gemini_configured() and not api_key:
            return text  # fallback English if no Gemini
        key = api_key or get_gemini_key()
        if not key or not GEMINI_AVAILABLE:
            return text
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Translate this NSE market news to Hindi in short headline style (max 25 words), keep symbol names in English:\n\n{text}\n\nHindi:"
        resp = model.generate_content(prompt)
        hindi = resp.text.strip()[:300]
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
        if not key or not GEMINI_AVAILABLE:
            return {"bias": "Neutral", "reason_hindi": "Gemini library nahi hai", "impact": "Medium"}
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
You are NSE expert. Symbol: {symbol}, News: {news_text}

Task: Give trading hypothesis in Hindi (2 lines max).
Format JSON: {{"bias": "Bullish/Bearish/Neutral", "reason_hindi": "Hindi me reason 20 words", "impact": "High/Medium/Low"}}

Example: {{"bias": "Bullish 📈", "reason_hindi": "अच्छे नतीजों से खरीदारी बढ़ेगी, सपोर्ट जोन मजबूत", "impact": "High"}}

JSON only:
"""
        resp = model.generate_content(prompt)
        txt = resp.text.strip()
        # Clean markdown
        if "```json" in txt:
            txt = txt.split("```json")[1].split("```")[0].strip()
        elif "```" in txt:
            txt = txt.split("```")[1].split("```")[0].strip()
        try:
            data = json.loads(txt)
            return data
        except:
            # Fallback parse
            return {"bias": "Neutral", "reason_hindi": txt[:200], "impact": "Medium"}
    except Exception as e:
        return {"bias": "Neutral", "reason_hindi": f"Error: {e}", "impact": "Low"}

# ---------- Cost Saving Tips ----------
"""
1. gemini-1.5-flash use karo (pro se 10x sasta, fast)
2. Sirf Top 10 nearest zones ka analysis karo, 500 zones ka nahi
3. Cache karo: @st.cache_data(ttl=3600) se Gemini response ko 1 ghante tak cache
4. Batch me 1 hi prompt me 5 zones bhejo, alag-alag nahi (prompt me list de do)
5. Streamlit secrets me API key rakho, GitHub par push mat karo
"""
