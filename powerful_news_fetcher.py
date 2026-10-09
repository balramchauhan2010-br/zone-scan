"""
powerful_news_fetcher.py - F&O-FOCUSED fresh market news

NAYA (user requirement):
1. **Sirf NSE F&O relevant news** - koi bhi news jo scan universe (F&O stocks +
   NIFTY/BANKNIFTY indices) ko affect karti ho. Random crypto/viral/general
   news filter ho jati hai.
2. **Freshness window configurable** - pehle hard 1-hour thi jisse box zyadatar
   khaali rehta tha; ab UI se 1h/3h/6h/12h/24h choose kar sakte ho
   (default 1h - purana behaviour preserve).
3. Symbol detection ab real F&O universe (~220 symbols) ke against hota hai,
   pehle wali chhoti hardcoded list ki jagah.
"""

import re
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------- F&O Universe (news relevance ka base) ----------

@st.cache_data(show_spinner=False, ttl=24 * 3600)
def get_fno_symbol_set() -> frozenset:
    """NSE F&O universe + indices - news filtering ke liye (bundled fallback,
    live NSE fetch nahi karte taaki news path fast rahe)."""
    symbols = set()
    try:
        from fno_universe import get_fno_symbols
        syms, _ = get_fno_symbols(try_live=False)
        symbols |= {str(s).upper() for s in syms}
    except Exception:
        pass
    if not symbols:
        try:
            import json
            with open("fno_stocks_fallback.json") as f:
                symbols |= {str(s).upper() for s in json.load(f)}
        except Exception:
            pass
    # Indices + macro entities jo F&O universe ko move karte hain
    symbols |= {
        "NIFTY", "NIFTY 50", "BANKNIFTY", "BANK NIFTY", "FINNIFTY", "FIN NIFTY",
        "MIDCPNIFTY", "NIFTY NEXT 50", "SENSEX", "GIFT NIFTY",
        "RBI", "FED", "SEBI", "MPC", "US FED", "FOMC",
    }
    return frozenset(symbols)


# Macro/global topics jo F&O stocks ko directly affect karte hain
_MACRO_KEYWORDS = [
    "fii", "dii", "rbi", "repo rate", "interest rate", "rate cut", "rate hike",
    "lending rate", "policy rate", "rate decision", "borrowing cost", "bank rate",
    "monetary policy", "cpi", "inflation", "wpi", "iip", "gdp", "pmi",
    "federal reserve", "fed ", "fed's", "fomc", "us fed", "ecb", "boj",
    "crude", "oil price", "opec", "gold price", "bullion",
    "rupee", "dollar index", "dxy", "usd/inr", "usdinr",
    "bond yield", "us 10-year", "treasury", "gift nifty", "sgx nifty",
    "budget", "gst", "tax ", "tariff", "trade war", "sanctions",
    "monsoon", "election", "government policy", "stimulus",
    "market crash", "bull run", "bear market", "circuit",
    "f&o", "fno", "derivatives", "expiry", "margin",
    "nifty", "sensex", "banknifty", "stock market", "equity market",
]

# News me company ke display-name aate hain, NSE trading-symbol nahi:
# "Bajaj Finance" -> BAJFINANCE, "HDFC Bank" -> HDFCBANK, "Infosys" -> INFY ...
_DISPLAY_ALIASES = {
    "HDFC BANK": "HDFCBANK", "BAJAJ FINANCE": "BAJFINANCE", "BAJAJ FINSERV": "BAJAJFINSV",
    "KOTAK MAHINDRA": "KOTAKBANK", "MAHINDRA & MAHINDRA": "M&M", "BHARTI AIRTEL": "BHARTIARTL",
    "HINDUSTAN UNILEVER": "HINDUNILVR", "INFOSYS": "INFY", "MARUTI SUZUKI": "MARUTI",
    "STATE BANK": "SBIN", "LARSEN & TOUBRO": "LT", "TATA CONSULTANCY": "TCS",
    "ADANI ENTERPRISE": "ADANIENT", "ADANI PORT": "ADANIPORTS", "ADANI POWER": "ADAANIPOWER",
    "TATA POWER": "TATAPOWER", "JSW STEEL": "JSWSTEEL", "COAL INDIA": "COALINDIA",
    "TECH MAHINDRA": "TECHM", "HCL TECHNOLOGIES": "HCLTECH", "DR REDDY": "DRREDDY",
    "DIVIS LABORATORIES": "DIVISLAB", "EICHER MOTORS": "EICHERMOT", "HERO MOTOCORP": "HEROMOTOCO",
    "BAJAJ AUTO": "BAJAJ-AUTO", "INDUSIND BANK": "INDUSINDBK", "TITAN COMPANY": "TITAN",
    "ULTRATECH CEMENT": "ULTRACEMCO", "HINDALCO INDUSTRIES": "HINDALCO", "POWER GRID": "POWERGRID",
    "APOLLO HOSPITALS": "APOLLOHOSP", "BHARAT PETROLEUM": "BPCL", "OIL AND NATURAL GAS": "ONGC",
    "NESTLE INDIA": "NESTLEIND", "SHRIRAM FINANCE": "SHRIRAMFIN", "JIO FINANCIAL": "JIOFIN",
}

