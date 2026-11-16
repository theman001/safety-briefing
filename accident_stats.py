#!/usr/bin/env python3
"""KOSHA 산업중분류별 발생형태별 사고재해자수 통계 수집 (odcloud REST API). Task 2b.

Python 3.9+, 표준 라이브러리만 사용.

data.go.kr의 openapi.do 탭에는 안 뜨지만, 실제로는 odcloud 기반 REST API가 있다
(docs/03_tasks/task-02b-accident-stats-file.md 참고). 매년 새 연도 데이터가 새 uddi로
올라오므로 uddi를 하드코딩하지 않고 swagger 메타데이터에서 매번 최신 연도를 찾는다.

사용법:
    DATA_GO_KR_SERVICE_KEY=... python3 accident_stats.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv_loader import load_dotenv

DATASET_ID = "15084677"
SWAGGER_URL = f"https://infuser.odcloud.kr/oas/docs?namespace={DATASET_ID}/v1"
API_ROOT = "https://api.odcloud.kr/api"

YEAR_RE = re.compile(r"(\d{4})[-/.]?(\d{2})[-/.]?(\d{2})")

OCCURRENCE_FIELDS = [
    "떨어짐", "넘어짐", "부딪힘", "맞음", "무너짐", "끼임", "절단베임찔림", "감전",
    "폭발파열", "화재", "깔림뒤집힘", "이상온도물체접촉", "빠짐익사", "불균형및무리한동작",
    "화학물질누출접촉", "산소결핍", "사업장내교통사고", "사업장외교통사고", "체육행사",
    "폭력행위", "동물상해", "기타", "분류불능",
]


def _http_get_json(url: str, retries: int = 3, timeout: int = 25) -> dict:
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=timeout) as res:
                body = res.read(8_000_000)
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status}")
                return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"응답이 JSON이 아님: {exc}") from None
    raise RuntimeError("재시도 초과")


def find_latest_endpoint(swagger: dict) -> tuple[str, str]:
    """swagger paths 중 summary 끝의 날짜가 가장 최신인 경로를 고른다. 반환: (path, summary)."""
    best = None
    for path, spec in swagger.get("paths", {}).items():
        summary = spec.get("get", {}).get("summary", "")
        m = YEAR_RE.search(summary)
        if not m:
            continue
        date_key = "".join(m.groups())
        if best is None or date_key > best[0]:
            best = (date_key, path, summary)
    if best is None:
        raise RuntimeError("swagger에서 연도별 엔드포인트를 찾지 못함")
    return best[1], best[2]


def fetch_all_rows(service_key: str, path: str, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        url = API_ROOT + path + "?" + urlencode({"page": page, "perPage": page_size, "serviceKey": service_key})
        resp = _http_get_json(url)
        rows.extend(resp.get("data", []))
        total = resp.get("totalCount", len(rows))
        if len(rows) >= total or not resp.get("data"):
            break
        page += 1
    return rows


def verify_row_totals(rows: list[dict]) -> list[dict]:
    mismatches = []
    for row in rows:
        total = row.get("총계")
        if total is None:
            continue
        computed = sum(row.get(f, 0) or 0 for f in OCCURRENCE_FIELDS)
        if computed != total:
            mismatches.append({"대업종": row.get("대업종"), "중업종": row.get("중업종"), "규모": row.get("규모"), "총계": total, "계산값": computed})
    return mismatches


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KOSHA 사고재해자수 통계(최신 연도) 수집")
    parser.add_argument("--out", default=None, help="저장 경로 (기본: output/accident_stats_<연도>.json)")
    args = parser.parse_args(argv)

    load_dotenv()
    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        print("환경변수 DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    try:
        swagger = _http_get_json(SWAGGER_URL)
        path, summary = find_latest_endpoint(swagger)
        rows = fetch_all_rows(service_key, path)
    except RuntimeError as exc:
        print(f"수집 실패: {exc}", file=sys.stderr)
        return 1

    mismatches = verify_row_totals(rows)
    year_match = YEAR_RE.search(summary)
    year = year_match.group(1) if year_match else "unknown"

    out_path = args.out or f"output/accident_stats_{year}.json"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"source_summary": summary, "row_count": len(rows), "mismatches": mismatches, "rows": rows}, f, ensure_ascii=False, indent=2)

    print(f"수집 완료: {summary} / {len(rows)}행, 총계 불일치 {len(mismatches)}건 -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
