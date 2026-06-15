#!/usr/bin/env python3
"""estat_to_json.py — e-Stat CSV → public-data.json

Usage:
    python3 estat_to_json.py <monthly_csv> <permits_csv> [--out public-data.json]

Sources (Shift-JIS encoded):
  monthly_csv : 月度受理処理 (sid=0003449073, 表番号06) — 在留資格の取得等の受理及び処理人員
  permits_csv : 年度永住許可数 (sid=0003289203) — 国籍・地域別 地方局別 永住許可人員
"""

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

# ── Monthly table column indices (0-based after CSV parse) ────────────────────
# Row structure: 12 dimension fields | 1 label field | 16 region value fields
MONTHLY_COL_TIME_CODE   = 3   # 時間軸（月次） コード  e.g. "2026000303"
MONTHLY_COL_TIME_LABEL  = 5   # 時間軸（月次）  e.g. "2026年3月"
MONTHLY_COL_VISA_CODE   = 6   # 在留資格審査 コード  "60" = 永住
MONTHLY_COL_ITEM_CODE   = 9   # 受理・処理 コード
MONTHLY_COL_TOTAL       = 13  # 総数
MONTHLY_COL_SAPPORO     = 14  # 札幌管内
MONTHLY_COL_SENDAI      = 15  # 仙台管内
MONTHLY_COL_TOKYO       = 16  # 東京管内 (includes Narita/Haneda/Yokohama branches)
MONTHLY_COL_NARITA      = 17  # 成田空港支局
MONTHLY_COL_HANEDA      = 18  # 羽田空港支局
MONTHLY_COL_YOKOHAMA    = 19  # 横浜支局
MONTHLY_COL_NAGOYA      = 20  # 名古屋管内 (includes Chubu airport)
MONTHLY_COL_CHUBU       = 21  # 中部空港支局
MONTHLY_COL_OSAKA       = 22  # 大阪管内 (includes Kansai airport/Kobe)
MONTHLY_COL_KANSAI      = 23  # 関西空港支局
MONTHLY_COL_KOBE        = 24  # 神戸支局
MONTHLY_COL_HIROSHIMA   = 25  # 広島管内
MONTHLY_COL_TAKAMATSU   = 26  # 高松管内
MONTHLY_COL_FUKUOKA     = 27  # 福岡管内 (includes Naha)
MONTHLY_COL_NAHA        = 28  # 那覇支局

# Item codes
ITEM_RECEIVED_TOTAL = "100000"  # 受理_総数 = 旧受 + 新受 (used to compute pending)
ITEM_RECEIVED_NEW   = "103000"  # 受理_新受 = λ
ITEM_PROCESSED      = "300000"  # 既済_総数 = μ

VISA_EIJYU = "60"  # 永住

# Per-office calibration: real observed latency ÷ naive backlog-clearance estimate.
# The FIFO model (pending ÷ throughput) underestimates actual wait because the queue
# isn't strictly FIFO and resources are shared across statuses. Tuned from ground truth
# (Tokyo ≈ 700 days). Offices without ground truth stay at 1.0 until measured.
CALIBRATION = {
    "TOKYO": 1.65,
}

# ── Permits table column indices ───────────────────────────────────────────────
PERMITS_COL_YEAR_CODE   = 3   # 時間軸(年次) コード  e.g. "2024000000"
PERMITS_COL_YEAR_LABEL  = 5   # 時間軸(年次)  e.g. "2024年"
PERMITS_COL_NATL_CODE   = 6   # 国籍・地域 コード  "50000" = 総数
PERMITS_COL_DIM_LABEL   = 9   # dimension label (empty in data rows)
PERMITS_COL_TOTAL       = 10  # 全国総数
PERMITS_COL_SAPPORO     = 11  # 札幌管内
PERMITS_COL_SENDAI      = 12  # 仙台管内
PERMITS_COL_TOKYO       = 13  # 東京管内 (includes Yokohama; no sub-split in this table)
PERMITS_COL_NAGOYA      = 14  # 名古屋管内
PERMITS_COL_OSAKA       = 15  # 大阪管内 (includes Kobe)
PERMITS_COL_HIROSHIMA   = 16  # 広島管内
PERMITS_COL_TAKAMATSU   = 17  # 高松管内
PERMITS_COL_FUKUOKA     = 18  # 福岡管内


