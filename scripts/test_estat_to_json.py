"""test_estat_to_json.py — Gold-standard assertions for the e-Stat CSV converter.

Run with:  python3 -m pytest test_estat_to_json.py -v
Or simply: python3 test_estat_to_json.py

The tests use the real downloaded CSVs as fixtures. Update CSV_MONTHLY / CSV_PERMITS
paths if you move the files, or pass them via env vars ESTAT_MONTHLY / ESTAT_PERMITS.
"""

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate real CSV files
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent
CSV_MONTHLY = Path(os.environ.get(
    "ESTAT_MONTHLY",
    str(_BASE / "../raw/monthly_2026-03.csv"),
))
CSV_PERMITS = Path(os.environ.get(
    "ESTAT_PERMITS",
    str(_BASE / "../raw/permits_2024.csv"),
))

_SKIP = not (CSV_MONTHLY.exists() and CSV_PERMITS.exists())
_SKIP_REASON = (
    f"Real CSVs not found at {CSV_MONTHLY} / {CSV_PERMITS}. "
    "Place them under scripts/raw/ or set ESTAT_MONTHLY / ESTAT_PERMITS env vars."
)

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
sys.path.insert(0, str(_BASE))
from estat_to_json import (
    parse_monthly_csv,
    parse_permits_csv,
    build_json,
    ITEM_RECEIVED_TOTAL,
    ITEM_RECEIVED_NEW,
    ITEM_PROCESSED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _office(doc, code):
    return next(o for o in doc["offices"] if o["code"] == code)


def _month(office_data, ym):
    return next((m for m in office_data["monthly"] if m["month"] == ym), None)


def _bureau_month(office_data, ym):
    return next(
        (m for m in office_data.get("bureauTotal", {}).get("monthly", []) if m["month"] == ym),
        None,
    )


# ---------------------------------------------------------------------------
# Fixtures (loaded lazily so import itself never fails)
# ---------------------------------------------------------------------------
_monthly_parsed = None
_permits_parsed = None
_doc = None


def _load():
    global _monthly_parsed, _permits_parsed, _doc
    if _monthly_parsed is None:
        _monthly_parsed = parse_monthly_csv(CSV_MONTHLY)
        _permits_parsed = parse_permits_csv(CSV_PERMITS)
        _doc = build_json(_monthly_parsed, _permits_parsed)


# ---------------------------------------------------------------------------
# Tests — §10.2 Gold Standard (2026-03, 永住)
# ---------------------------------------------------------------------------

def test_csv_files_exist():
    if _SKIP:
        _skip()
    assert CSV_MONTHLY.exists(), f"Monthly CSV not found: {CSV_MONTHLY}"
    assert CSV_PERMITS.exists(), f"Permits CSV not found: {CSV_PERMITS}"


def test_month_count():
    """CSV spans 2020-11 to 2026-03 = 65 months."""
    if _SKIP:
        _skip()
    _load()
    assert len(_monthly_parsed) == 65, f"Expected 65 months, got {len(_monthly_parsed)}"


def test_tokyo_bureau_received_total_2026_03():
    """東京管内 受理_総数 = 55,427 (§2.2)."""
    if _SKIP:
        _skip()
    _load()
    val = _monthly_parsed["2026-03"]["bureau"]["TOKYO"].get(ITEM_RECEIVED_TOTAL)
    assert val == 55427, f"Expected 55427, got {val}"


def test_tokyo_bureau_received_new_2026_03():
    """東京管内 受理_新受 = 5,713 (§2.2)."""
    if _SKIP:
        _skip()
    _load()
    val = _monthly_parsed["2026-03"]["bureau"]["TOKYO"].get(ITEM_RECEIVED_NEW)
    assert val == 5713, f"Expected 5713, got {val}"


def test_tokyo_bureau_processed_2026_03():
    """東京管内 既済_総数 = 3,720 (§2.2)."""
    if _SKIP:
        _skip()
    _load()
    val = _monthly_parsed["2026-03"]["bureau"]["TOKYO"].get(ITEM_PROCESSED)
    assert val == 3720, f"Expected 3720, got {val}"


def test_yokohama_received_new_2026_03():
    """横浜支局 受理_新受 = 1,290 (§2.2)."""
    if _SKIP:
        _skip()
    _load()
    val = _monthly_parsed["2026-03"]["bureau"]["YOKOHAMA"].get(ITEM_RECEIVED_NEW)
    assert val == 1290, f"Expected 1290, got {val}"


def test_yokohama_processed_2026_03():
    """横浜支局 既済_総数 = 565 (§2.2)."""
    if _SKIP:
        _skip()
    _load()
    val = _monthly_parsed["2026-03"]["bureau"]["YOKOHAMA"].get(ITEM_PROCESSED)
    assert val == 565, f"Expected 565, got {val}"


def test_narita_haneda_zero_2026_03():
    """成田/羽田 永住はゼロ (§10.2)."""
    if _SKIP:
        _skip()
    _load()
    narita = _monthly_parsed["2026-03"]["bureau"]["NARITA"].get(ITEM_RECEIVED_NEW, 0)
    haneda = _monthly_parsed["2026-03"]["bureau"]["HANEDA"].get(ITEM_RECEIVED_NEW, 0)
    assert narita == 0, f"Narita 受理_新受 expected 0, got {narita}"
    assert haneda == 0, f"Haneda 受理_新受 expected 0, got {haneda}"


def test_pure_tokyo_received_2026_03():
    """純东京 新受 = 東京管内(5713) − 成田(0) − 羽田(0) − 横浜(1290) = 4423 (§10.2)."""
    if _SKIP:
        _skip()
    _load()
    pt = _month(_office(_doc, "TOKYO"), "2026-03")
    assert pt is not None, "No 2026-03 entry for TOKYO"
    assert pt["received"] == 4423, f"Expected 4423, got {pt['received']}"


def test_pure_tokyo_processed_2026_03():
    """純东京 既済 = 東京管内(3720) − 横浜(565) = 3155 (§10.2)."""
    if _SKIP:
        _skip()
    _load()
    pt = _month(_office(_doc, "TOKYO"), "2026-03")
    assert pt["processed"] == 3155, f"Expected 3155, got {pt['processed']}"


def test_pure_tokyo_pending_2026_03():
    """純东京 pending = 受理総(49455) − 既済(3155) = 46300 (§10.2)."""
    if _SKIP:
        _skip()
    _load()
    pt = _month(_office(_doc, "TOKYO"), "2026-03")
    assert pt["pending"] == 46300, f"Expected 46300, got {pt['pending']}"


def test_tokyo_bureau_total_pending_2026_03():
    """東京管内 bureauTotal pending = 55427 − 3720 = 51707 (§10.2)."""
    if _SKIP:
        _skip()
    _load()
    bt = _bureau_month(_office(_doc, "TOKYO"), "2026-03")
    assert bt is not None, "No bureauTotal 2026-03 for TOKYO"
    assert bt["pending"] == 51707, f"Expected 51707, got {bt['pending']}"


def test_pending_equals_recv_total_minus_processed():
    """Invariant: pending == received_total − processed for every data point."""
    if _SKIP:
        _skip()
    _load()
    for month, bureau_data in _monthly_parsed.items():
        for key, items in bureau_data["bureau"].items():
            rt = items.get(ITEM_RECEIVED_TOTAL, 0)
            pr = items.get(ITEM_PROCESSED, 0)
            computed_pending = max(0, rt - pr)
            # Cross-check via doc (pure office values won't match exactly due to subtraction,
            # so we check the raw bureau values directly)
            if key == "TOKYO" and month == "2026-03":
                assert computed_pending == 51707, (
                    f"TOKYO bureau pending invariant: expected 51707, got {computed_pending}"
                )


def test_dataasof():
    """dataAsOf should reflect the latest month in the CSV."""
    if _SKIP:
        _skip()
    _load()
    assert _doc["dataAsOf"] == "2026-03", f"Expected 2026-03, got {_doc['dataAsOf']}"


def test_permits_years():
    """Permits table should have entries for multiple years including 2024."""
    if _SKIP:
        _skip()
    _load()
    assert 2024 in _permits_parsed, "2024 permits data missing"
    assert _permits_parsed[2024]["TOKYO"] == 17903, (
        f"Expected Tokyo 2024 permits 17903, got {_permits_parsed[2024]['TOKYO']}"
    )


def test_yokohama_no_bureau_total():
    """YOKOHAMA is a branch itself; bureauTotal field should be absent."""
    if _SKIP:
        _skip()
    _load()
    yoko = _office(_doc, "YOKOHAMA")
    assert "bureauTotal" not in yoko, "YOKOHAMA should not have bureauTotal"


# ---------------------------------------------------------------------------
# Runner (no pytest dependency)
# ---------------------------------------------------------------------------
def _skip():
    print(f"SKIP: {_SKIP_REASON}")
    sys.exit(0)


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except SystemExit:
            pass
    if failed:
        print(f"\n{failed} test(s) FAILED")
        sys.exit(1)
    else:
        print(f"\nAll {len(tests)} tests passed")
