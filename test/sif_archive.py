#!/usr/bin/env python3
"""KOSHA 사망사고 고위험요인(SIF) 아카이브 키워드 조회. Task 2a.

Python 3.9+, 표준 라이브러리만 사용.

날짜 필터가 없는 키워드 검색 API다 (docs/03_tasks/task-02a-sif-archive-lookup.md 참고).
"오늘의 신규 사고"가 아니라, 주어진 재해유형 키워드로 과거 유사 사례를 찾는 용도.

사용법:
    DATA_GO_KR_SERVICE_KEY=... python3 sif_archive.py --keyword 끼임 --cate-code 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv_loader import load_dotenv

API_URL = "https://apis.data.go.kr/B552468/sifArchive"


def _build_url(service_key: str, keyword: str, cate_code: str, page_no: int, num_of_rows: int) -> str:
    params = {
        "serviceKey": service_key,
        "callApiId": 1170,
        "cateSeCd": cate_code,
        "disasterOverview": keyword,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
    }
    return API_URL + "?" + urlencode(params)


def fetch_cases(service_key: str, keyword: str, cate_code: str = "1", page_no: int = 1, num_of_rows: int = 10, retries: int = 3) -> dict:
    url = _build_url(service_key, keyword, cate_code, page_no, num_of_rows)
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=25) as res:
                body = res.read(8_000_000)
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status}")
                return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise RuntimeError(f"SIF API HTTP {exc.code}: {detail[:300]}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"SIF API 통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SIF API 응답이 JSON이 아님(XML 에러 응답일 가능성): {exc}") from None
    raise RuntimeError("재시도 초과")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KOSHA SIF 아카이브 키워드 조회")
    parser.add_argument("--keyword", required=True, help="재해유형 검색어 (예: 끼임)")
    parser.add_argument("--cate-code", default="1", help="업종 구분 코드 (의미 미확인, 실호출로 확인 예정)")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--num-rows", type=int, default=10)
    args = parser.parse_args(argv)

    load_dotenv()
    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        print("환경변수 DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    try:
        result = fetch_cases(service_key, args.keyword, args.cate_code, args.page, args.num_rows)
    except RuntimeError as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