def _int(s: str) -> int:
    """Parse e-Stat value: strip quotes, remove thousands commas, handle 0/"***"."""
    s = s.strip().strip('"')
    if s in ("", "***", "-"):
        return 0
    return int(s.replace(",", ""))


def _parse_month(label: str) -> str | None:
    """Convert '2026年3月' → '2026-03'. Returns None if not parseable."""
    m = re.match(r"(\d{4})年(\d{1,2})月", label.strip().strip('"'))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def _parse_year(label: str) -> int | None:
    """Convert '2024年' → 2024. Returns None if not parseable."""
    m = re.match(r"(\d{4})年", label.strip().strip('"'))
    return int(m.group(1)) if m else None


def parse_monthly_csv(filepath: Path) -> dict:
    """
    Returns:
        {
            "YYYY-MM": {
                "bureau": {  # 管内合計 (e-Stat raw)
                    "TOKYO":    {"recv_total": int, "recv_new": int, "processed": int},
                    "YOKOHAMA": {...},
                    ...
                }
            }
        }
    """
    result: dict[str, dict] = {}

    with open(filepath, encoding="shift_jis", errors="replace", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) <= MONTHLY_COL_ITEM_CODE:
                continue
            if row[MONTHLY_COL_VISA_CODE].strip().strip('"') != VISA_EIJYU:
                continue
            item_code = row[MONTHLY_COL_ITEM_CODE].strip().strip('"')
            if item_code not in (ITEM_RECEIVED_TOTAL, ITEM_RECEIVED_NEW, ITEM_PROCESSED):
                continue
            month = _parse_month(row[MONTHLY_COL_TIME_LABEL])
            if month is None:
                continue

            if month not in result:
                result[month] = {"bureau": {}}
            bureau = result[month]["bureau"]

            def _set(key: str, col: int):
                if key not in bureau:
                    bureau[key] = {}
                if col < len(row):
                    bureau[key][item_code] = _int(row[col])

            _set("TOKYO",    MONTHLY_COL_TOKYO)
            _set("NARITA",   MONTHLY_COL_NARITA)
            _set("HANEDA",   MONTHLY_COL_HANEDA)
            _set("YOKOHAMA", MONTHLY_COL_YOKOHAMA)
            _set("NAGOYA",   MONTHLY_COL_NAGOYA)
            _set("CHUBU",    MONTHLY_COL_CHUBU)
            _set("OSAKA",    MONTHLY_COL_OSAKA)
            _set("KANSAI",   MONTHLY_COL_KANSAI)
            _set("KOBE",     MONTHLY_COL_KOBE)
            _set("FUKUOKA",  MONTHLY_COL_FUKUOKA)
            _set("NAHA",     MONTHLY_COL_NAHA)

    return result


def parse_permits_csv(filepath: Path) -> dict:
    """
    Returns:
        {
            2024: {"TOKYO": int, "NAGOYA": int, "OSAKA": int, "FUKUOKA": int},
            ...
        }
    """
    result: dict[int, dict] = {}

    with open(filepath, encoding="shift_jis", errors="replace", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) <= PERMITS_COL_OSAKA:
                continue
            if row[PERMITS_COL_NATL_CODE].strip().strip('"') != "50000":
                continue
            year = _parse_year(row[PERMITS_COL_YEAR_LABEL])
            if year is None:
                continue
            if len(row) <= PERMITS_COL_FUKUOKA:
                continue
            result[year] = {
                "TOKYO":    _int(row[PERMITS_COL_TOKYO]),
                "NAGOYA":   _int(row[PERMITS_COL_NAGOYA]),
                "OSAKA":    _int(row[PERMITS_COL_OSAKA]),
                "FUKUOKA":  _int(row[PERMITS_COL_FUKUOKA]),
            }

    return result


