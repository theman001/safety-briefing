#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 3: 뉴스 브리핑 후보(1b)에 공공데이터 통계(2b) 트렌드를 참고 컨텍스트로 붙여
Task 4 입력용 daily_briefing_<date>.json을 만든다. 네트워크 호출 없음, 표준 라이브러리만 사용.

사건 단위 교차 소스 중복 제거는 하지 않음 — 2a(SIF 아카이브)가 블로커 상태라
지금은 사건 단위 소스가 뉴스 하나뿐. 2a가 준비되면 추가할 것.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

META_FIELDS = {"규모", "대업종", "중업종", "총계"}

# 우리 7개 업종 버킷 ↔ KSIC 중업종(실제 2025 데이터 대조, 2026-11-16).
# 완성차 전용 중업종이 따로 없어 "자동차·설비보전"은 근사 매핑. "방산"은 KSIC에
# 무기제조 전용 분류가 없어 매핑하지 않음(추측 금지 원칙).
INDUSTRY_TO_KSIC = {
    "정유·석유화학": ["화학및고무제품제조업", "의약품·화장품·연탄·석유제품제조업"],
    "철강": ["금속제련업", "기계기구·금속·비금속광물제품제조업"],
    "비철금속": ["금속제련업"],
    "발전소": ["전기·가스·증기·수도사업"],
    "반도체": ["전기기계기구·정밀기구·전자제품제조업"],
    "자동차·설비보전": ["기계기구·금속·비금속광물제품제조업"],
}


def load_stats(output_dir: Path):
    years = []
    for p in output_dir.glob("accident_stats_*.json"):
        m = re.match(r"accident_stats_(\d{4})\.json$", p.name)
        if m:
            years.append((int(m.group(1)), p))
    if not years:
        return None, None
    year, path = max(years)
    data = json.loads(path.read_text(encoding="utf-8"))
    return year, data.get("rows", [])


def aggregate_by_ksic(rows: list[dict]) -> dict[str, Counter]:
    by_ksic: dict[str, Counter] = {}
    for row in rows:
        name = row.get("중업종")
        if not name:
            continue
        counter = by_ksic.setdefault(name, Counter())
        for k, v in row.items():
            if k in META_FIELDS or not isinstance(v, int):
                continue
            counter[k] += v
    return by_ksic


def stat_context_for(industries: list[str], by_ksic: dict[str, Counter], year: int):
    mapped = [i for i in industries if i in INDUSTRY_TO_KSIC]
    if not mapped:
        return None
    combined = Counter()
    used_ksic = set()
    for bucket in mapped:
        for ksic_name in INDUSTRY_TO_KSIC[bucket]:
            if ksic_name in by_ksic:
                combined.update(by_ksic[ksic_name])
                used_ksic.add(ksic_name)
    if not combined:
        return None
    return {
        "source_year": year,
        "based_on_industries": mapped,
        "based_on_ksic_categories": sorted(used_ksic),
        "top_event_types": [[name, count] for name, count in combined.most_common(3)],
    }


def enrich(articles: list[dict], by_ksic: dict[str, Counter] | None, year: int | None) -> list[dict]:
    result = []
    for art in articles:
        ctx = stat_context_for(art.get("industry_matches", []), by_ksic, year) if by_ksic is not None else None
        result.append({**art, "stat_context": ctx})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Task 3: 뉴스 브리핑 후보 + 공공데이터 통계 컨텍스트 통합")
    parser.add_argument("--date", default=None, help="대상일(KST), YYYY-MM-DD. 기본: 어제")
    parser.add_argument("--input-dir", type=Path, default=Path("output"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args(argv)

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            parser.error("--date는 YYYY-MM-DD 형식이어야 합니다")
    else:
        target = (datetime.now(KST) - timedelta(days=1)).date()

    candidates_path = args.input_dir / f"briefing_candidates_{target.isoformat()}.json"
    if not candidates_path.exists():
        print(f"오류: 입력 파일이 없음: {candidates_path}", file=sys.stderr)
        return 2
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))

    year, rows = load_stats(args.input_dir)
    by_ksic = None
    if rows is None:
        print(f"주의: {args.input_dir}에 accident_stats_*.json이 없음. stat_context는 전부 null로 진행.", file=sys.stderr)
    else:
        by_ksic = aggregate_by_ksic(rows)

    incidents = enrich(candidates.get("incidents", []), by_ksic, year)
    insights = enrich(candidates.get("safety_and_maintenance", []), by_ksic, year)
    unmapped = sum(1 for a in incidents + insights if a["stat_context"] is None)

    output = {
        "target_date_kst": target.isoformat(),
        "generated_at_kst": datetime.now(KST).isoformat(),
        "stats_year_used": year,
        "incidents": incidents,
        "safety_and_maintenance": insights,
        "unmapped_industry_count": unmapped,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"daily_briefing_{target.isoformat()}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Task 3: 소스 통합")
    print("대상일(KST):", target.isoformat())
    print("통계 연도:", year if year else "없음(통계 파일 없음)")
    print("incidents:", len(incidents), "건 / safety_and_maintenance:", len(insights), "건")
    print("통계 미매핑:", unmapped, "건")
    print("출력:", out_path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
