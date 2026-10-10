"""
test_live_oi.py - live futures OI ke tests (no internet, fakes ke saath)

  * parsers: _first_num nested lookup, Dhan quote parse, NSE quote-derivative parse
  * expiry pick: front-month = sabse nazdeeki expiry (>= aaj)
  * Dhan batch chunking with a fake client (500 ids per call)
  * NSE fallback: fixture payload, fail-stop after 3 lagatar failures
  * orchestrator: Dhan > NSE fallback > (empty -> EOD) with injected fakes
  * nse_fno_context.oi_table live math + EOD fallback + sanity guard + oi_priority

Run: pytest -q test_live_oi.py
"""

import datetime as dt

import pandas as pd
import pytest

import live_oi as lo
import nse_fno_context as nfc

TODAY = dt.date(2026, 10, 12)


# ----------------------------------------------------------------- parsers

def test_first_num_handles_nested_and_strings():
    obj = {"data": {"quote": {"open_interest": "1,234,500", "oi": None}}}
    assert lo._first_num(obj, ("oi", "open_interest")) == 1234500.0
    assert lo._first_num({"oi": "NA"}, ("oi",)) is None
    assert lo._first_num({"oi": True}, ("oi",)) is None  # bool is not a number
    assert lo._first_num({}, ("oi",)) is None


def test_pick_front_month_nearest_future_expiry():
    rows = [
        ("RELIANCE", dt.date(2026, 9, 29), "1"),   # expired -> skip
        ("RELIANCE", dt.date(2026, 10, 27), "2"),  # front month
        ("RELIANCE", dt.date(2026, 11, 24), "3"),  # far month
        ("TCS", dt.date(2026, 11, 24), "4"),
        ("TCS", dt.date(2026, 10, 27), ""),        # empty id -> skip
        ("INFY", None, "5"),                       # no expiry -> skip
    ]
    got = lo.pick_front_month(rows, TODAY)
    assert got == {
        "RELIANCE": {"security_id": "2", "expiry": "2026-10-27"},
        "TCS": {"security_id": "4", "expiry": "2026-11-24"},
    }


def test_parse_dhan_quotes_maps_ids_and_skips_missing_oi():
    resp = {"status": "success", "data": {"NSE_FNO": {
        "101": {"last_price": 2950.5, "oi": 4_000_000, "volume": 12345},
        "102": {"ltp": "1,410", "open_interest": "900000"},
        "103": {"last_price": 88.0},                 # no OI -> skipped
        "999": {"oi": 1},                            # unknown id -> skipped
    }}}
    out = lo.parse_dhan_quotes(resp, {"101": "RELIANCE", "102": "TCS", "103": "INFY"})
    assert out["RELIANCE"] == {"oi": 4_000_000.0, "ltp": 2950.5, "volume": 12345.0, "source": "Dhan"}
    assert out["TCS"]["oi"] == 900000.0 and out["TCS"]["ltp"] == 1410.0
    assert "INFY" not in out and len(out) == 2


def test_parse_dhan_quotes_bad_payload_is_empty():
    assert lo.parse_dhan_quotes({}, {}) == {}
    assert lo.parse_dhan_quotes({"data": "oops"}, {}) == {}
    assert lo.parse_dhan_quotes({"data": {"NSE_EQ": {}}}, {}) == {}


def _nse_payload():
    return {"stocks": [
        {"metadata": {"instrumentType": "Stock Futures", "expiryDate": "27-Oct-2026"},
         "marketDeptOrderBook": {"tradeInfo": {}}, "openInterest": 5_200_000,
         "lastPrice": 2960.0, "totalTradedVolume": 8_000_000},
        {"metadata": {"instrumentType": "Stock Futures", "expiryDate": "24-Nov-2026"},
         "openInterest": 9_999_999, "lastPrice": 2970.0},
        {"metadata": {"instrumentType": "Stock Futures", "expiryDate": "29-Sep-2026"},
         "openInterest": 1, "lastPrice": 1.0},  # expired
        {"metadata": {"instrumentType": "Stock Options", "expiryDate": "20-Oct-2026",
                      "optionType": "Call"}, "openInterest": 77},
    ]}


