# 📊 Trader Pulse — Senior Demand & Supply Trader Analysis
### zone-scan repo ka gap analysis + naya AI Trader Pulse feature

> Ye document ek **senior D&S (Demand & Supply) trader** ke nazariye se likha gaya hai.
> Pehle batata hai ki repo me **kya kami thi**, phir **kya add kiya gaya**, aur
> naye data columns ka **trader ko kya matlab samajhna chahiye**.

---

## 1️⃣ Repo kya karta hai (samajh)

`zone-scan` ek Streamlit app hai jo `zone_core.py` naam ke engine se poore **NSE F&O
universe** ko scan karta hai aur har stock ke har timeframe (15m se Monthly tak)
ke **live supply/demand zones** (RBR/DBR/DBD/RBD patterns + 4 extra rules) ek table
me dikhata hai: Entry (Proximal), Stop Loss (Distal+buffer), Target, aur LTP se
distance. Saath me market tape, FII/DII badge, global cues, news, sector mapping,
per-zone hypothesis aur optional Dhan/Gemini integration hai.

**Mazbooti:** zone detection engine solid hai, perf fixes ache hain, UI clean hai.

---

## 2️⃣ Kya kami thi — ek senior D&S trader ke nazariye se

Ek professional D&S trader **sirf chart zones nahi dekhta**. Ek zone tabhi
trade-worthy hota hai jab uske peeche **flow data** (delivery, OI, volume, FII)
abino confirm kare. Is repo me ye sab ya to bilkul nahi tha, ya bahut limited tha:

### ❌ Gap 1 — Delivery % data bilkul nahi tha
**Kyun zaroori hai:** Delivery % batata hai ki kitne % traded shares **actually
haath badle** (physical settlement) vs intraday speculation. Delivery badhna =
**accumulation** (smart money khareed raha hai), girna = **distribution**
(profit booking). Ye sabse purana aur sabse reliable "smart money" signal hai.
Zone ke upar agar delivery bhi badh rahi hai toh zone ki quality aur bhi mazboot.

**Pehle kya tha:** Kahin bhi delivery data nahi — na table me, na analysis me.

### ❌ Gap 2 — Breadth sirf ek chhota badge tha
**Kyun zaroori hai:** "% of F&O futures stocks that increased" batata hai ki
poora market breadth **healthy hai ya sirf kuch heavyweights chal rahe hain**.
>55% groen = healthy breadth, <45% = kamzor (index ko sirf kuch stocks sambhal
rahe hain).

**Pehle kya tha:** `cached_breadth_for_all` se up/down count aata tha (Yahoo se,
sirf selected universe ka), sirf ek badge me — na poore F&O futures ka, na
koi section me, na AI summary ka hissa.

### ❌ Gap 3 — Option OI data bilkul nahi tha (sabse bada gap)
**Kyun zaroori hai:** Options OI batata hai ki **asli supply/demand kahan ban
rahi hai**:
- **PCR (Put/Call Ratio)** — >1.1 matlab zyada put writing → neeche support
- **Max Pain** — jis strike par option writers ko sabse kam nuksan → expiry
  uske aas-paas settle hone ki sambhavna
- **Support/Resistance strikes** — sabse zyada PE OI = support, sabse zyada
  CE OI = resistance
- **4-way OI buildup** — price ↑ + OI ↑ = **Long Buildup** (bullish), price ↓ +
  OI ↑ = **Short Buildup** (bearish), price ↑ + OI ↓ = **Short Covering**
  (bullish), price ↓ + OI ↓ = **Long Unwinding** (bearish)
- **Put Writing / Call Writing** — kis side positions ban rahi hain

**Pehle kya tha:** Bilkul nahi. Ek D&S trader ke liye ye "zone ka confirmation
data" hai — bina iske zone pe blind trust nahi hota.

### ❌ Gap 4 — Volume + Price analysis nahi tha
**Kyun zaroori hai:** Zone tabhi valid hota hai jab usme **volume confirmation**
ho. Volume 2× se upar + price move = real participation. Volume girna + price
move = kamzor move, zone fail ho sakta hai.

**Pehle kya tha:** Indicators hypothesis me vol_ratio tha, lekin scan table me
na volume column tha, na "volume vs yesterday".

### ❌ Gap 5 — FII/DII sirf badge me tha
**Kyun zaroori hai:** FII buying + DII selling = positive flow (aur vice versa).
Trend (3 din ka) zyada important hai than ek din ka number.