_regex_cache = None


def _symbol_regex():
    """Ek compiled regex - poore F&O universe ka word-boundary match."""
    global _regex_cache
    if _regex_cache is None:
        syms = sorted(get_fno_symbol_set(), key=len, reverse=True)
        parts = []
        for s in syms:
            esc = re.escape(s)
            # word-boundary jaise: aage/peeche sirf non-alphanumeric (M&M, M_M bhi chale)
            parts.append(r"(?<![A-Z0-9])" + esc + r"(?![A-Z0-9])")
        _regex_cache = re.compile("|".join(parts))
    return _regex_cache


def extract_symbol_from_text(text: str) -> str:
    """News text me kaunsa F&O symbol hai? Real universe ke against match.
    Step 1: direct word-match (RELIANCE, M&M, TCS...)
    Step 2: display-name match - "HDFC Bank" -> HDFCBANK, "Bajaj Finance" -> BAJFINANCE
    """
    try:
        if not text:
            return "MARKET"
        up = re.sub(r"\s+", " ", str(text).upper())
        m = _symbol_regex().search(up)
        if m:
            return m.group(0).strip()
        # Display aliases: "Bajaj Finance" -> BAJFINANCE, "HDFC Bank" -> HDFCBANK
        for alias, sym in _DISPLAY_ALIASES.items():
            if alias in up:
                return sym
        # Display names me space hota hai - spaces hatakar universe se milao
        fno = get_fno_symbol_set()
        words = re.findall(r"[A-Z&]{2,}", up)
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                joined = "".join(words[i:i + n])
                if joined in fno:
                    return joined
        return "MARKET"
    except Exception:
        return "MARKET"


def is_fresh(pub_date_str: str, hours: int = 1) -> bool:
    """Configurable freshness window (default 1 hour - purana behaviour)."""
    try:
        if not pub_date_str:
            return False
        pub_dt = parsedate_to_datetime(pub_date_str)
        if pub_dt is None:
            return False
        pub_dt_naive = pub_dt.replace(tzinfo=None)
        cutoff = datetime.now() - timedelta(hours=max(1, int(hours)))
        return pub_dt_naive >= cutoff
    except Exception:
        return False


# Backward-compatible naam (purana code kahin use kare to)
def is_fresh_1hour(pub_date_str: str) -> bool:
    return is_fresh(pub_date_str, hours=1)


def is_macro_relevant(title: str, desc: str) -> bool:
    """Kya ye news F&O market/macro level par move karti hai?"""
    try:
        text = (str(title) + " " + str(desc)).lower()
        return any(k in text for k in _MACRO_KEYWORDS)
    except Exception:
        return False


def is_relevant_to_fno(title: str, desc: str) -> bool:
    """USER RULE: news sirf tab dikhe jab wo (a) kisi F&O stock/index ki ho,
    ya (b) macro/global event ho jo NSE F&O stocks ko affect karta hai."""
    if extract_symbol_from_text(str(title) + " " + str(desc)) != "MARKET":
        return True
    return is_macro_relevant(title, desc)


def is_trending_financial_news(title: str, desc: str) -> bool:
    """Stocks/financial market news hai? (pehle jaisa hi + macro check)"""
    try:
        text = (str(title) + " " + str(desc)).lower()
        trending_keywords = [
            "nifty", "sensex", "banknifty", "stock", "share", "market", "bse", "nse",
            "result", "earnings", "profit", "loss", "dividend", "bonus", "split",
            "fii", "dii", "rbi", "fed", "inflation", "gdp", "buyback", "merger",
            "ipo", "listing", "intraday", "trading", "bull", "bear", "rally", "crash",
            "gift nifty", "usd/inr", "gold", "crude", "tlt", "bond", "forex",
            "reliance", "tcs", "infosys", "hdfc", "icici", "sbi", "lt", "axis"
        ]
        return any(k in text for k in trending_keywords)
    except Exception:
        return False


