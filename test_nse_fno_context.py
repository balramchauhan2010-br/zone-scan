"""
test_nse_fno_context.py - F&O context panel ke tests (no internet)

  * pure logic: session fraction, breadth, movers, time-adjusted volume spikes,
    OI top-10 + verdict, zone map, market mood, index movers, corporate actions
  * NSE MCP parsing against the local mock server (bulk equities, grouped gainers,
    volume baseline, corporate actions)
  * Streamlit render smoke test (AppTest) - panel exception ke bina render ho

Run: pytest -q test_nse_fno_context.py
"""

import datetime as dt

import pandas as pd
import pytest

import nse_fno_context as nfc
import nse_mcp_client as nmc
from test_nse_mcp_client import _start_mock_server  # reuse the same local NSE MCP mock

IST = "Asia/Kolkata"


@pytest.fixture(scope="module")
def mock_url():
    return _start_mock_server()


@pytest.fixture()
def client(mock_url):
    c = nmc.NseMcpClient(live_url=mock_url, bhavcopy_url=mock_url, enabled=True)
    yield c
    c.enabled = False


# ------------------------------------------------------------------ pure logic

def test_clean_fno_drops_indices_and_dupes():
    out = nfc.clean_fno(["RELIANCE.NS", "reliance", "NIFTY", "BANKNIFTY", "TCS", "", "NIFTY 50"])
    assert out == ("RELIANCE", "TCS")


def test_session_fraction_by_phase():
    mon_1015 = pd.Timestamp("2026-10-12 10:15", tz=IST)   # Monday, trading day
    assert nfc.session_fraction(mon_1015) == pytest.approx(60 / 375, rel=1e-6)
    assert nfc.session_fraction(pd.Timestamp("2026-10-12 08:30", tz=IST)) is None   # pre-market
    assert nfc.session_fraction(pd.Timestamp("2026-10-12 16:00", tz=IST)) == 1.0    # post-market
    assert nfc.session_fraction(pd.Timestamp("2026-10-10 11:00", tz=IST)) == 1.0    # Saturday = closed


def _live(rows):
    return pd.DataFrame(rows, columns=nfc.COLS_LIVE)


def test_breadth_and_mood():
    df = _live([
        {"Symbol": "A", "LTP": 1, "Chg %": 1.2, "Volume": 1},
        {"Symbol": "B", "LTP": 1, "Chg %": 0.8, "Volume": 1},
        {"Symbol": "C", "LTP": 1, "Chg %": 0.9, "Volume": 1},
        {"Symbol": "D", "LTP": 1, "Chg %": -0.6, "Volume": 1},
    ])
    b = nfc.breadth(df)
    assert (b["up"], b["down"], b["flat"], b["total"]) == (3, 1, 0, 4)
    assert b["pct_up"] == 75.0 and b["mood"] == "Bullish 🟢"
    assert nfc.breadth(_live([]))["mood"] == "—"


def test_movers_sorted_and_n_limited():
    df = _live([{"Symbol": s, "LTP": 1, "Chg %": c, "Volume": 1}
                for s, c in [("A", 3.0), ("B", -4.0), ("C", 1.0), ("D", -0.5)]])
    assert list(nfc.movers(df, "gain", 2)["Symbol"]) == ["A", "C"]
    assert list(nfc.movers(df, "loss", 2)["Symbol"]) == ["B", "D"]


def test_time_adjusted_spike_ratio():
    df = _live([
        {"Symbol": "HOT", "LTP": 1, "Chg %": 2.0, "Volume": 1_200_000},   # expect 1M*0.5=500k -> 2.4x
        {"Symbol": "NORM", "LTP": 1, "Chg %": 0.1, "Volume": 600_000},    # 1.2x -> not a spike
    ])
    rf = nfc.ratio_frame(df, {"HOT": 1_000_000, "NORM": 1_000_000}, frac=0.5)
    sp = nfc.spikes(rf)
    assert list(sp["Symbol"]) == ["HOT"]
    assert sp.iloc[0]["Vol x (time-adj)"] == pytest.approx(2.4, rel=1e-6)


def test_no_spikes_in_pre_market():
    df = _live([{"Symbol": "HOT", "LTP": 1, "Chg %": 2.0, "Volume": 9_999_999}])
    rf = nfc.ratio_frame(df, {"HOT": 1_000_000}, frac=None)
    assert nfc.spikes(rf).empty


def test_zone_map_keeps_nearest_zone():
    z = pd.DataFrame([
        {"Ticker": "RELIANCE.NS", "Direction": "DEMAND (Buy Zone)", "Distance %": -2.5},
        {"Ticker": "RELIANCE.NS", "Direction": "SUPPLY (Sell Zone)", "Distance %": 0.8},
        {"Ticker": "TCS.NS", "Direction": "SUPPLY (Sell Zone)", "Distance %": 4.0},
    ])
    m = nfc.zone_map(z)
    assert m["RELIANCE"] == "Supply · 0.8% door"
    assert m["TCS"].startswith("Supply")


