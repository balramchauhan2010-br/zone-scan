# 🗺️ Roadmap — आगे क्या sudhaar karein

**Aaj ki sthiti (baseline):**

| Cheez | Value |
|-------|-------|
| Engine | `zone_core_validation.py` (Pine 1:1 + 5 rules + RULE TABLE v2) |
| Universe | 210 NSE F&O |
| Active zones (Daily) | ~53 · 1H ~48 · 15m ~36 |
| Best exit | `PB2_TRAIL` (partial @2R + trail) |
| Best filter (walk-forward) | Dep≥3+Trend **+0.50R** (13/15 folds) |
| Baseline avgR | ~0.64 → filtered ~0.90–1.14 |
| Capital / risk | ₹25,000 · 1% = ₹250/trade |
| Data | Yahoo (delayed, 60d intraday, survivorship bias) |

> ⚠️ **Sabse badi kami:** abhi tak sab kuch **backtest** hai — full-sample optimized.
> Ek bhi **live/paper trade** nahi hua. Isliye Tier 1 sabse jaroori hai.

---

# 🔴 TIER 1 — Trust banana (agle 1–2 hafte)

## 1️⃣ Forward-Test Journal ⭐ *SABSE PEHLE YE KARO*

**Kyun:** walk-forward achha hai, par wo bhi historical hai. Asli saboot sirf
aane wale data se milega. Ye ek hi cheez strategy ko "sach mein kaam karta hai"
ya "backtest me hi achha tha" batayegi.

**Kya karna:**
- Roz EOD ek **paper-trade journal** chalao (koi paisa nahi lagta)
- Har zone touch par entry/SL/target likho, 30 din tak
- 30 din baad compare karo: **realized avgR vs backtest avgR**

**Banane wala module:** `forward_test.py`
```
Har din (15:35 IST):
  1. NSE 210 scan (Daily + 1H)
  2. Naye zones → journal me daalo (entry, SL, target, PLOS2, legOutRR)
  3. Purane open trades check karo → SL/Target laga? → result likho
  4. SQLite me save (Render pe bhi chalega)
```
**Expected output:** `journal.db` + ek naya **"📈 Track Record"** tab jisme
realized WR / avgR / PF / equity curve dikhe.

**Success criteria (30 din baad):**
- ✅ avgR ≥ 0.6 aur ≥ 25 trades → aage badho
- ⚠️ avgR 0.3–0.6 → filters aur tight karo
- ❌ avgR < 0.3 → mat chalao, pehle Tier 3

---

## 2️⃣ Execution realism — backtest ko sachcha banao

Abhi backtest maan leta hai ki proximal line par **hamesha** fill ho gaya.
Asli duniya me aisa nahi hota.

**Add karo:**
| Cheez | Model |
|-------|-------|
| Slippage | 0.05% entry par, 0.10% SL par (SL gap-down par worse) |
| Gap-through | agar open hi SL se paar ho → SL us open price par fill |
| Partial fill | zone ke beech me entry → 50% chance |
| MIS square-off | 15:15 IST par强制 exit (MIS trades ke liye) |
| No-trade days | expiry day + budget day optional |

**Impact:** avgR realistically ~0.10–0.20R kam hoga. Ye **achha** hai —
jhoothi ummeed se bachata hai.

---

## 3️⃣ Data quality — Yahoo se aage badho

| Problem | Fix |
|---------|-----|
| Surviorship bias (sirf aaj ki F&O list) | 2020 ki F&O list lekar backtest dobara chalao |
| Adjusted prices (dividend/split se zones distorted) | **unadjusted** close use karo, ya Dhan historical |
| 15m sirf 60 din | Dhan `intraday_minute_data` (5 din) + `historical_daily_data` |
| Delayed quotes | Dhan websocket (Tier 2) |

**Step:** `dhan_live.py` ka **DATA** layer pehle wire karo (orders nahi, sirf data).

---

# 🟠 TIER 2 — Automation (2–6 hafte)

## 4️⃣ Live Alerts — zone touch hone par turant khabar

`dhan_live.py` ka data layer + websocket:

```
Dhan websocket (210 symbols)
   → har tick par check: price kisi active zone ke proximal ke paas?
   → 🎯 AT ZONE (≤0.25%) ya zone ke andar ghusa?
   → Telegram / Email alert
```

**Kyun jaroori:** abhi aapko manually SCAN dabana padta hai. Zone kabhi
2 minute me touch ho jata hai aur nikal jata hai.