def test_parse_nse_derivative_picks_nearest_stock_future():
    got = lo.parse_nse_derivative(_nse_payload(), TODAY)
    assert got == {"oi": 5_200_000.0, "ltp": 2960.0, "volume": 8_000_000.0,
                   "expiry": "2026-10-27", "source": "NSE"}


def test_parse_nse_derivative_no_future_returns_none():
    assert lo.parse_nse_derivative({"stocks": []}, TODAY) is None
    assert lo.parse_nse_derivative({"stocks": [{"metadata": {"instrumentType": "Stock Options"}}]}, TODAY) is None
    assert lo.parse_nse_derivative("not a dict", TODAY) is None


# ----------------------------------------------------------------- Dhan chunking

class FakeDhan:
    def __init__(self, fail_on_call=None):
        self.calls = []
        self.fail_on_call = fail_on_call

    def quote_data(self, securities):
        self.calls.append(securities)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("rate limited")
        ids = securities["NSE_FNO"]
        return {"status": "success", "data": {"NSE_FNO": {
            str(i): {"last_price": 100.0, "oi": 1000 + i, "volume": 1} for i in ids}}}


def _big_fut_map(n):
    return {f"S{i}": {"security_id": str(i + 1000), "expiry": "2026-10-27"} for i in range(n)}


def test_dhan_live_oi_chunks_500_per_call():
    fm = _big_fut_map(1201)
    client = FakeDhan()
    out = lo.dhan_live_oi(client, fm, fm.keys())
    assert len(client.calls) == 3                         # 500 + 500 + 201
    sizes = [len(c["NSE_FNO"]) for c in client.calls]
    assert sizes == [500, 500, 201]
    assert len(out) == 1201
    assert out["S0"]["oi"] == 1000 + 1000 and out["S0"]["source"] == "Dhan"  # sid = i + 1000
    assert out["S1200"]["oi"] == 1000 + 2200


def test_dhan_live_oi_only_requested_symbols():
    fm = _big_fut_map(10)
    client = FakeDhan()
    out = lo.dhan_live_oi(client, fm, ["S3", "S7", "NOT_IN_MAP"])
    assert len(client.calls) == 1
    assert sorted(client.calls[0]["NSE_FNO"]) == [1003, 1007]
    assert set(out) == {"S3", "S7"}


def test_dhan_live_oi_partial_on_error_keeps_first_batch():
    fm = _big_fut_map(600)
    client = FakeDhan(fail_on_call=2)
    out = lo.dhan_live_oi(client, fm, fm.keys())
    assert len(client.calls) == 2
    assert len(out) == 500                                # first batch survives


def test_dhan_live_oi_empty_map_makes_no_call():
    client = FakeDhan()
    assert lo.dhan_live_oi(client, {}, ["X"]) == {}
    assert client.calls == []


# ----------------------------------------------------------------- NSE fallback

class FakeResp:
    def __init__(self, payload=None, fail=False):
        self._p, self._fail = payload, fail

    def raise_for_status(self):
        if self._fail:
            raise RuntimeError("403")

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, fail_all=False, payload=None):
        self.headers = {}
        self.urls = []
        self.fail_all = fail_all
        self.payload = payload if payload is not None else _nse_payload()

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return FakeResp(fail=self.fail_all, payload=self.payload)


@pytest.fixture()
def fast_nse(monkeypatch):
    monkeypatch.setattr(lo, "NSE_SPACING", 0.0)
    monkeypatch.setattr(lo.time, "sleep", lambda s: None)


def test_nse_live_oi_parses_fixture(fast_nse):
    sess = FakeSession()
    out = lo.nse_live_oi(["RELIANCE", "TCS"], TODAY, session=sess)
    assert set(out) == {"RELIANCE", "TCS"}
    assert out["RELIANCE"]["oi"] == 5_200_000.0
    assert all("quote-derivative?symbol=" in u for u in sess.urls)


def test_nse_live_oi_fail_stop_after_three(fast_nse):
    sess = FakeSession(fail_all=True)
    out = lo.nse_live_oi([f"S{i}" for i in range(30)], TODAY, session=sess)
    assert out == {}
    assert len(sess.urls) == lo.NSE_FAIL_STOP == 3        # stops, does not hammer NSE