def is_valid_link(link: str) -> bool:
    """Valid links only - working https, no broken"""
    try:
        if not link or not isinstance(link, str):
            return False
        if not link.startswith("http"):
            return False
        if "TRADINGVIEW" in link.upper():
            return False
        if len(link) > 500 or len(link) < 20:
            return False
        trusted_domains = ["moneycontrol.com", "economictimes.indiatimes.com", "news.google.com",
                           "nseindia.com", "bseindia.com", "investing.com", "livemint.com",
                           "financialexpress.com", "business-standard.com"]
        low = link.lower()
        if not any(d in low for d in trusted_domains):
            return False
        return True
    except Exception:
        return False


def _parse_rss_items(resp_content, source: str, limit: int, hours: int, require_fno: bool = True) -> list:
    """Common RSS parser - fresh + F&O-relevant + valid-link items."""
    all_news = []
    root = ET.fromstring(resp_content)
    for item in root.findall(".//item")[:40]:
        title = item.find("title")
        link = item.find("link")
        desc = item.find("description")
        pub = item.find("pubDate")

        title_text = title.text if title is not None and title.text else ""
        link_text = link.text if link is not None and link.text else ""
        desc_text = desc.text if desc is not None and desc.text else ""
        pub_text = pub.text if pub is not None and pub.text else ""

        if not is_fresh(pub_text, hours=hours):
            continue
        if not is_trending_financial_news(title_text, desc_text):
            continue
        if require_fno and not is_relevant_to_fno(title_text, desc_text):
            continue
        if not is_valid_link(link_text):
            continue
        if not title_text or len(title_text) < 15:
            continue

        all_news.append({
            "source": source,
            "title": title_text,
            "link": link_text,
            "desc": desc_text[:300],
            "date": pub_text,
            "symbol": extract_symbol_from_text(title_text + " " + desc_text),
            "fresh": f"{hours}H",
        })
        if len(all_news) >= limit:
            break
    return all_news