def test_verdict_combines_oi_price_volume_zone():
    v = nfc.verdict("long_buildup", 1.2, 2.5, "Demand · 0.5% door")
    assert "Fresh long build-up" in v and "2.5x" in v and "Demand" in v
    assert "divergence" in nfc.verdict("long_buildup", -0.4, None)
    assert "squeeze" in nfc.verdict("short_buildup", 0.7, 1.0)
    assert nfc.verdict("neutral", 1.0, 1.0) == "—"


def test_oi_top10_increase_and_decrease_with_live_context():
    fo_map = {
        "THIN": {"fut_oi_chg_pct": 90.0, "fut_oi_chg": 900, "fut_oi": 5e3, "chg_pct": 3.0,
                 "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"},  # OI tiny -> skip
        "AAA": {"fut_oi_chg_pct": 12.0, "fut_oi_chg": 900, "fut_oi": 8e5, "chg_pct": 2.0,
                "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"},
        "BBB": {"fut_oi_chg_pct": 5.0, "fut_oi_chg": 300, "fut_oi": 4e5, "chg_pct": -1.5,
                "oi_signal": "Short Buildup 🔴", "oi_signal_en": "short_buildup"},
        "CCC": {"fut_oi_chg_pct": -7.0, "fut_oi_chg": -200, "fut_oi": 2e5, "chg_pct": 1.0,
                "oi_signal": "Short Covering 🟢", "oi_signal_en": "short_covering"},
        "NOTFNO": {"fut_oi_chg_pct": 50.0, "fut_oi": 1e5, "chg_pct": 1.0,
                   "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"},
    }
    live = _live([
        {"Symbol": "AAA", "LTP": 1, "Chg %": 1.5, "Volume": 3_000_000},
        {"Symbol": "BBB", "LTP": 1, "Chg %": -0.9, "Volume": 100_000},
        {"Symbol": "CCC", "LTP": 1, "Chg %": 0.5, "Volume": 100_000},
    ])
    rf = nfc.ratio_frame(live, {"AAA": 1_000_000, "BBB": 1_000_000, "CCC": 1_000_000}, frac=0.5)
    fno = ("AAA", "BBB", "CCC", "THIN")
    inc = nfc.oi_table(fo_map, rf, {"AAA": "Demand · 1.0% door"}, fno, "inc")
    assert "THIN" not in set(inc["Symbol"])  # MIN_FUT_OI filter
    dec = nfc.oi_table(fo_map, rf, {}, fno, "dec")
    assert list(inc["Symbol"]) == ["AAA", "BBB"]          # NOTFNO excluded, sorted desc
    assert list(dec["Symbol"]) == ["CCC"]                  # only negative OI change
    top = inc.iloc[0]
    assert top["Vol x (time-adj)"] == pytest.approx(6.0)
    assert "Fresh long build-up" in top["Read"] and "Demand" in top["Read"]
    assert "short build-up" in inc.iloc[1]["Read"].lower()
    assert "Short covering" in dec.iloc[0]["Read"]


def test_market_mood_balances_breadth_and_oi():
    long3 = pd.DataFrame({"OI Signal": ["Long Buildup 🟢"] * 3})   # OI-increase table
    short3 = pd.DataFrame({"OI Signal": ["Short Buildup 🔴"] * 3})  # OI-decrease table
    one_long = pd.DataFrame({"OI Signal": ["Long Buildup 🟢"]})
    mood, reason = nfc.market_mood({"mood": "Bullish 🟢"}, long3, short3, 4)
    assert mood == "Bullish 🟢"
    assert "long build-up 3 vs short build-up 3" in reason
    assert nfc.market_mood({"mood": "Bearish 🔴"}, one_long, short3, 0)[0] == "Bearish 🔴"
    assert nfc.market_mood({"mood": "Bullish 🟢"}, one_long, short3, 0)[0] == "Mixed ⚪"


def test_index_movers_only_fno_stocks():
    groups = {"NIFTY 50": [
        {"symbol": "RELIANCE", "pChange": 2.0, "lastPrice": 1200.0},
        {"symbol": "ABCNOTFNO", "pChange": 9.0, "lastPrice": 50.0},
        {"symbol": "TCS", "pChange": 1.0, "lastPrice": 2000.0},
    ]}
    t = nfc.index_movers_table(groups, ("RELIANCE", "TCS"), "gain", n=5)
    assert list(t["Symbol"]) == ["RELIANCE", "TCS"]
    assert set(t["Index"]) == {"NIFTY 50"}


