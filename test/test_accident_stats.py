#!/usr/bin/env python3
"""accident_stats.py 핵심 로직(최신연도 선택, 합계 검증) self-check. 네트워크 호출 없음."""
from accident_stats import OCCURRENCE_FIELDS, find_latest_endpoint, verify_row_totals


def test_find_latest_endpoint_picks_max_year():
    swagger = {
        "paths": {
            "/15084677/v1/uddi:aaa": {"get": {"summary": "foo_20231231"}},
            "/15084677/v1/uddi:bbb": {"get": {"summary": "foo_20251231"}},
            "/15084677/v1/uddi:ccc": {"get": {"summary": "foo_12/31/2020"}},
        }
    }
    path, summary = find_latest_endpoint(swagger)
    assert path == "/15084677/v1/uddi:bbb"
    assert "20251231" in summary


def test_verify_row_totals_detects_mismatch():
    row_ok = {f: 0 for f in OCCURRENCE_FIELDS}
    row_ok.update({"총계": 2, "떨어짐": 1, "넘어짐": 1})
    row_bad = {f: 0 for f in OCCURRENCE_FIELDS}
    row_bad.update({"총계": 5, "떨어짐": 1, "넘어짐": 1})

    mismatches = verify_row_totals([row_ok, row_bad])
    assert len(mismatches) == 1
    assert mismatches[0]["총계"] == 5


if __name__ == "__main__":
    test_find_latest_endpoint_picks_max_year()
    test_verify_row_totals_detects_mismatch()
    print("OK")
