"""
nse_mcp_client.py - official NSE MCP servers ka low-latency client
===================================================================

NSE ne do public MCP servers chalaye hain (no login, no API key, Streamable HTTP):

  * bhavcopy : https://mcp.nseindia.in/bhavcopy/cm/mcp
               End-of-day data (last ~5 saal), market breadth, top movers (EOD),
               52-week high/low, corporate actions, volume analysis ...
  * live     : https://mcp.nseindia.in/cmmkt/mcp
               Aaj ka live snapshot (NSE ke according 1-3 min behind; crawl ~5 min),
               cm_get_stock_quote, nse_get_market_movers, live gainers/losers ...

Ye module un tools ko app ke liye ek chhote, fast, fail-safe wrapper me deta hai:

  1. PERSISTENT SESSION  - ek hi MCP session poore app me reuse hota hai (har call par
                           naya TLS+initialize+list_tools nahi). Connect ek baar.
  2. PARALLEL BATCH      - 50 stocks ke quotes ek saath (semaphore-bounded), sequential nahi.
  3. TTL CACHE           - quote 10s, movers 60s, breadth/52w/corp-actions EOD-type data
                           ke liye lamba TTL. Ek candle ke andar repeat call nahi.
  4. CIRCUIT BREAKER     - connect fail ho to 60s tak NSE ko skip karo -> app kabhi
                           hang nahi hoti (default timeout: connect 5s, call 6s).
  5. SCHEMA-AWARE ARGS   - tool ki inputSchema se sirf valid arguments bhejte hain,
                           taaki NSE server ke tool signature change hone par bhi crash na ho.

IMPORTANT (latency reality):
  NSE MCP ka live data NSE ke hisaab se 1-3 min delay ka hota hai aur ye intraday
  OHLC candles (15m/1H...) nahi deta. Isliye:
    - Zone scan ke candles: Dhan intraday API / Yahoo (unchanged).
    - LTP tape: Dhan (sabse tez) > Yahoo > NSE MCP (aakhri fallback, keyless).
    - NSE MCP ka main kaam: keyless fallback + market-wide data (movers, breadth,
      52W, corporate actions) jo zone context me kaam aate hain.

  NSE ki terms ke according MCP data "informational/educational" use ke liye hai,
  real-time trading ya commercial deployment ke liye nahi. Ye baat README me bhi likhi hai.

Env overrides (optional):
  NSE_MCP_ENABLED=0           -> poora NSE MCP band
  NSE_MCP_LIVE_URL=...        -> live endpoint override
  NSE_MCP_BHAVCOPY_URL=...    -> bhavcopy endpoint override

Self-check / field verification (apne network se chalao, jahan NSE reachable ho):
  python nse_mcp_client.py --probe RELIANCE
  -> tools ki list + cm_get_stock_quote ka raw JSON dikhata hai, taaki field
     names (lastPrice / pChange etc.) confirm kar sako.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import warnings as _warnings

try:  # mcp SDK optional - na ho to module quietly disabled rahega (app crash nahi)
    with _warnings.catch_warnings():
        # mcp 1.x me streamablehttp_client ka naam deprecated hai (kaam wahi karta hai);
        # timeout= wala signature sirf isi naam me hai, isliye warning chup karke use karte hain.
        _warnings.simplefilter("ignore", DeprecationWarning)
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    _MCP_OK = True
    _MCP_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    _MCP_OK = False
    _MCP_IMPORT_ERR = repr(_e)[:200]

# runtime par streamablehttp_client ki deprecation warning (functional, harmless) chup
_warnings.filterwarnings("ignore", message=".*streamable_http_client.*", category=DeprecationWarning)

DEFAULT_LIVE_URL = "https://mcp.nseindia.in/cmmkt/mcp"
DEFAULT_BHAVCOPY_URL = "https://mcp.nseindia.in/bhavcopy/cm/mcp"

CONNECT_TIMEOUT = 5.0      # seconds - connect + initialize + list_tools
CALL_TIMEOUT = 6.0         # seconds per tool call
SSE_READ_TIMEOUT = 300.0   # streamable http long-poll window
BREAKER_SECONDS = 60.0     # connect fail hone par itni der NSE skip karo
MAX_PARALLEL_CALLS = 8     # ek saath kitne tool calls (NSE par dabav na pade)

# ---- tool names (NSE official MCP, 26 tools: bhavcopy 13 + cm-market 13) ----
SERVER_LIVE = "live"
SERVER_BHAV = "bhavcopy"

T_STOCK_QUOTE = "cm_get_stock_quote"          # live, 1 symbol
T_MARKET_MOVERS = "nse_get_market_movers"     # live gainers/losers (PRIMARY)
T_DATA_STATUS = "cm_get_data_status"          # live data freshness
T_52W = "get_52_week_high_low"                # bhavcopy
T_BREADTH = "get_market_breadth"              # bhavcopy, advance/decline
T_TOP_VOLUME = "get_top_by_volume"            # bhavcopy
T_CORP_ACTIONS = "get_corporate_actions"      # bhavcopy

_TTL = {
    T_STOCK_QUOTE: 10,
    T_MARKET_MOVERS: 60,
    T_DATA_STATUS: 30,
    T_52W: 3600,
    T_BREADTH: 900,
    T_TOP_VOLUME: 900,
    T_CORP_ACTIONS: 1800,
}

_LTP_KEYS = ("lastPrice", "last_price", "ltp", "lastTradedPrice", "last", "LTP", "close")
_CHG_PCT_KEYS = ("pChange", "percentChange", "change_pct", "changePct", "pct_change",
                 "percent_change", "chg_pct", "changePercent")
_CHG_KEYS = ("change", "netChange", "priceChange", "change_abs")


class _Unavailable(RuntimeError):
    """NSE endpoint abhi use nahi ho sakta (connect fail / cooldown / closed)."""


class _ToolMissing(RuntimeError):
    """Server ke tool list me ye tool nahi hai."""


# --------------------------------------------------------------------- helpers

def _dfs(obj: Any, key: str, depth: int = 0) -> Any:
    """Nested JSON me pehli matching key ka value (depth-limited, lists ke first 5 items)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        for v in obj.values():
            r = _dfs(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj[:5]:
            r = _dfs(v, key, depth + 1)
            if r is not None:
                return r
    return None


def _first(obj: Any, keys: Iterable[str]) -> Any:
    """Keys ki PRIORITY order me pehla value (har key ko poore object me dhoondhte hain)."""
    for k in keys:
        v = _dfs(obj, k)
        if v is not None:
            return v
    return None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, str):
            v = v.strip().replace(",", "").replace("%", "")
            if v in ("", "-", "--", "NA", "null"):
                return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _decode(result: Any) -> Any:
    """CallToolResult -> python object. Text JSON pehle (NSE isi form me deta hai),
    phir structuredContent fallback."""
    if getattr(result, "isError", False):
        texts = [getattr(c, "text", "") for c in (result.content or [])]
        raise RuntimeError("NSE MCP tool error: " + " ".join(texts)[:200])
    texts = [getattr(c, "text", None) for c in (result.content or []) if getattr(c, "type", "") == "text"]
    raw = "\n".join(t for t in texts if t).strip()
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return getattr(result, "structuredContent", None)