**Pehle kya tha:** Last day FII/DII net badge me tha — trend table, per-stock
context, aur AI summary me use nahi hota tha.

### ❌ Gap 6 — Koi combined "AI Market Summary" nahi tha
**Kyun zaroori hai:** Ek trader ko har roj subah ek **2-minute briefing** chahiye:
breadth kaisa hai, delivery trend kya hai, OI kya keh raha hai, FII/DII kya
kiya, global cues kaise hain, aaj ke events kya hain — aur is sab ka **matlab
kya hai** aur **kal ka kya forecast hai**.

**Pehle kya tha:** Har cheez alag-alag thi (badges, news box neeche, per-zone
hypothesis). Koi fusion nahi — trader ko khud sab jodna padta tha.

### ❌ Gap 7 — Top 10 Buy / Top 10 Sell forecast nahi tha
**Kyun zaroori hai:** Zone scanner hazaaron zones deta hai. Trader ko chahiye
**Top 10 actionable ideas** — zone + delivery + OI + volume + FII + global +
news ka composite score.

**Pehle kya tha:** Sirf zones ki list. Koi ranking, koi composite scoring nahi.

### ❌ Gap 8 — Pre-Market / Post-Market structure nahi tha
**Kyun zaroori hai:**
- **Pre-market (subah 9:15 se pehle):** GIFT/global cues, overnight OI signal,
  pichhle din ki delivery trend, aaj ke events, aur aaj ki Top 10 watchlist —
  taaki din ka plan ban sake.
- **Post-market (3:30 ke baad):** Aaj ka delivery % vs kal, breadth %, volume
  surges, OI signals, FII/DII, gainers/losers — aur **kal ka forecast**.

**Pehle kya tha:** Ek hi undifferentiated page — din ke kis phase me kya dekhna
chahiye, ye structure nahi tha.

### ❌ Gap 9 — `indicators_hypothesis.py` missing tha (bonus finding)
`app.py` ye module optional import karta hai, lekin **repo me file thi hi nahi** —
isliye `INDICATOR_AVAILABLE = False` ho jata tha aur Detailed Zone Analysis hamesha
stub fallback par chalta tha (RSI/EMA/Supertrend/MACD hamesha "default" values).
**Ab fix kar diya** — naya `indicators_hypothesis.py` add kiya with real
RSI/EMA20/50/200/Supertrend/MACD/volume-ratio + Hinglish rule-based hypothesis.

### ❌ Gap 10 — `zone_core_validation_v2.py` missing tha (bonus finding)
Validated page ka "v2 engine" selector hai lekin **file nahi thi** — v2 hamesha
unavailable tha. (Ye zone-detection engine se related hai, isliye yahan note
kiya — isme change nahi kiya, bas bataya.)

---

## 3️⃣ Kya add kiya gaya (AI Trader Pulse)

Naya module **`market_pulse.py`** + naye columns + naya UI section:

### 📌 Naye table columns (zone scanner table me, dono pages par)
| Column | Matlab (trader ko) |
|---|---|
| **Delivery %** | Aaj kitne % shares deliver hue (NSE official bhavcopy se). 60%+ = bahut mazboot accumulation |
| **ΔDeliv pp** | Aaj ka delivery % **vs pichhla din** kitne point badha/gira. +5pp↑ = accumulation badh raha hai |
| **Vol ×Yday** | Aaj ka volume pichhle din ka kitna guna. ≥1.5× = bada participation, ≥2× = bahut mazboot |
| **OI Signal** | Futures/Options OI se 4-way signal: Long Buildup 🟢 / Short Buildup 🔴 / Short Covering 🟢 / Long Unwinding 🔴 / Put Writing 🟢 / Call Writing 🔴 |

### 📌 Top strip (page ke top par, market tape ke neeche)
Phase badge (🌅 Pre-Market / ⚡ Open / 🌇 Post-Market) + NIFTY PCR + FII/DII +
Global cues + **🧠 AI Bias** (ek-line) — poori page ka "health check" ek nazar me.

### 📌 Full section: 🧠 AI Trader Pulse — Pre-Market / Post-Market Briefing
Market phase ke hisaab se **default section auto-select** hota hai:

