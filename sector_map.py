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


# ------------------------------------------------------------------
# Sector -> देश-विदेश के macro drivers (कौन-सा news/data इस sector को
# प्रभावित करता है). yahoo = live quote key (app iska LTP/% dikhayega).
# ------------------------------------------------------------------
MACRO_DRIVERS = {
    "IT": [
        {"name": "USD/INR (₹ कमज़ोर = IT revenue ↑)", "yahoo": "USDINR=X", "why": "IT companies की कमाई डॉलर में है — रुपया गिरता है तो revenue/margin बढ़ता है"},
        {"name": "US 10Y Yield (US बाज़ार का mood)", "yahoo": "^TNX", "why": "US yields बढ़ें = tech spending/valuations पर दबाव"},
        {"name": "S&P 500 (US client spending)", "yahoo": "^GSPC", "why": "US clients के खर्चे ही IT deal-flow तय करते हैं"},
    ],
    "Banking": [
        {"name": "RBI Repo Rate / Liquidity", "yahoo": "", "why": "दर बढ़ी = NIM कम, growth loans धीमे; घटी = credit growth तेज़"},
        {"name": "US 10Y Yield (global fund flows)", "yahoo": "^TNX", "why": "US yields बढ़ें = FII emerging markets से पैसा निकालते हैं"},
        {"name": "NIFTY (credit growth proxy)", "yahoo": "^NSEI", "why": "बाज़ार गिरे = loan risk sentiment खराब"},
    ],
    "Financial": [
        {"name": "RBI Repo Rate / Liquidity", "yahoo": "", "why": "NBFC/fin companies का borrowing cost सीधे repo से जुड़ा"},
        {"name": "US 10Y Yield", "yahoo": "^TNX", "why": "global rates = FII flows in financials"},
    ],
    "Pharma": [
        {"name": "USD/INR (exports ↑)", "yahoo": "USDINR=X", "why": "Pharma की US कमाई डॉलर में — ₹ कमज़ोर = फायदा"},
        {"name": "US 10Y Yield / US health policy", "yahoo": "^TNX", "why": "US drug-pricing news/FDA policy से pharma हिलता है"},
    ],
    "Auto": [
        {"name": "Crude Oil (ईंधन/रबर लागत)", "yahoo": "CL=F", "why": "तेल महंगा = EV पैक-पुश + पेट्रोल-वाहन मांग पर दबाव, freight/input cost बढ़ता"},
        {"name": "USD/INR (imported parts)", "yahoo": "USDINR=X", "why": "₹ कमज़ोर = components/कच्चा माल महंगा, margin घटता"},
        {"name": "China Auto/EV demand", "yahoo": "000001.SS", "why": "global EV cycle और raw-material prices पर असर"},
    ],
    "Metals": [
        {"name": "DXY - Dollar Index (कीमतों का उलटा संकेत)", "yahoo": "DX-Y.NYB", "why": "डॉलर मजबूत = global metals सस्ते, भारतीय metal stocks पर दबाव"},
        {"name": "China SSE (सबसे बड़ा खरीदार)", "yahoo": "000001.SS", "why": "China stimulus/property news = steel/alu की global demand"},
        {"name": "Crude Oil (freight/energy cost)", "yahoo": "CL=F", "why": "ऊर्जा-लागत mining/smelting margin तय करती है"},
    ],
    "FMCG": [
        {"name": "Crude Oil (packaging/transport)", "yahoo": "CL=F", "why": "तेल महंगा = input+freight cost, margin पर दबाव"},
        {"name": "Monsoon/Rural demand", "yahoo": "", "why": "अच्छी फसल/मानसून = गांव की आमदनी = बिक्री तेज़"},
        {"name": "India CPI inflation", "yahoo": "", "why": "महंगाई बढ़ी = price-hike vs demand trade-off"},
    ],
    "Energy": [
        {"name": "Crude Oil (सीधा revenue link)", "yahoo": "CL=F", "why": "crude बढ़ा = upstream (ONGC) फायदे में, OMC (IOC/BPCL) को margin दबाव"},
        {"name": "Natural Gas", "yahoo": "NG=F", "why": "gas-based companies का input cost/revenue"},
        {"name": "USD/INR", "yahoo": "USDINR=X", "why": "import bill डॉलर में — ₹ कमज़ोर = OMC घाटा बढ़ सकता"},
    ],
    "Power": [
        {"name": "Monsoon (hydro + demand)", "yahoo": "", "why": "कम बारिश = hydro कम, AC-demand बढ़; ज़्यादा बारिश = उलटा"},
        {"name": "Crude/Coal (fuel cost)", "yahoo": "CL=F", "why": "imported coal महंगा = plant economics खराब"},
        {"name": "RBI rates (capex funding)", "yahoo": "", "why": "दरें बढ़ीं = बड़े projects का financing महंगा"},
    ],
    "Cement": [
        {"name": "Crude/Petcoke (fuel cost)", "yahoo": "CL=F", "why": "energy की हिस्सेदारी cost में सबसे ज़्यादा — तेल महंगा = margin घटता"},
        {"name": "Govt Infra Capex / Monsoon", "yahoo": "", "why": "सरकारी infra spend = demand; मानसून = निर्माण धीमा"},
        {"name": "USD/INR (imported coal)", "yahoo": "USDINR=X", "why": "₹ कमज़ोर = imported coal/fuel महंगा"},
    ],
    "Telecom": [
        {"name": "USD/INR (network equipment)", "yahoo": "USDINR=X", "why": "₹ कमज़ोर = 4G/5G gear का import महंगा (capex बढ़ता)"},
        {"name": "US 10Y (debt-heavy sector)", "yahoo": "^TNX", "why": "rates बढ़ें = telecom का बड़ा कर्ज़ महंगा"},
    ],
    "Realty": [
        {"name": "Interest Rates (home-loan EMI)", "yahoo": "^TNX", "why": "दरें बढ़ीं = EMI बढ़ती, flat-sales धीमी; घटीं = boom"},
        {"name": "RBI Liquidity", "yahoo": "", "why": "सस्ता कर्ज़ = builders व buyers दोनों को फायदा"},
    ],
}
_DEFAULT_DRIVERS = [
    {"name": "GIFT NIFTY / NIFTY trend", "yahoo": "^NSEI", "why": "बाज़ार का overall mood हर stock पर असर डालता है"},
    {"name": "Crude Oil", "yahoo": "CL=F", "why": "भारत import-देश — तेल महंगा = inflation + FII mood खराब"},
    {"name": "USD/INR", "yahoo": "USDINR=X", "why": "₹ कमज़ोर = FII outflow का दबाव"},
]


def get_macro_drivers_for_sector(sector: str) -> list:
    """Sector को प्रभावित करने वाले देश-विदेश के factors (name + live-yahoo-key + why)."""
    return MACRO_DRIVERS.get(str(sector or "").strip(), _DEFAULT_DRIVERS)