def test_corporate_actions_window_and_bonus_warning():
    today = dt.date(2026, 10, 10)
    raw = {"symbol": "RELIANCE", "actions": [
        {"purpose": "BONUS 1:1", "exDate": "13-Oct-2026"},
        {"purpose": "DIVIDEND - RS 5", "exDate": "01-Jan-2020"},   # out of window
    ]}
    df = nfc.corp_actions_table({"RELIANCE": raw}, today=today)
    assert len(df) == 1
    assert df.iloc[0]["Ex-date"] == "2026-10-13" and df.iloc[0]["Days to ex"] == 3
    assert "Bonus" in df.iloc[0]["Note"]


# ------------------------------------------------------------------ MCP parsing

def test_extract_records_and_groups_helpers():
    recs = nmc.extract_records({"data": [{"symbol": "A"}, {"symbol": "B"}, {"x": 1}]})
    assert [r["symbol"] for r in recs] == ["A", "B"]
    g = nmc.extract_groups({"NIFTY 50": [{"symbol": "A"}], "NIFTY BANK": [{"symbol": "B"}]})
    assert set(g) == {"NIFTY 50", "NIFTY BANK"}
    g2 = nmc.extract_groups([{"symbol": "A", "index": "NIFTY"}, {"symbol": "B", "index": "BANKNIFTY"}])
    assert set(g2) == {"NIFTY", "BANKNIFTY"}


def test_quote_volume_and_prev_close_derived_change():
    q = nmc._quote_from("X", {"lastPrice": 110.0, "previousClose": 100.0, "totalTradedVolume": "1,20,000"})
    assert q["change_pct"] == pytest.approx(10.0)
    assert q["volume"] == 120000.0 and q["prev_close"] == 100.0


def test_live_snapshot_bulk_then_per_symbol_fallback(client):
    snap = client.live_snapshot(["RELIANCE", "INFY", "TCS"])
    assert snap["RELIANCE"]["volume"] == 3000000        # bulk tool se
    assert snap["INFY"]["ltp"] == 1500.0
    assert snap["TCS"]["ltp"] == 2050.6                 # bulk me nahi -> per-symbol fallback
    assert "ZZZ" not in snap


def test_avg_volumes_batch_and_grouped_movers(client):
    base = client.avg_volumes(["RELIANCE", "TCS"], days=20)
    assert base == {"RELIANCE": 1000000.0, "TCS": 1000000.0}
    gainers = client.index_movers("gainers")
    assert "NIFTY 50" in gainers and "NIFTY BANK" in gainers


def test_corporate_actions_many(client):
    raw = client.corporate_actions_many(["RELIANCE", "TCS"])
    assert "RELIANCE" in raw and "TCS" in raw


# ------------------------------------------------------------------ render smoke

def test_render_panel_smoke(monkeypatch, mock_url):
    """Streamlit script ke andar panel render - koi exception nahi, sections dikhte hain."""
    from streamlit.testing.v1 import AppTest

    fno = ("RELIANCE", "TCS", "INFY")
    monkeypatch.setattr(nmc, "_DEFAULT", nmc.NseMcpClient(live_url=mock_url, bhavcopy_url=mock_url))
    monkeypatch.setattr(nfc, "fetch_live", lambda f: {
        "RELIANCE": {"ltp": 1200.0, "change_pct": 2.0, "volume": 3_000_000},
        "TCS": {"ltp": 2050.6, "change_pct": -1.1, "volume": 900_000},
        "INFY": {"ltp": 1500.0, "change_pct": 0.3, "volume": 500_000},
    })
    monkeypatch.setattr(nfc, "fetch_baselines", lambda f: {"RELIANCE": 1e6, "TCS": 1e6, "INFY": 1e6})
    monkeypatch.setattr(nfc, "session_fraction", lambda now=None: 0.5)
    monkeypatch.setattr(nfc, "_fo_eod", lambda: {"date": "2026-10-09", "map": {
        "RELIANCE": {"fut_oi_chg_pct": 6.0, "fut_oi_chg": 1000, "fut_oi": 5e5, "chg_pct": 1.8,
                     "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"},
        "TCS": {"fut_oi_chg_pct": -4.0, "fut_oi_chg": -300, "fut_oi": 2e5, "chg_pct": -1.0,
                "oi_signal": "Long Unwinding 🔴", "oi_signal_en": "long_unwinding"},
    }})
    monkeypatch.setattr(nfc, "fetch_index_groups", lambda side: {})
    monkeypatch.setattr(nfc, "fetch_corp", lambda syms: {})

    script = f'''
import pandas as pd
import nse_fno_context as nfc
nfc.render_nse_fno_panel(pd.DataFrame(), {fno!r})
'''
    at = AppTest.from_string(script)
    at.run(timeout=60)
    assert not at.exception, [e.value for e in at.exception]
    headers = [h.value for h in at.header]
    assert any("Live Market Context" in h for h in headers), headers
    assert len(at.dataframe) >= 2   # gainers/losers + OI tables


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