**🌅 Pre-Market Setup** (subah, market khulne se pehle):
- Global cues (US/Asia/Europe), DXY, USD/INR, Crude, Gold
- Option OI **overnight signal**: NIFTY + BANKNIFTY PCR, max pain, support/resistance, put/call writing
- Delivery trend (latest EOD vs previous day): top gainers/losers
- Aaj ke events: global macro calendar + Indian market news (with bias)
- 🤖 **AI Short Summary** (Hinglish): sab data ka fusion + **matlab** + **aaj ka forecast**
- 🎯 **Top 10 BUY / Top 10 SELL watchlist** for the day

**🌇 Post-Market Review** (shaam, session band hone ke baad):
- 📈 **% of F&O futures stocks increased** (the headline metric you asked for) + advancers/decliners + breadth bar
- 📦 **Aaj ka Delivery % vs Pichhla Din** — top gainers (accumulation) / losers (distribution)
- 📊 Top gainers/losers, volume breakouts (≥1.5×), OI signal table
- 🧾 Option chain EOD: PCR, max pain, support/resistance per index
- 💰 FII/DII full data
- 🤖 **AI Short Summary** + **kal ka forecast**
- 🎯 **Top 10 BUY / Top 10 SELL** for next session

### 📌 🤖 AI Short Summary kaise kaam karta hai (bina kisi API key ke)
Rule-based **data fusion engine** — har signal ko score karta hai:

| Signal | Weight | Logic |
|---|---|---|
| Breadth % up | ±1.0 | >55% bullish, <45% bearish |
| Avg Delivery Δ | ±1.0 | ≥+2pp accumulation, ≤-2pp distribution |
| NIFTY/BANKNIFTY PCR | ±0.5 each | ≥1.1 support, ≤0.9 resistance |
| FII net | ±1.0 | FII buying = support, selling = drag (DII se cross-check) |
| Global cues | ±0.75 | US/Asia/Europe bias + USD/INR + Crude |
| News sentiment | ±0.5 | Bullish vs bearish headlines count |

Score ≥ +1.5 → **Bullish 📈**, ≤ -1.5 → **Bearish 📉**, beech me → Mild/Neutral.
Output me 3 cheezein hoti hain:
1. **Summary** — kya hua / kya setup hai
2. **📖 Matlab** — iska arth kya hai (trader language me)
3. **🔮 Forecast** — agla session kaisa rahega + key levels (support/resistance/max pain)

Gemini key ho toh ek button se summary aur gehri ho sakti hai (optional).

### 📌 Top 10 Buy / Sell kaise banta hai
Composite score per stock:
- **Zone part (sabse zyada weight):** sabse nazdeek DEMAND/SUPPLY zone (40 pts), Fresh +8, HQ +8, bada TF +5
- **Delivery:** Δdelivery +5pp↑ = +12 (buy) / -5pp↓ = +12 (sell); high delivery % +5
- **Volume:** ≥2× = +8, ≥1.5× = +5
- **OI signal:** Long Buildup/Short Covering/Put Writing = +8 (buy); Short Buildup/Long Unwinding/Call Writing = +8 (sell)
- **PCR:** ≥1.05 +3 (buy) / ≤0.95 +3 (sell)
- **Context:** FII buying +4, global bullish +3, bullish news +5
- Har row me **Reason** column me Hinglish explanation (kaun-kaun se factors mile)

---

## 4️⃣ Data sources (sab FREE, bina kisi API key ke)

| Data | Source | Format handle karta hai |
|---|---|---|
| Delivery %, price, volume | NSE `sec_bhavdata_full_DDMMYYYY.csv` (archives.nseindia.com) | Plain CSV: `DELIV_QTY`, `DELIV_PER`, `CLOSE_PRICE`, `PREV_CLOSE`, `TTL_TRD_QNTY` |
| CM fallback | NSE CM bhavcopy zip (`cm{DD}{MON}{YYYY}bhav.csv.zip`) + UDiff (`BhavCopy_NSE_CM_...`) | Legacy space-style + underscore-style + UDiff columns |
| FO OI, option aggregates, breadth | NSE FO bhavcopy — UDiff (`BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`, post Jul-2024) + legacy (`fo{DD}{MON}{YYYY}bhav.csv.zip` at `DERIVATIVES` path) + daily-reports API fallback | Legacy: `INSTRUMENT/OPEN_INT/CHG_IN_OI/CONTRACTS`; UDiff: `TckrSymb/FinInstrmTp/OpnIntrst/ChngInOpnIntrst` |
| Option chain (PCR, max pain) | NSE `option-chain-indices` / `option-chain-equities` API | `records.data[].CE/PE.openInterest/changeinOpenInterest` |
| FII/DII | NSE `fiidiiTradeReact` API (via existing `fii_dii_fetcher.py`) | — |
| Global cues | NSE world indices API + Yahoo (DXY/USDINR/Crude/Gold) | — |
| News + macro events | Existing `powerful_news_fetcher.py` + `global_macro_fetcher.py` | — |

