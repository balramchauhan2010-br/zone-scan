# 🚀 Performance & "502 Bad Gateway" — kya fix kiya gaya

## 🔴 Asli problem

Render FREE plan = **0.1 CPU + 512 MB RAM**.

`data_fetch.py` me Yahoo se bahut zada history mangi ja rahi thi, aur
har chunk ka bada raw DataFrame memory me rehta tha →
**OOM → container kill → browser me "502 Bad Gateway" / "CONNECTING"**.

Baseline (sirf imports) hi **~155 MB** lete hain — data ke liye ~350 MB bachta hai.

## ✅ Jo fix kiya (data_fetch.py)

| Cheez | Pehle | Ab |
|-------|-------|-----|
| Chunk size | `40` | **`ZS_CHUNK` (default 15)** |
| Memory release | nahi | **`del df` + `gc.collect()` har chunk ke baad** |
| dtype | float64 | **float32** (aadhi memory) |
| Bars retained | sab | **`ZS_KEEP_BARS` (default 800)** |

```python
# data_fetch.py
CHUNK_SIZE = int(os.environ.get("ZS_CHUNK", "15"))
KEEP_BARS  = int(os.environ.get("ZS_KEEP_BARS", "800"))
...
sub = sub.astype("float32")
if KEEP_BARS and len(sub) > KEEP_BARS:
    sub = sub.iloc[-KEEP_BARS:]
...
del df
gc.collect()
```

## ✅ Universe fix (fno_universe.py)

Deploy par `fno_stocks_fallback.json` kabhi-kabhi missing/unreadable ho jata tha →
`load_fallback()` chupchap `[]` lautata tha → **"All (0)" + koi zone nahi**.

Ab **210 symbols seedha code me embedded** hain (safety net):

```python
_EMBEDDED_FNO = ("360ONE", "ABB", ... )   # 210 symbols

def load_fallback():
    embedded = sorted(...)      # pehle embedded
    if embedded: return embedded
    try: ...JSON file...        # phir file
    except: return []
```

**Verify:** JSON file hata kar bhi `get_fno_symbols()` → **210**.

## 🧪 App ke andar Diagnostics

Page ke upar **🧪 Diagnostics** expander kholo — abhi ki memory, chunk/keep-bars,
aur universe size dikhta hai. (502 ki wajah turant samajh aati hai.)

## 🆘 Agar phir bhi 502 aaye

Render → **Environment** me ye daalo (code change ki zarurat nahi):

```bash
ZS_CHUNK=8
ZS_KEEP_BARS=450
ZS_WORKERS=1
```

Aur/ya scan chhota rakho:
- ✅ `🚀 Main: Fast (50)` / `🚀 Validated: Fast (50)` → hamesha chalta hai
- ⚠️ `🔍 Full (213)` + 10 timeframes → 5-10 min → 502 ka khatra

**Render Starter ($7/mo)** = 0.5 CPU + 2 GB → koi dikkat hi nahi.

## 🔒 Guarantee (machine-verified)

```bash
python3 verify_zone_source.py
```

```
✅ 1. Zone definitions sirf engine files me
✅ 2. Koi aur file zone factory define nahi karti
✅ 3. App/scanner layer me koi ad-hoc zone/level logic nahi
✅ 4. Engine files UNTOUCHED (SHA-256 manifest)
```

`ENGINE_MANIFEST.sha256`:
```
3518c3b2…  zone_core.py
ea55e51a…  zone_core_validation.py
```
