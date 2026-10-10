"""
test_nse_mcp_client.py - nse_mcp_client.py ke liye tests (no internet needed)

Ek local MCP server (FastMCP + uvicorn, same process me) NSE ke tool names aur
documented response shape ko mock karta hai. Isse real MCP protocol path
(handshake, session reuse, parallel calls, TTL cache, circuit breaker,
schema-aware args) end-to-end test hota hai - sirf NSE ka network hata diya gaya hai.

Run:  pytest -q test_nse_mcp_client.py      (ya)   python test_nse_mcp_client.py
"""

import json
import socket
import threading
import time
from typing import Optional

import pytest

import nse_mcp_client as nmc

HITS: dict = {}  # tool -> call count (mock server same process me hai)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_mock_server() -> str:
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    port = _free_port()
    srv = FastMCP("mock-nse", host="127.0.0.1", port=port)

    @srv.tool()
    def cm_get_stock_quote(symbol: str) -> str:
        """Live quote for one stock by exact symbol."""
        HITS["cm_get_stock_quote"] = HITS.get("cm_get_stock_quote", 0) + 1
        s = symbol.upper()
        if s == "RELIANCE":  # nested NSE-style shape
            return json.dumps({"info": {"symbol": "RELIANCE"},
                               "priceInfo": {"lastPrice": 1187.5, "change": -3.2, "pChange": -0.27}})
        if s == "TCS":  # flat, string numbers with commas
            return json.dumps({"symbol": "TCS", "last_price": "2,050.60", "change_pct": "-1.10"})
        return json.dumps({"error": "symbol not found", "symbol": s})

    @srv.tool()
    def get_52_week_high_low(symbol: str) -> str:
        """52-week high and low with dates."""
        HITS["get_52_week_high_low"] = HITS.get("get_52_week_high_low", 0) + 1
        return json.dumps({"symbol": symbol.upper(), "last_close": 1187.0, "52w_high": 1611.8,
                           "52w_high_date": "2026-01-05", "52w_low": 1181.7,
                           "52w_low_date": "2026-09-30", "position_in_range_pct": 1.23,
                           "from_52w_high_pct": -26.36, "from_52w_low_pct": 0.45, "trading_days": 245})

    @srv.tool()
    def nse_get_market_movers(limit: int = 10, index: Optional[str] = None) -> str:
        """PRIMARY TOOL for live top gainers and losers."""
        HITS["nse_get_market_movers"] = HITS.get("nse_get_market_movers", 0) + 1
        return json.dumps({"index": index or "ALL", "limit": limit,
                           "gainers": [{"symbol": "ABC", "pChange": 4.2}][:limit], "losers": []})

    @srv.tool()
    def cm_get_data_status() -> str:
        """How fresh the live market data is."""
        return json.dumps({"status": "fresh", "crawl_interval_min": 5})

    @srv.tool()
    def get_market_breadth(date: Optional[str] = None) -> str:
        """Advance and decline numbers for a date."""
        return json.dumps({"date": date or "latest", "advances": 1200, "declines": 800, "unchanged": 90})

    app = srv.streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error", lifespan="on"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}/mcp"


@pytest.fixture(scope="module")
def mock_url():
    return _start_mock_server()


@pytest.fixture()
def client(mock_url):
    c = nmc.NseMcpClient(live_url=mock_url, bhavcopy_url=mock_url, enabled=True)
    yield c
    c.enabled = False  # stop further calls; loop thread is daemon


# ---------------------------------------------------------------- pure helpers

def test_quote_parser_nested_and_flat_shapes():
    q = nmc._quote_from("RELIANCE", {"info": {"symbol": "RELIANCE"},
                                     "priceInfo": {"lastPrice": 1187.5, "change": -3.2, "pChange": -0.27}})
    assert q["ltp"] == 1187.5 and q["change_pct"] == -0.27 and q["source"] == "NSE MCP"
    q2 = nmc._quote_from("TCS", {"symbol": "TCS", "last_price": "2,050.60", "change_pct": "-1.10"})
    assert q2["ltp"] == 2050.60 and q2["change_pct"] == -1.10


def test_quote_parser_rejects_missing_or_bad_price():
    assert nmc._quote_from("X", {"error": "not found"}) is None
    assert nmc._quote_from("X", {"lastPrice": 0}) is None
    assert nmc._quote_from("X", {"lastPrice": "--"}) is None
    assert nmc._quote_from("X", {"lastPrice": True}) is None  # bool is not a price