def _monthly_point(bureau_data: dict, month: str,
                   new_cols: list[str], sub_cols: list[str]) -> dict | None:
    """
    Build one MonthlyPoint (pure office = bureau minus sub-offices).

    new_cols  : list of sub-bureau keys to subtract (e.g. ["NARITA","HANEDA","YOKOHAMA"])
    sub_cols  : same (same list, kept separate for clarity)
    Returns None if required item codes are missing.
    """
    bureau = bureau_data.get("bureau", {})

    def _get(key: str, item: str) -> int:
        return bureau.get(key, {}).get(item, 0)

    def _pure(item: str) -> int:
        base = _get(new_cols[0], item)  # first entry is the main bureau
        for sub in new_cols[1:]:
            base -= _get(sub, item)
        return max(0, base)

    recv_total = _pure(ITEM_RECEIVED_TOTAL)
    recv_new   = _pure(ITEM_RECEIVED_NEW)
    processed  = _pure(ITEM_PROCESSED)

    if recv_total == 0 and recv_new == 0 and processed == 0:
        return None

    return {
        "month": month,
        "received": recv_new,
        "processed": processed,
        "pending": max(0, recv_total - processed),
    }


def _bureau_point(bureau_data: dict, month: str, key: str) -> dict | None:
    bureau = bureau_data.get("bureau", {}).get(key, {})
    recv_total = bureau.get(ITEM_RECEIVED_TOTAL, 0)
    recv_new   = bureau.get(ITEM_RECEIVED_NEW, 0)
    processed  = bureau.get(ITEM_PROCESSED, 0)
    if recv_total == 0 and recv_new == 0 and processed == 0:
        return None
    return {
        "month": month,
        "received": recv_new,
        "processed": processed,
        "pending": max(0, recv_total - processed),
    }