**Effort:** medium · **Impact:** HIGH (execution quality)

---

## 5️⃣ Auto OCO orders — Dhan Super Order

Dhan ke paas native **Super Order (Bracket)** hai — yani OCO built-in:
```
Entry  LIMIT @ proximal
SL     @ distal + buffer
Target @ 1:3 (ya PB2_TRAIL ke hisaab se)
```
Ek hi API call me sab set ho jata hai — server-side, phone band ho to bhi chalega.

**Step:** pehle **PAPER** mode me chalao (quantity = 1 ya ₹100), 2 hafte.

⚠️ **Dhyan:** CNC me short nahi ho sakta → supply zones ke liye
**MIS intraday** ya **futures** use karo.

---

## 6️⃣ Scheduled EOD scan (Render Cron)

Roz shaam 15:35 IST auto-scan → journal me entry → subah 9:00 par alert list.

**Step:** `render.yaml` me `type: cron` service add karo, ya GitHub Actions.

---

# 🟡 TIER 3 — Edge badhana (1–3 mahine)

⚠️ **Ye tabhi karo jab Tier 1 pass ho jaye.** Warna aur overfit hoga.

## 7️⃣ Multi-Timeframe confluence
- Zone jo **2+ TFs** par ek hi jagah ho (jaise Daily + 1H) → strong
- Test: confluence zones ka avgR vs single-TF zones

## 8️⃣ Regime filter
- **NIFTY gate:** NIFTY EMA200 ke upar → sirf DEMAND zones; niche → sirf SUPPLY
- Backtest me ye check nahi hua — potential +0.1–0.3R

## 9️⃣ Portfolio risk limits
| Rule | Value |
|------|-------|
| Max concurrent trades | 3 |
| Max ek sector me | 1 |
| Daily loss cap | 2R → aaj aur trade nahi |
| Weekly loss cap | 5R → hafta band |

## 🔟 Universe expansion
- Nifty 500 / sector indices / F&O futures
- Futures = clean data + short allowed + leverage

## 1️⃣1️⃣ Time-of-day filter (intraday ke liye)
Backtest me mila: **09:15–10:00 best** (avgR 0.62), **12:00–13:00 sabse kharab** (−0.03).
Intraday trades ko is window tak simit karo.

---

# ⛔ KYA NAHI KARNA (overfit ke jaal)

| ❌ | Kyun nahi |
|----|-----------|
| Aur zada filters lagana | Har naya filter overfit ka risk badhata hai |
| Naye "custom" zone rules banana | Guarantee toot jayegi (`verify_zone_source.py`) |
| `zone_core*.py` edit karna | Wo locked hain — SHA-256 manifest hai |
| Param sweep se "best" combo dhoondhna | Full-sample optimization se OOS me fail hota hai |
| Capital badhana jab tak Tier 1 pass na ho | Pehle 30-din paper test |

**Rule of thumb:** koi bhi naya filter tabhi accept karo jab wo
**walk-forward + OOS + 30-din live paper test** — teeno me pass ho.

---

# 📅 Recommended order

```
Hafte 1-2   →  ① Forward-test journal  +  ③ Dhan data layer
Hafte 3-4   →  ② Execution realism (slippage/MIS)  → backtest dobara
Hafte 5-8   →  ④ Live alerts  +  ⑤ Paper OCO orders
Mahine 3    →  Tier 1 review: live vs backtest match?
                 ├── Haan → ⑥ cron +  ⑧ regime filter
                 └── Nahi → ruko, filters mat badhao, data/execution theek karo
Mahine 4-6  →  ⑦ confluence  +  ⑨ risk limits  +  capital badhao
```

---

# 🎯 Agar sirf EK cheez karuni ho

> **① Forward-Test Journal.**

30 din, ₹0 invest, sirf likhna. Iske baad aapko pata chalega ki
ye strategy **sach mein** kaam karti hai ya sirf backtest me achhi lagti hai.
Baaki sab isi ke result par depend karta hai.

---

## Shuruat kaise karein

```bash
# Tier 1 — ① forward_test.py banwana hai?
# Batao, main bana deta hoon:
#   - SQLite journal (Render pe persistent disk ke saath)
#   - Roz EOD scan → naye zones log
#   - "📈 Track Record" tab: realized WR / avgR / PF / equity curve
#   - 30-din baad auto backtest-vs-live comparison report
```