**Freshness:** NSE bhavcopy **sham ~18:30-19:00 IST** ke baad publish hota hai.
Isliye:
- **Pre-market** me "latest EOD" = pichhla trading day (overnight positioning) — dates clearly dikhte hain
- **Post-market (7pm ke baad)** me = aaj ka vs pichhla din (exactly what you asked)
- App automatically walk-back karta hai agar aaj ki file abhi nahi mili

**Cache:** 30 min (bhavcopy/OI), refresh button available in the section.

---

## 5️⃣ Kaise use karein (daily workflow)

**🌅 Subah 8:00-9:15 (Pre-Market):**
1. Page kholein → top strip pe **🧠 AI Bias** dekhein
2. **Pre-Market Setup** section me: global cues → option OI overnight signal →
   delivery trend → aaj ke events → AI summary padhein
3. **Top 10 BUY/SELL watchlist** se aaj ke candidates note karein
4. Zone table me unhi stocks ki **nayi columns** (Delivery %, ΔDeliv, Vol ×, OI Signal) cross-check karein

**⚡ Din me (Market Open):**
- Top strip live hai; zone table ka LTP live refresh hota hai (existing feature)
- Post-Market section me **LIVE (so far)** data dikhega

**🌇 Shaam 7pm ke baad (Post-Market):**
1. **Post-Market Review** section kholein
2. **% F&O futures groen** dekhein — breadth healthy tha ya nahi
3. **Delivery % aaj vs kal** — kaun accumulate ho raha hai, kaun distribute
4. OI signals + FII/DII → kis side ka haath mazboot tha
5. AI summary ka **🔮 kal ka forecast** padhein
6. **Top 10 for next session** se kal ki watchlist taiyaar

---

## 6️⃣ Limitations (zarur padhein)

1. **Bhavcopy sham ko aata hai** — din me delivery data nahi milta (EOD data hai).
   Intraday decisions ke liye live OI (option chain API) + live breadth use karein.
2. **NSE datacenter IPs block karta hai** — agar sab kuch fail ho jaye toh app
   gracefully "—"/"Data unavailable" dikhata hai, kabhi nahi rukta. Local/home
   connection par sabse accha kaam karta hai.
3. **Breadth proxy:** F&O futures stocks ke liye cash-segment close change use
   hota hai (FO settle vs prev settle na milne par) — direction 99% same hota hai.
4. **OI signal** futures OI + option OI aggregate se banta hai — ye end-of-day
   positioning batata hai, intraday OI flux nahi.
5. **Top 10 / AI summary educational hai** — financial advice nahi. Real trades
   se pehle zone + SL + risk management zaroor dekhein.
6. **Option chain API kabhi-kabhi 401 deti hai** (cookie issue) — fallback FO
   bhavcopy OI aggregates se PCR nikalta hai.

---

## 7️⃣ File changes summary

| File | Change |
|---|---|
| `market_pulse.py` | **NEW** — poora AI Trader Pulse engine (data + signals + AI summary + Top 10 + UI) |
| `indicators_hypothesis.py` | **NEW** — missing module (RSI/EMA/Supertrend/MACD + Hinglish hypothesis) — app.py isko already import karta tha |
| `app.py` | Pulse import + top strip + 4 naye table columns (enrichment) + full Pre/Post-Market section |
| `TRADER_PULSE_ANALYSIS.md` | **NEW** — ye document |
| `README.md` | Features + project layout update |

**Self-test (bina network ke):** `python market_pulse.py` — 10 fixture tests against
real NSE formats (sec_bhavdata_full, CM legacy, FO legacy, FO UDiff, option chain,
URL builders, top10 scoring, enrichment, AI summary, market phase).
**Indicators self-test:** `python indicators_hypothesis.py`