def build_json(monthly_by_month: dict, permits_by_year: dict,
               data_as_of: str | None = None) -> dict:
    months_sorted = sorted(monthly_by_month.keys())
    if not months_sorted:
        raise ValueError("No monthly data parsed")

    data_as_of = data_as_of or months_sorted[-1]
    updated_at = date.today().isoformat()

    # ── Build per-office monthly series ───────────────────────────────────────
    def _series_pure(main_key: str, sub_keys: list[str]) -> list[dict]:
        out = []
        for m in months_sorted:
            pt = _monthly_point(monthly_by_month[m], m,
                                [main_key] + sub_keys, sub_keys)
            if pt:
                out.append(pt)
        return out

    def _series_bureau(key: str) -> list[dict]:
        out = []
        for m in months_sorted:
            pt = _bureau_point(monthly_by_month[m], m, key)
            if pt:
                out.append(pt)
        return out

    def _permits(key: str) -> list[dict]:
        return [
            {"year": y, "count": v[key]}
            for y, v in sorted(permits_by_year.items())
            if key in v and v[key] > 0
        ]

    # TOKYO pure = 東京管内 − 成田 − 羽田 − 横浜
    tokyo_pure = _series_pure("TOKYO", ["NARITA", "HANEDA", "YOKOHAMA"])
    tokyo_bureau = _series_bureau("TOKYO")

    # YOKOHAMA is itself a branch (no further sub-branches)
    yokohama_pure = _series_bureau("YOKOHAMA")

    # OSAKA pure = 大阪管内 − 関西空港 − 神戸
    osaka_pure = _series_pure("OSAKA", ["KANSAI", "KOBE"])
    osaka_bureau = _series_bureau("OSAKA")

    # KOBE is itself a branch
    kobe_pure = _series_bureau("KOBE")

    # NAGOYA pure = 名古屋管内 − 中部空港
    nagoya_pure = _series_pure("NAGOYA", ["CHUBU"])
    nagoya_bureau = _series_bureau("NAGOYA")

    # FUKUOKA pure = 福岡管内 − 那覇
    fukuoka_pure = _series_pure("FUKUOKA", ["NAHA"])
    fukuoka_bureau = _series_bureau("FUKUOKA")

    offices = [
        {
            "code": "TOKYO",
            "displayName": "东京入管",
            "regionalNote": "东京都案件量大，处理时间显著偏长。纯东京数据已减去成田/羽田/横浜支局。",
            "monthly": tokyo_pure,
            "bureauTotal": {
                "label": "东京管内（含横滨等支局）",
                "monthly": tokyo_bureau,
            },
            "permitsByYear": _permits("TOKYO"),
        },
        {
            "code": "YOKOHAMA",
            "displayName": "横滨支局",
            "regionalNote": "横浜支局自 2025 年起处理显著加快。",
            "monthly": yokohama_pure,
        },
        {
            "code": "OSAKA",
            "displayName": "大阪入管",
            "regionalNote": "大阪管内覆盖关西地区，处理时间通常接近官方标准区间。",
            "monthly": osaka_pure,
            "bureauTotal": {
                "label": "大阪管内（含関西空港/神户支局）",
                "monthly": osaka_bureau,
            },
            "permitsByYear": _permits("OSAKA"),
        },
        {
            "code": "KOBE",
            "displayName": "神户支局",
            "regionalNote": "神户支局覆盖兵库一带。",
            "monthly": kobe_pure,
        },
        {
            "code": "NAGOYA",
            "displayName": "名古屋入管",
            "regionalNote": "名古屋管内覆盖中部地区。",
            "monthly": nagoya_pure,
            "bureauTotal": {
                "label": "名古屋管内（含中部空港支局）",
                "monthly": nagoya_bureau,
            },
            "permitsByYear": _permits("NAGOYA"),
        },
        {
            "code": "FUKUOKA",
            "displayName": "福冈入管",
            "regionalNote": "福冈管内覆盖九州地区。",
            "monthly": fukuoka_pure,
            "bureauTotal": {
                "label": "福岡管内（含那覇支局）",
                "monthly": fukuoka_bureau,
            },
            "permitsByYear": _permits("FUKUOKA"),
        },
    ]

    # Attach per-office calibration factor (default 1.0).
    for office in offices:
        office["calibrationFactor"] = CALIBRATION.get(office["code"], 1.0)

    return {
        "schemaVersion": 1,
        "dataAsOf": data_as_of,
        "updatedAt": updated_at,
        "source": {
            "name": "出入国在留管理庁 出入国管理統計",
            "mainTableUrl": "https://www.e-stat.go.jp/dbview?sid=0003449073",
            "permitTableUrl": "https://www.e-stat.go.jp/dbview?sid=0003289203",
        },
        "standardProcessing": {
            "rangeLabel": "4 - 6 个月",
            "minMonths": 4,
            "maxMonths": 6,
        },
        "offices": offices,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("monthly_csv", help="月度受理処理 CSV (Shift-JIS)")
    parser.add_argument("permits_csv", help="年度永住許可数 CSV (Shift-JIS)")
    parser.add_argument("--out", default="public-data.json",
                        help="Output path (default: public-data.json)")
    args = parser.parse_args()

    print(f"Parsing monthly CSV: {args.monthly_csv}", file=sys.stderr)
    monthly = parse_monthly_csv(Path(args.monthly_csv))
    print(f"  → {len(monthly)} months", file=sys.stderr)

    print(f"Parsing permits CSV: {args.permits_csv}", file=sys.stderr)
    permits = parse_permits_csv(Path(args.permits_csv))
    print(f"  → {len(permits)} years", file=sys.stderr)

    doc = build_json(monthly, permits)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"Written: {out_path}  ({out_path.stat().st_size:,} bytes)", file=sys.stderr)

    # Quick sanity check
    tokyo_mar = next((o for o in doc["offices"] if o["code"] == "TOKYO"), None)
    if tokyo_mar:
        last = tokyo_mar["monthly"][-1] if tokyo_mar["monthly"] else None
        if last and last["month"] == "2026-03":
            assert last["received"] == 4423, f"Tokyo 新受 mismatch: {last['received']}"
            assert last["processed"] == 3155, f"Tokyo 既済 mismatch: {last['processed']}"
            assert last["pending"] == 46300, f"Tokyo pending mismatch: {last['pending']}"
            print("✓ Gold standard assertions passed (2026-03 Tokyo pure values)", file=sys.stderr)
        bt_last = tokyo_mar.get("bureauTotal", {}).get("monthly", [])
        bt_last = bt_last[-1] if bt_last else None
        if bt_last and bt_last["month"] == "2026-03":
            assert bt_last["pending"] == 51707, f"Tokyo bureauTotal pending mismatch: {bt_last['pending']}"
            print("✓ Tokyo bureauTotal pending == 51707 ✓", file=sys.stderr)


if __name__ == "__main__":
    main()