def test_nse_live_oi_caps_at_max(fast_nse):
    sess = FakeSession()
    lo.nse_live_oi([f"S{i}" for i in range(50)], TODAY, max_n=30, session=sess)
    assert len(sess.urls) == 30


# ----------------------------------------------------------------- orchestrator

@pytest.fixture()
def no_dhan(monkeypatch):
    monkeypatch.setattr(lo, "_resolve_dhan_client", lambda: None)


def test_orchestrator_dhan_only_no_nse_call(no_dhan):
    fm = _big_fut_map(5)
    client = FakeDhan()
    called = []
    out, status = lo.get_live_fut_oi(
        [f"S{i}" for i in range(5)], ["S0", "S1"], today=TODAY,
        client=client, fut_map=fm, nse_fetch=lambda syms: called.append(syms) or {})
    assert len(out) == 5 and all(v["source"] == "Dhan" for v in out.values())
    assert called == []                                   # Dhan covered priority -> no NSE
    assert "Dhan 5/5" in status


def test_orchestrator_nse_fallback_for_missing_priority_only(no_dhan):
    fno = ["A", "B", "C"]
    called = []

    def fake_nse(syms):
        called.append(list(syms))
        return {s: {"oi": 1e6, "source": "NSE"} for s in syms}

    out, status = lo.get_live_fut_oi(fno, ["A", "B", "C"], today=TODAY,
                                     client=None, fut_map={}, nse_fetch=fake_nse)
    assert called == [["A", "B", "C"]]
    assert {v["source"] for v in out.values()} == {"NSE"}
    assert "NSE fallback 3/3" in status


def test_orchestrator_mixed_dhan_then_nse_for_gap(no_dhan):
    fm = {"A": {"security_id": "1000", "expiry": "x"}}     # Dhan knows only A
    client = FakeDhan()
    called = []

    def fake_nse(syms):
        called.append(list(syms))
        return {s: {"oi": 2e6, "source": "NSE"} for s in syms}

    out, _ = lo.get_live_fut_oi(["A", "B"], ["A", "B"], today=TODAY,
                                client=client, fut_map=fm, nse_fetch=fake_nse)
    assert out["A"]["source"] == "Dhan" and out["B"]["source"] == "NSE"
    assert called == [["B"]]


def test_orchestrator_nothing_available_returns_empty(no_dhan):
    out, status = lo.get_live_fut_oi(["A"], ["A"], today=TODAY, client=None, fut_map={},
                                     nse_fetch=lambda syms: {})
    assert out == {}
    assert "EOD dikh raha" in status


# ----------------------------------------------------------------- oi_table live math

def _fo(**kw):
    base = {"fut_oi": 1_000_000.0, "fut_oi_chg": 50_000.0, "fut_oi_chg_pct": 5.0,
            "chg_pct": 0.4, "oi_signal": "Long Buildup 🟢", "oi_signal_en": "long_buildup"}
    base.update(kw)
    return base


def _ratio(**chg):
    rows = [{"Symbol": s, "Chg %": c, "Vol x (time-adj)": 3.0} for s, c in chg.items()]
    return pd.DataFrame(rows, columns=["Symbol", "Chg %", "Vol x (time-adj)"])


def test_oi_table_uses_live_oi_against_prev_close_baseline():
    fo_map = {"RELIANCE": _fo()}
    live = {"RELIANCE": {"oi": 1_200_000.0, "ltp": 2960.0, "source": "Dhan"}}
    df = nfc.oi_table(fo_map, _ratio(RELIANCE=1.8), {}, ["RELIANCE"], "inc", live)
    row = df.iloc[0]
    assert row["OI Source"] == "Dhan"
    assert row["Fut OI Δ %"] == pytest.approx(20.0)        # (1.2M - 1.0M) / 1.0M
    assert row["Fut OI Δ (contracts)"] == 200_000
    assert row["Fut OI (lakh)"] == pytest.approx(12.0)
    assert row["Price %"] == pytest.approx(1.8)            # live price, not EOD
    assert row["OI Signal"] == "Long Buildup 🟢"           # OI up + price up