@st.cache_data(show_spinner=False, ttl=60)
def fetch_moneycontrol_trending_1hour(limit=15, hours=1):
    """Moneycontrol - Trending financial market news - Fresh + F&O relevant"""
    try:
        url = "https://www.moneycontrol.com/rss/MCtopnews.xml"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            return pd.DataFrame(_parse_rss_items(resp.content, "Moneycontrol", limit, hours))
        return pd.DataFrame()
    except Exception as e:
        print(f"Moneycontrol fetch error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=60)
def fetch_et_trending_1hour(limit=15, hours=1):
    """Economic Times Markets - Fresh + F&O relevant"""
    try:
        url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            return pd.DataFrame(_parse_rss_items(resp.content, "Economic Times", limit, hours))
        return pd.DataFrame()
    except Exception as e:
        print(f"ET RSS error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=60)
def fetch_google_news_trending_1hour(limit=15, hours=1):
    """Google News - NSE/F&O focused query - Fresh + F&O relevant"""
    try:
        url = ("https://news.google.com/rss/search?q=NIFTY+OR+BANKNIFTY+OR+"
               "%22stock+market%22+India&hl=en-IN&gl=IN&ceid=IN:en")
        resp = requests.get(url, headers=HEADERS, timeout=8)
        all_news = []
        if resp.status_code == 200:
            all_news = _parse_rss_items(resp.content, "Google News", limit, hours)
        return pd.DataFrame(all_news)
    except Exception as e:
        print(f"Google News error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=60)
def fetch_nse_trending_1hour(limit=10, hours=1):
    """NSE Announcements - F&O stocks ki hi announcements (SAFE: fail => empty)"""
    try:
        from news_corporate_events import get_nse_announcements
        nse_df = get_nse_announcements(days=max(1, hours // 24) or 1)
        if nse_df is not None and not nse_df.empty:
            fno = get_fno_symbol_set()
            formatted = []
            for _, row in nse_df.head(40).iterrows():
                symbol = str(row.get("symbol", ""))
                desc = str(row.get("desc", ""))
                date = str(row.get("date", ""))
                clean_symbol = symbol.replace(".NS", "").replace("https://", "").replace("http://", "").split("/")[0].split("?")[0].strip().upper()
                # USER RULE: sirf F&O universe ki announcements
                if not clean_symbol or clean_symbol not in fno:
                    continue
                link = f"https://www.nseindia.com/get-quotes/equity?symbol={clean_symbol}"
                formatted.append({
                    "source": "NSE",
                    "title": f"{clean_symbol} - {desc[:80]}",
                    "link": link,
                    "desc": desc,
                    "date": date,
                    "symbol": clean_symbol,
                    "fresh": f"{hours}H",
                })
                if len(formatted) >= limit:
                    break
            return pd.DataFrame(formatted)
        return pd.DataFrame()
    except Exception as e:
        print(f"NSE trending error (safe): {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=60)
def get_all_powerful_free_news(limit_per_source=10, hours=1):
    """Combine all sources - Fresh, F&O-relevant only, Valid links"""
    try:
        dfs = []
        nse_df = fetch_nse_trending_1hour(limit_per_source, hours)
        if not nse_df.empty:
            dfs.append(nse_df)
        mc_df = fetch_moneycontrol_trending_1hour(limit_per_source, hours)
        if not mc_df.empty:
            dfs.append(mc_df)
        et_df = fetch_et_trending_1hour(limit_per_source, hours)
        if not et_df.empty:
            dfs.append(et_df)
        gn_df = fetch_google_news_trending_1hour(limit_per_source, hours)
        if not gn_df.empty:
            dfs.append(gn_df)

        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.drop_duplicates(subset=["title"], keep="first")
            combined = combined[combined["link"].apply(is_valid_link)]
            # USER RULE: sirf F&O universe ya usse affect hone wali macro news
            combined = combined[combined.apply(
                lambda row: is_relevant_to_fno(row["title"], row["desc"]), axis=1)]
            return combined.head(30)
        return pd.DataFrame()
    except Exception as e:
        print(f"All powerful news error: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=60)
def get_verified_news_with_gemini_layers(hours=1):
    """Multi-layer verification - Fresh, F&O-relevant, Valid Links"""
    try:
        all_news_df = get_all_powerful_free_news(hours=hours)
        if all_news_df.empty:
            return pd.DataFrame()

        powerful_keywords = ["result", "dividend", "bonus", "split", "buyback", "merger",
                             "rbi", "fed", "inflation", "gdp", "profit", "loss", "board meeting",
                             "earnings", "nifty", "banknifty", "sensex", "fii", "dii", "ipo",
                             "rally", "crash", "trending", "live", "today", "breaking",
                             "repo", "rate", "tariff", "order win", "capex"]
        all_news_df["is_powerful"] = all_news_df["title"].str.lower().apply(
            lambda x: any(k in str(x).lower() for k in powerful_keywords))

        symbol_counts = all_news_df["symbol"].value_counts()
        all_news_df["cross_verified"] = all_news_df["symbol"].apply(
            lambda s: symbol_counts.get(s, 0) >= 2 if s else False)
        all_news_df["confidence"] = all_news_df.apply(
            lambda row: "High" if row["cross_verified"] and row["is_powerful"]
            else "Medium" if row["is_powerful"] else "Low", axis=1)

        try:
            from secure_config import is_gemini_configured
            if is_gemini_configured():
                from gemini_analyzer import get_gemini_hypothesis_for_news
                verified = []
                for _, row in all_news_df.head(8).iterrows():
                    try:
                        hypo = get_gemini_hypothesis_for_news(
                            row.get("symbol", ""), row.get("title", "") + " " + row.get("desc", ""))
                        verified.append({
                            **row.to_dict(),
                            "gemini_bias": hypo.get("bias", "Neutral") if isinstance(hypo, dict) else "Neutral",
                            "gemini_reason_hindi": hypo.get("reason_hindi", "") if isinstance(hypo, dict) else "",
                            "gemini_impact": hypo.get("impact", "Medium") if isinstance(hypo, dict) else "Medium",
                        })
                    except Exception:
                        verified.append({**row.to_dict(), "gemini_bias": "Neutral",
                                         "gemini_reason_hindi": "", "gemini_impact": "Medium"})
                return pd.DataFrame(verified)
        except Exception as e:
            print(f"Gemini layer error: {e}")

        return all_news_df
    except Exception as e:
        print(f"Verified news error: {e}")
        return pd.DataFrame()


def get_news_for_symbol_powerful(symbol: str, limit=5, hours=24):
    """Ek F&O symbol ki fresh news (per-symbol, 24h default window)."""
    try:
        all_news = get_all_powerful_free_news(hours=hours)
        if all_news.empty:
            return pd.DataFrame()
        symbol_upper = symbol.replace(".NS", "").upper().split("?")[0].split("/")[0].strip()
        if not symbol_upper or "TRADINGVIEW" in symbol_upper or len(symbol_upper) > 20:
            return pd.DataFrame()
        filtered = all_news[
            all_news["symbol"].str.upper().str.contains(symbol_upper, na=False) |
            all_news["title"].str.upper().str.contains(symbol_upper, na=False)
        ]
        filtered = filtered[filtered["link"].apply(is_valid_link)]
        return filtered.head(limit)
    except Exception:
        return pd.DataFrame()