def _quote_from(symbol: str, data: Any) -> Optional[dict]:
    """cm_get_stock_quote ka response -> {ltp, change, change_pct, source}."""
    ltp = _num(_first(data, _LTP_KEYS))
    if not ltp or ltp <= 0:
        return None
    return {
        "ltp": ltp,
        "change": _num(_first(data, _CHG_KEYS)) or 0.0,
        "change_pct": _num(_first(data, _CHG_PCT_KEYS)) or 0.0,
        "source": "NSE MCP",
        "symbol": symbol,
    }


def _clean_symbol(s: str) -> str:
    return str(s).strip().upper().replace(".NS", "")


# ------------------------------------------------------------- endpoint layer

class _Session:
    """Ek MCP connection ka state. Har reconnect par naya object -> purane owner ka
    state naye session ko kabhi corrupt nahi karta."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.connected = False      # session live hai
        self.ready_ok = False       # kabhi initialize ho gaya tha
        self.need_reconnect = False # transport/timeout error -> agle request par naya session


class _Endpoint:
    """Ek MCP server ka persistent session. Saare methods background loop par chalte hain."""

    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self.schemas: Dict[str, dict] = {}
        self.down_until = 0.0
        self.last_error = ""
        self.connects = 0
        self._sess: Optional[_Session] = None
        self._lock: Optional[asyncio.Lock] = None

    @property
    def connected(self) -> bool:
        return bool(self._sess and self._sess.connected)

    # -- breaker
    def _trip(self, err: BaseException) -> None:
        self.down_until = time.time() + BREAKER_SECONDS
        self.last_error = repr(err)[:200]
        print(f"[nse-mcp] {self.name} down, {BREAKER_SECONDS:.0f}s skip: {self.last_error}")

    # -- owner task: session ko apne context me rakhta hai (anyio cancel-scope safe)
    async def _run_owner(self, sess: _Session) -> None:
        pending: set = set()
        try:
            async with streamablehttp_client(self.url, timeout=CONNECT_TIMEOUT,
                                             sse_read_timeout=SSE_READ_TIMEOUT) as (read, write, _):
                async with ClientSession(read, write,
                                         read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT)) as session:
                    await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
                    tl = await asyncio.wait_for(session.list_tools(), CONNECT_TIMEOUT)
                    self.schemas = {t.name: (t.inputSchema or {}) for t in tl.tools}
                    self.connects += 1
                    sess.connected = True
                    sess.ready_ok = True
                    sess.ready.set()
                    while not sess.need_reconnect:
                        tool, args, fut = await sess.queue.get()
                        t = asyncio.ensure_future(self._one(sess, session, tool, args, fut))
                        pending.add(t)
                        t.add_done_callback(pending.discard)
        except asyncio.CancelledError:
            raise
        except BaseException as e:  # connect ya transport error
            if not sess.ready_ok:
                self._trip(e)           # connect hi fail -> breaker
            else:
                self.last_error = repr(e)[:200]
        finally:
            sess.connected = False
            for t in list(pending):
                t.cancel()
            sess.ready.set()
            while not sess.queue.empty():
                _, _, fut = sess.queue.get_nowait()
                if not fut.done():
                    fut.set_exception(_Unavailable("NSE MCP session closed"))

    async def _one(self, sess: _Session, session: Any, tool: str, args: dict, fut: asyncio.Future) -> None:
        try:
            res = await session.call_tool(tool, args)
            if not fut.done():
                fut.set_result(res)
        except asyncio.CancelledError:
            if not fut.done():
                fut.cancel()
            raise
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            if type(e).__name__ != "McpError":  # transport/timeout -> connection reset
                sess.need_reconnect = True

    async def _ensure_session(self) -> _Session:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            s = self._sess
            if s is not None and s.connected and not s.need_reconnect:
                return s
            if time.time() < self.down_until:
                raise _Unavailable(f"{self.name} cooling down: {self.last_error}")
            if s is not None and s.task is not None and not s.task.done():
                s.task.cancel()
                await asyncio.gather(s.task, return_exceptions=True)
            new = _Session()
            new.task = asyncio.ensure_future(self._run_owner(new))
            self._sess = new
            try:
                await asyncio.wait_for(new.ready.wait(), CONNECT_TIMEOUT + 2)
            except asyncio.TimeoutError:
                self._trip(TimeoutError("connect timeout"))
                new.task.cancel()
                raise _Unavailable("NSE MCP connect timeout")
            if not new.connected:
                raise _Unavailable(f"{self.name} connect failed: {self.last_error}")
            return new

    async def request(self, tool: str, wanted: dict) -> Any:
        """Ek tool call. Schema ke hisaab se args filter, session reuse, timeout."""
        sess = await self._ensure_session()
        if tool not in self.schemas:
            raise _ToolMissing(f"{self.name}: tool '{tool}' server par nahi mila")
        args = _build_args(self.schemas[tool], wanted)
        fut = asyncio.get_running_loop().create_future()
        await sess.queue.put((tool, args, fut))
        return await asyncio.wait_for(fut, CALL_TIMEOUT + 2)


def _build_args(schema: dict, wanted: Dict[str, Any]) -> dict:
    """Sirf schema me declared, non-None args. Required missing ho to ValueError."""
    props = (schema or {}).get("properties") or {}
    given = {k: v for k, v in wanted.items() if v is not None}
    if props:
        given = {k: v for k, v in given.items() if k in props}
        missing = [r for r in (schema.get("required") or []) if r not in given]
        if missing:
            raise ValueError(f"required args missing: {missing}")
    return given


# ------------------------------------------------------------- public client

class NseMcpClient:
    """Thread-safe sync facade. Streamlit ke har script-run thread se safely call ho sakta hai."""

    def __init__(self, live_url: str = None, bhavcopy_url: str = None, enabled: bool = True):
        self.enabled = bool(enabled and _MCP_OK)
        self.import_error = "" if _MCP_OK else _MCP_IMPORT_ERR
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="nse-mcp-loop", daemon=True)
        self._thread.start()
        self._eps = {
            SERVER_LIVE: _Endpoint(SERVER_LIVE, live_url or DEFAULT_LIVE_URL),
            SERVER_BHAV: _Endpoint(SERVER_BHAV, bhavcopy_url or DEFAULT_BHAVCOPY_URL),
        }
        self._cache: Dict[tuple, Tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()

    # -- cache
    def _cache_get(self, key):
        with self._cache_lock:
            hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return True, hit[1]
        return False, None

    def _cache_put(self, key, ttl, value):
        if ttl <= 0 or value is None:
            return
        with self._cache_lock:
            self._cache[key] = (time.time() + ttl, value)

    # -- core runner: many (server, tool, args) in parallel, returns decoded results
    def _run_many(self, reqs: List[Tuple[str, str, dict]]) -> List[Any]:
        out: List[Any] = [None] * len(reqs)
        if not self.enabled or not reqs:
            return out
        todo: List[Tuple[int, str, str, dict]] = []
        for i, (srv, tool, args) in enumerate(reqs):
            key = (srv, tool, json.dumps(args, sort_keys=True, default=str))
            hit, val = self._cache_get(key)
            if hit:
                out[i] = val
            else:
                todo.append((i, srv, tool, args))
        if not todo:
            return out

        async def _gather():
            sem = asyncio.Semaphore(MAX_PARALLEL_CALLS)

            async def _one(srv, tool, args):
                async with sem:
                    return _decode(await self._eps[srv].request(tool, args))

            return await asyncio.gather(*[_one(s, t, a) for _, s, t, a in todo],
                                        return_exceptions=True)

        waves = max(1, math.ceil(len(todo) / MAX_PARALLEL_CALLS))
        budget = CONNECT_TIMEOUT + CALL_TIMEOUT * waves + 3
        fut = asyncio.run_coroutine_threadsafe(_gather(), self._loop)
        try:
            results = fut.result(timeout=budget)
        except Exception as e:  # timeout / loop error -> fail-safe
            fut.cancel()
            print(f"[nse-mcp] batch error: {e!r}"[:200])
            return out
        for (i, srv, tool, args), res in zip(todo, results):
            if isinstance(res, BaseException):
                if not isinstance(res, (_Unavailable, _ToolMissing)):
                    print(f"[nse-mcp] {srv}.{tool} failed: {res!r}"[:200])
                continue
            out[i] = res
            self._cache_put((srv, tool, json.dumps(args, sort_keys=True, default=str)),
                            _TTL.get(tool, 0), res)
        return out

    def _call(self, srv: str, tool: str, args: dict) -> Any:
        return self._run_many([(srv, tool, args)])[0]

    # -- public API ---------------------------------------------------------
    def live_quotes(self, symbols: Iterable[str]) -> Dict[str, dict]:
        """NSE live LTP/%chg for many stocks in parallel. {SYMBOL: {ltp, change, change_pct, source}}"""
        syms = list(dict.fromkeys(_clean_symbol(s) for s in symbols if str(s).strip()))
        if not syms:
            return {}
        raws = self._run_many([(SERVER_LIVE, T_STOCK_QUOTE, {"symbol": s}) for s in syms])
        out: Dict[str, dict] = {}
        for s, raw in zip(syms, raws):
            if raw is None:
                continue
            q = _quote_from(s, raw)
            if q:
                out[s] = q
        return out

    def top_movers(self, limit: int = 10, index: Optional[str] = None) -> Any:
        return self._call(SERVER_LIVE, T_MARKET_MOVERS, {"limit": limit, "index": index})

    def live_status(self) -> Any:
        return self._call(SERVER_LIVE, T_DATA_STATUS, {})

    def week52(self, symbol: str) -> Any:
        return self._call(SERVER_BHAV, T_52W, {"symbol": _clean_symbol(symbol)})

    def market_breadth(self, date: Optional[str] = None) -> Any:
        return self._call(SERVER_BHAV, T_BREADTH, {"date": date})

    def corporate_actions(self, symbol: Optional[str] = None) -> Any:
        return self._call(SERVER_BHAV, T_CORP_ACTIONS,
                          {"symbol": _clean_symbol(symbol) if symbol else None})

    def prewarm(self) -> None:
        """Non-blocking: app start par session pehle se khol do -> pehla user call tez."""
        if self.enabled:
            asyncio.run_coroutine_threadsafe(self._prewarm_async(), self._loop)

    async def _prewarm_async(self):
        try:
            await self._eps[SERVER_LIVE].request(T_DATA_STATUS, {})
        except Exception:
            pass

    def status(self) -> dict:
        now = time.time()
        return {
            "enabled": self.enabled,
            "import_error": self.import_error,
            **{
                name: {
                    "connected": ep.connected,
                    "connects": ep.connects,
                    "tools": len(ep.schemas),
                    "cooldown_s": max(0, int(ep.down_until - now)),
                    "last_error": ep.last_error,
                    "url": ep.url,
                }
                for name, ep in self._eps.items()
            },
        }


# ------------------------------------------------------------- module singleton

_DEFAULT: Optional[NseMcpClient] = None
_DEFAULT_LOCK = threading.Lock()


def _env_enabled() -> bool:
    return os.getenv("NSE_MCP_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def get_client() -> NseMcpClient:
    """Process-wide ek hi client (ek hi persistent session poore app me)."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = NseMcpClient(
                    live_url=os.getenv("NSE_MCP_LIVE_URL") or None,
                    bhavcopy_url=os.getenv("NSE_MCP_BHAVCOPY_URL") or None,
                    enabled=_env_enabled(),
                )
    return _DEFAULT