def test_oi_table_live_signal_recomputed_from_live_price_and_oi():
    # EOD said long buildup, but live the price is falling and OI is up -> short buildup
    fo_map = {"TCS": _fo()}
    live = {"TCS": {"oi": 1_100_000.0, "source": "NSE"}}
    df = nfc.oi_table(fo_map, _ratio(TCS=-1.0), {}, ["TCS"], "inc", live)
    assert df.iloc[0]["OI Signal"] == "Short Buildup 🔴"
    assert df.iloc[0]["OI Source"] == "NSE"


def test_oi_table_falls_back_to_eod_when_live_ratio_is_insane():
    fo_map = {"ROLL": _fo()}
    live = {"ROLL": {"oi": 9_000_000.0, "source": "Dhan"}}  # 9x: expiry mismatch -> EOD
    df = nfc.oi_table(fo_map, _ratio(ROLL=0.5), {}, ["ROLL"], "inc", live)
    assert df.iloc[0]["OI Source"] == "EOD"
    assert df.iloc[0]["Fut OI Δ %"] == pytest.approx(5.0)
    assert df.iloc[0]["Price %"] == pytest.approx(0.4)     # EOD price for EOD row


def test_oi_table_no_live_is_pure_eod_and_dec_direction():
    fo_map = {"ZED": _fo(fut_oi_chg_pct=-8.0, fut_oi_chg=-80_000.0, chg_pct=1.2,
                         oi_signal="Short Covering 🟢", oi_signal_en="short_covering")}
    df_dec = nfc.oi_table(fo_map, _ratio(ZED=1.2), {}, ["ZED"], "dec", None)
    assert list(df_dec["Symbol"]) == ["ZED"]
    assert df_dec.iloc[0]["OI Source"] == "EOD"
    assert nfc.oi_table(fo_map, _ratio(ZED=1.2), {}, ["ZED"], "inc", None).empty


def test_oi_table_live_only_for_fno_symbols():
    fo_map = {"ONLYEQ": _fo()}
    live = {"ONLYEQ": {"oi": 1_500_000.0, "source": "Dhan"}}
    assert nfc.oi_table(fo_map, _ratio(ONLYEQ=1.0), {}, [], "inc", live).empty


def test_oi_table_live_row_dropped_when_live_oi_is_below_floor():
    fo_map = {"THINLIVE": _fo(fut_oi=50_000.0)}           # EOD OI itself is thin
    live = {"THINLIVE": {"oi": 60_000.0, "source": "Dhan"}}
    assert nfc.oi_table(fo_map, _ratio(THINLIVE=2.0), {}, ["THINLIVE"], "inc", live).empty


# ----------------------------------------------------------------- oi_priority

def test_oi_priority_zone_first_then_top_movers_fno_only():
    fo_map = {
        "AAA": _fo(fut_oi_chg_pct=3.0),
        "BBB": _fo(fut_oi_chg_pct=-9.0),
        "CCC": _fo(fut_oi_chg_pct=1.0),
        "NOTFNO": _fo(fut_oi_chg_pct=50.0),                # not in fno -> excluded
        "THIN": _fo(fut_oi_chg_pct=40.0, fut_oi=10_000.0), # below floor -> excluded
    }
    prio = nfc.oi_priority(fo_map, {"CCC": "zone"}, ["AAA", "BBB", "CCC", "THIN"], n_movers=2)
    assert prio[0] == "CCC"                               # zone symbol first
    assert "BBB" in prio and "AAA" in prio                # top-2 by |OI change %|
    assert "NOTFNO" not in prio and "THIN" not in prio
    assert len(prio) == len(set(prio))                    # no duplicates


def test_get_live_fut_oi_status_and_priority_from_oi_priority(no_dhan):
    fo_map = {"X": _fo(fut_oi_chg_pct=10.0), "Y": _fo(fut_oi_chg_pct=-2.0)}
    prio = nfc.oi_priority(fo_map, {}, ["X", "Y"])
    assert prio == ("X", "Y")
    out, status = lo.get_live_fut_oi(["X", "Y"], prio, today=TODAY, client=None, fut_map={},
                                     nse_fetch=lambda syms: {"X": {"oi": 1.0, "source": "NSE"}})
    assert set(out) == {"X"} and "NSE fallback 1/2" in status