def test_build_args_keeps_only_schema_props_and_checks_required():
    schema = {"properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}
    assert nmc._build_args(schema, {"symbol": "TCS", "junk": 1, "limit": None}) == {"symbol": "TCS"}
    with pytest.raises(ValueError):
        nmc._build_args(schema, {"limit": 5})
    # schema me properties nahi -> sab non-None args pass
    assert nmc._build_args({}, {"a": 1, "b": None}) == {"a": 1}


# ---------------------------------------------------------------- live MCP path

def test_live_quotes_parallel_parse_and_skip_unknown(client):
    out = client.live_quotes(["reliance", "TCS.NS", "NOSUCH"])
    assert set(out) == {"RELIANCE", "TCS"}
    assert out["RELIANCE"]["ltp"] == 1187.5
    assert out["TCS"]["ltp"] == 2050.6


def test_session_is_reused_across_calls(client):
    for _ in range(3):
        client.live_quotes(["RELIANCE"])
    client.week52("RELIANCE")
    assert client._eps[nmc.SERVER_LIVE].connects == 1
    assert client.status()["live"]["connected"] is True


def test_ttl_cache_avoids_repeat_network_calls(client):
    client.live_quotes(["RELIANCE"])  # warm
    before = HITS.get("cm_get_stock_quote", 0)
    for _ in range(5):
        assert client.live_quotes(["RELIANCE"])["RELIANCE"]["ltp"] == 1187.5
    assert HITS.get("cm_get_stock_quote", 0) == before  # cache hit, koi network call nahi


def test_documented_52w_shape(client):
    d = client.week52("reliance")
    assert d["52w_high"] == 1611.8 and d["52w_low_date"] == "2026-09-30"


def test_schema_aware_optional_args_do_not_break(client):
    movers = client.top_movers(limit=5)              # index=None -> dropped silently
    assert movers["limit"] == 5 and movers["index"] == "ALL"
    assert client.live_status()["status"] == "fresh"
    assert client.market_breadth()["advances"] == 1200  # date=None -> dropped


def test_unknown_tool_returns_none_not_exception(client):
    assert client._call(nmc.SERVER_LIVE, "no_such_tool", {}) is None


def test_disabled_client_never_touches_network():
    c = nmc.NseMcpClient(live_url="http://127.0.0.1:9/mcp", enabled=False)
    assert c.live_quotes(["RELIANCE"]) == {}
    assert c.week52("RELIANCE") is None
    assert c.status()["enabled"] is False


def test_breaker_fails_fast_when_endpoint_down():
    dead = f"http://127.0.0.1:{_free_port()}/mcp"  # koi server nahi
    c = nmc.NseMcpClient(live_url=dead, bhavcopy_url=dead, enabled=True)
    t0 = time.time()
    assert c.live_quotes(["RELIANCE"]) == {}
    first = time.time() - t0
    assert first < nmc.CONNECT_TIMEOUT + 4, f"first failure too slow: {first:.1f}s"
    st = c.status()["live"]
    assert st["cooldown_s"] > 0 and st["connected"] is False
    t1 = time.time()
    assert c.live_quotes(["TCS"]) == {}
    assert time.time() - t1 < 0.5, "breaker cooldown ke andar turant return hona chahiye"


# ---------------------------------------------------------------- integration

def test_fast_live_price_uses_nse_mcp_as_last_fallback(monkeypatch, mock_url):
    """Dhan absent + Yahoo empty -> NSE MCP se RELIANCE/TCS aayein; index Yahoo-style
    fallback me NSE MCP ko nahi jaata."""
    import data_fetch
    import fast_live_price as flp

    monkeypatch.setattr(data_fetch, "fetch_market_watch_quotes", lambda *a, **k: {})
    monkeypatch.setattr(nmc, "_DEFAULT", nmc.NseMcpClient(live_url=mock_url, bhavcopy_url=mock_url))
    try:
        res = flp.get_live_price_hybrid_ultra_fast(("RELIANCE.NS", "TCS", "NIFTY 50"))
    finally:
        nmc._DEFAULT.enabled = False
        nmc._DEFAULT = None
    assert res["RELIANCE.NS"]["source"] == "NSE MCP"
    assert res["RELIANCE.NS"]["ltp"] == 1187.5
    assert res["TCS"]["ltp"] == 2050.6
    assert "NIFTY 50" not in res


def test_breaker_recovers_after_cooldown(monkeypatch, mock_url):
    """NSE thodi der down rahe, phir wapas aaye -> cooldown ke baad client khud recover kare."""
    monkeypatch.setattr(nmc, "BREAKER_SECONDS", 0.5)
    dead = f"http://127.0.0.1:{_free_port()}/mcp"
    c = nmc.NseMcpClient(live_url=dead, bhavcopy_url=dead, enabled=True)
    try:
        assert c.live_quotes(["RELIANCE"]) == {}          # pehli failure -> breaker
        assert c.status()["live"]["cooldown_s"] >= 0
        c._eps[nmc.SERVER_LIVE].url = mock_url            # "NSE wapas up"
        time.sleep(0.6)
        assert c.live_quotes(["RELIANCE"])["RELIANCE"]["ltp"] == 1187.5
        assert c.status()["live"]["connected"] is True
    finally:
        c.enabled = False


def test_dhan_equity_resolution_regression(monkeypatch):
    """Regression: fast_live_price ka Dhan EQ path pehle load_dhan_master_fast ko import
    nahi karta tha (NameError -> NSE stocks kabhi Dhan se nahi aate the). Ab resolve hona chahiye."""
    import dhan_api_helper as dah
    import fast_live_price as flp

    monkeypatch.setattr(dah, "load_dhan_master_fast",
                        lambda: {"RELIANCE": {"security_id": "2885", "segment": "NSE_EQ"}})

    class _FakeDhan:
        def quote_data(self, securities):
            ids = securities.get("NSE_EQ", [])
            return {"data": {"NSE_EQ": {str(i): {"last_price": 1190.0, "previous_close_price": 1180.0}
                                        for i in ids}}}

    monkeypatch.setattr(flp, "_dhan_client", lambda cid, tok: _FakeDhan())
    out = flp._dhan_quote_batch("cid-test", "tok-test", (), ("RELIANCE",))
    assert out["RELIANCE"]["ltp"] == 1190.0
    assert out["RELIANCE"]["source"] == "Dhan"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