def live_quotes(symbols: Iterable[str]) -> Dict[str, dict]:
    """Module-level shortcut (fast_live_price.py isi ko use karta hai)."""
    return get_client().live_quotes(symbols)


# ------------------------------------------------------------- CLI probe

def _probe(symbol: str) -> None:
    c = NseMcpClient()
    print("status:", json.dumps(c.status(), indent=2, ensure_ascii=False))
    ep_live = c._eps[SERVER_LIVE]
    ep_bhav = c._eps[SERVER_BHAV]
    for ep in (ep_live, ep_bhav):
        try:
            asyncio.run_coroutine_threadsafe(ep.request(T_DATA_STATUS, {}), c._loop).result(15)
        except Exception as e:
            print(f"{ep.name}: connect failed -> {e!r}")
            continue
        print(f"\n== {ep.name}: {len(ep.schemas)} tools ==")
        for name, sch in sorted(ep.schemas.items()):
            print(f"- {name}  args={list((sch or {}).get('properties', {}).keys())}")
    print("\n== raw cm_get_stock_quote ==")
    print(json.dumps(c._call(SERVER_LIVE, T_STOCK_QUOTE, {"symbol": symbol}), indent=2, ensure_ascii=False, default=str))
    print("\n== parsed live_quotes ==")
    print(c.live_quotes([symbol]))
    print("\n== raw get_52_week_high_low ==")
    print(json.dumps(c.week52(symbol), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--probe":
        _probe(sys.argv[2].upper())
    else:
        print("usage: python nse_mcp_client.py --probe RELIANCE")
