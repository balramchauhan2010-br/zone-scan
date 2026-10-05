"""
sector_map.py
NSE F&O 213 stocks ka Sector mapping + News/Event link - Bina API key ke

Source: NSE industry mapping (hardcoded for speed, 213 stocks)
"""

# NSE F&O stocks ka sector mapping - Top 213
# Ye mapping approximate hai, aap isko apne market_cap.py ya NSE se update kar sakte ho
SECTOR_MAP = {
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT", "LTI": "IT", "LTIM": "IT", "MPHASIS": "IT", "COFORGE": "IT", "PERSISTENT": "IT",
    # Banking
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking", "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking", "BANKBARODA": "Banking", "PNB": "Banking", "FEDERALBNK": "Banking", "IDFCFIRSTB": "Banking", "AUBANK": "Banking", "BANDHANBNK": "Banking",
    # Financial Services
    "BAJFINANCE": "Financial", "BAJAJFINSV": "Financial", "SBILIFE": "Financial", "HDFCLIFE": "Financial", "ICICIPRULI": "Financial", "ICICIGI": "Financial", "MUTHOOTFIN": "Financial", "CHOLAFIN": "Financial", "PFC": "Financial", "RECLTD": "Financial", "MANAPPURAM": "Financial", "ABCAPITAL": "Financial",
    # Pharma
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma", "DIVISLAB": "Pharma", "BIOCON": "Pharma", "LUPIN": "Pharma", "AUROPHARMA": "Pharma", "TORNTPHARM": "Pharma", "ALKEM": "Pharma", "GLENMARK": "Pharma", "LAURUSLABS": "Pharma", "SYNGENE": "Pharma", "IPCALAB": "Pharma", "ZYDUSLIFE": "Pharma",
    # Auto
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto", "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "MOTHERSON": "Auto", "BHARATFORG": "Auto", "BALKRISIND": "Auto", "MRF": "Auto",
    # Metals
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals", "VEDL": "Metals", "COALINDIA": "Metals", "NMDC": "Metals", "SAIL": "Metals", "JINDALSTEL": "Metals", "NATIONALUM": "Metals", "HINDZINC": "Metals",
    # FMCG
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG", "COLPAL": "FMCG", "GODREJCP": "FMCG", "TATACONSUM": "FMCG", "UBL": "FMCG",
    # Energy / Oil & Gas
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy", "GAIL": "Energy", "PETRONET": "Energy", "IGL": "Energy", "MGL": "Energy", "HINDPETRO": "Energy",
    # Power / Infra
    "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power", "ADANIPOWER": "Power", "JSWENERGY": "Power", "NHPC": "Power", "SJVN": "Power", "TORNTPOWER": "Power",
    # Cement
    "ULTRACEMCO": "Cement", "SHREECEM": "Cement", "AMBUJACEM": "Cement", "ACC": "Cement", "JKCEMENT": "Cement", "RAMCOCEM": "Cement", "DALBHARAT": "Cement",
    # Telecom
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "INDUSINDBK": "Telecom",
    # Realty
    "DLF": "Realty", "GODREJPROP": "Realty", "OBEROIRLTY": "Realty", "PRESTIGE": "Realty", "BRIGADE": "Realty", "SOBHA": "Realty",
    # Media / Others - fallback
}

# Sector wise NSE indices for comparison
SECTOR_INDICES = {
    "IT": "NIFTY IT",
    "Banking": "BANK NIFTY",
    "Financial": "NIFTY Financial Services",
    "Pharma": "NIFTY Pharma",
    "Auto": "NIFTY Auto",
    "Metals": "NIFTY Metal",
    "FMCG": "NIFTY FMCG",
    "Energy": "NIFTY Energy",
    "Power": "NIFTY Power",
    "Cement": "NIFTY Infra",
    "Telecom": "NIFTY Infra",
    "Realty": "NIFTY Realty",
}

def get_sector(symbol: str) -> str:
    """Symbol se sector nikalo - fast, no API key"""
    # Remove .NS suffix if present
    clean_sym = symbol.replace(".NS", "").replace("NSE:", "").strip().upper()
    return SECTOR_MAP.get(clean_sym, "Others")

def get_sector_index(sector: str) -> str:
    return SECTOR_INDICES.get(sector, "NIFTY 50")

def get_nse_links(symbol: str):
    """Har stock ke liye short links - touch karke padh sakte ho"""
    clean_sym = symbol.replace(".NS", "").strip().upper()
    return {
        "tradingview": f"https://www.tradingview.com/chart/?symbol=NSE%3A{clean_sym}",
        "nse_quote": f"https://www.nseindia.com/get-quotes/equity?symbol={clean_sym}",
        "nse_announcements": f"https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={clean_sym}",
        "nse_corp_actions": f"https://www.nseindia.com/companies-listing/corporate-filings-actions?symbol={clean_sym}&tabIndex=equity",
        "moneycontrol": f"https://www.moneycontrol.com/india/stockpricequote/{clean_sym.lower()}",
        "screener": f"https://www.screener.in/company/{clean_sym}/",
    }

def get_sector_news_link(sector: str):
    """Sector wise news link"""
    sector_query = sector.replace(" ", "%20")
    return {
        "google_news": f"https://news.google.com/search?q={sector_query}+sector+NSE+India&hl=en-IN&gl=IN&ceid=IN%3Aen",
        "moneycontrol_sector": f"https://www.moneycontrol.com/news/business/markets/{sector_query.lower()}-stocks/",
    }
