#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 1b: 뉴스 1차 분류 (규칙 기반, 네트워크 호출 없음).

1a 출력(news_raw_<date>.json)의 모든 기사에 레이블 하나를 매긴다:
INCIDENT_REPORT / INCIDENT_FOLLOWUP / SAFETY_TREND / MAINTENANCE_TECH / REVIEW / EXCLUDED.
우선순위 순서대로 규칙을 평가 — 먼저 맞는 규칙이 이기고 끝. 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

# ponytail: news_fetch.py와 INDUSTRY_TERMS/INDUSTRIAL_CONTEXT가 중복된다.
# 두 스크립트가 test/ 밖(프로젝트 루트)으로 같이 옮겨진 뒤 공용 모듈로 추출할 것.
INDUSTRY_TERMS = {
    "정유·석유화학": ["정유공장", "정유", "석유화학", "화학공장", "정제시설", "정제공장", "석유정제", "반응기", "나프타", "화학단지", "석유시설"],
    "철강": ["제철소", "제철", "제강", "철강", "압연", "용광로", "고로", "전기로"],
    "비철금속": ["제련소", "제련", "비철금속", "동제련", "아연제련", "니켈제련", "용해로", "용융금속", "주조설비"],
    "발전소": ["발전소", "화력발전", "원자력발전", "원전", "복합화력", "발전터빈", "발전설비", "증기터빈", "급수펌프", "보일러", "가스터빈"],
    "방산": ["방위산업", "방산", "군수공장", "탄약공장", "화약공장", "탄약제조", "방산설비", "화약제조", "무기제조", "군수품"],
    "반도체": ["반도체", "웨이퍼", "반도체공장", "반도체팹", "클린룸", "식각장비", "노광장비", "반도체장비", "스크러버"],
    "자동차·설비보전": ["자동차공장", "완성차", "차체공장", "자동차생산", "자동차 조립", "조립라인", "프레스", "컨베이어", "산업용로봇", "설비보전", "예방정비", "설비정비", "정비작업", "생산라인", "유압설비", "공압설비", "공작기계"],
}
INDUSTRIAL_CONTEXT = [
    "공장", "산업현장", "작업자", "근로자", "정비", "설비", "기계", "공정", "생산시설",
    "제조", "제련", "제철", "발전소", "배관", "작업장", "안전보건", "산업재해", "산재",
    "압력용기", "회전체", "로봇", "터빈", "보일러", "저장탱크", "용해로", "화학시설",
]

EVENT_STRONG = [
    "화재", "폭발", "누출", "유출", "질식", "감전", "끼임", "협착", "추락", "붕괴", "파열",
    "감전사", "인명피해", "사망", "숨져", "숨진", "숨졌다", "숨지고", "다쳐", "부상",
    "설비 고장", "설비고장", "기계 고장", "기계고장", "가동중단", "가동 중단", "가동정지", "가동 정지",
    "작업중 사고", "작업 중 사고", "정전", "가스중독", "중독사", "넘어져", "매몰", "화학물질 유출",
]
# 실제 발생 신호(드릴/시연 보도와 구분용). 사망/숨져 등 EVENT_STRONG과는 별개로 "지금 실제로 벌어졌다"는 단서만.
OCCURRENCE = ["소방당국", "현장 출동", "출동", "발견"]
# "후속 보도"임을 알려주는 단서 — 수사 진행/결과, 법적 절차 등 구체적인 것만 포함한다.
# "수사"/"지난해"/"작년" 같은 말은 최초 보도에도 관례적으로 흔히 쓰여서(예: "경찰이 수사
# 중이다") 뺐다 — 실데이터(2026-11-12)에서 이 때문에 최초 보도가 FOLLOWUP으로 잘못
# 당겨지는 걸 확인(한솔제지 지게차 사고 최초 보도가 "수사"만으로 FOLLOWUP 처리됨).
FOLLOWUP = [
    "사고 원인", "사고원인", "사고 조사", "사고조사", "사고 재발", "재발 방지", "재발방지",
    "조사 결과", "조사결과", "법원", "재판", "판결", "기소", "송치",
    "산재 인정", "보상", "과실", "책임자", "형사처벌",
]
SAFETY = [
    "안전관리", "산업안전", "위험하면", "작업 멈추", "대피", "안전교육", "안전대책", "안전 대책",
    "작업중지권", "안전점검", "예방대책", "사고 예방", "재해 예방", "위험성평가", "안전 강화",
    "안전 수칙", "안전수칙", "안전보건", "중대재해", "안전 기술",
]
TECH = [
    "예지보전", "예방정비", "설비보전", "설비 진단", "설비진단", "고장 예측", "고장예측",
    "이상 감지", "이상감지", "예측 정비", "예측정비", "유지보수", "정비 기술", "스마트 정비",
    "진동 진단", "설비 상태", "설비 수명", "결함 진단",
]
# 실제 사고가 아니라 훈련/시연 보도임을 알려주는 단서. "방제훈련"/"합동훈련"은
# 2026-11-12 실데이터(인천 남동구 유해화학물질 누출 대비 민·관 합동훈련 반복 보도)에서 누락 발견, 추가.
EXERCISE = [
    "모의훈련", "소방훈련", "방재훈련", "방제훈련", "대응훈련", "합동훈련", "훈련대회",
    "시연", "가상상황", "가상 상황", "대피훈련", "예방훈련", "화재 대응 훈련", "화재 대비 훈련",
]
# 일반 근로-안전 어휘(산업재해/근로자/산업안전보건법 등)만으로는 "공공·비산업" 근로 맥락과
# "진짜 산업 현장"을 구분 못 함(둘 다 "사업장"처럼 범용 단어만 쓰는 경우가 있음) — 그래서
# "설비/공장 단어 필수"로 가르지 않고, 공공·비산업 근로를 직접 가리키는 단어를 네거티브로 쓴다.
# 실데이터(2026-11-12)에서 발견: 환경미화원 교통사고, 대학 캠퍼스 낙엽 청소 추락사가
# 업종 키워드 없이 일반 맥락만으로 사고로 오분류됨.
PUBLIC_SECTOR_CONTEXT = [
    "환경미화원", "미화원", "가로 청소", "낙엽 청소", "청소노동자", "환경공무관",
    "대학", "캠퍼스", "대학교",
]

BUSINESS_TITLE = [
    "주가", "공시", "실적", "증시", "투자자", "주식", "경영권", "지분", "공개매수", "상장",
    "금융", "배당", "증권", "최고경영자", "대표이사", "대표 구속", "흑자경영", "사외이사",
    "M&A", "시가총액", "민영화",
]
CIVIC_TITLE = [
    "행정사무감사", "행감", "도의회", "시의회", "지방의회", "예산 집행", "시정 브리핑",
    "주요일정", "주요 일정", "시장 선거", "공공기관 인사", "브리핑 모음",
]
# 입법/제도 기사(제목에 "OO법 개정안" 식으로 사고 키워드가 우연히 섞여 사고 보도로
# 오분류되는 걸 막기 위한 단서. 2026-11-16 실데이터: "화재예방법 개정안 발의"가
# "화재"의 부분 문자열 매칭으로 INCIDENT_REPORT가 됨. 2026-11-18: title만 보던 걸
# description까지 확장 — Naver API의 제목 절단으로 "발의" 등이 제목에서 사라지는
# 경우(원전 입법 기사 실데이터)가 확인됨.
LAW_TITLE = ["법안", "개정안", "제정안", "발의", "입법", "시행령"]

LABELS = ["INCIDENT_REPORT", "INCIDENT_FOLLOWUP", "SAFETY_TREND", "MAINTENANCE_TECH", "LAW_POLICY", "OTHER", "REVIEW", "EXCLUDED"]


def compressed(s: str) -> str:
    return re.sub(r"\s+", "", s.casefold())


# 짧은 키워드가 무관한 복합어의 부분 문자열로 우연히 걸리는 경우의 예외 목록.
# "공시"(공개 공시)가 "공공시설"(대구공공시설관리공단 기사, 2026-11-12 실데이터에서 발견)에
# 우연히 매칭되는 문제 — 해당 term을 검사하기 전에 예외 문자열을 지우고 검사한다.
TERM_COLLISION_EXCEPTIONS = {
    "방산": ["방산면"],
    "공시": ["공공시설"],
}


def hit(text: str, terms: list[str]) -> list[str]:
    c = compressed(text)
    found = []
    for term in terms:
        term_c = compressed(term)
        probe = c
        for exc in TERM_COLLISION_EXCEPTIONS.get(term, []):
            probe = probe.replace(compressed(exc), "")
        if term_c in probe:
            found.append(term)
    return found


def classify(title: str, description: str) -> dict:
    tit_industries = [name for name, terms in INDUSTRY_TERMS.items() if hit(title, terms)]
    desc_industries = [name for name, terms in INDUSTRY_TERMS.items() if hit(description, terms)]
    industries = sorted(set(tit_industries) | set(desc_industries))
    tit_context = hit(title, INDUSTRIAL_CONTEXT)
    is_industrial = bool(industries) or bool(tit_context or hit(description, INDUSTRIAL_CONTEXT))

    tit_evt = hit(title, EVENT_STRONG)
    # title만 보던 걸 description까지 확장(2026-11-18): Naver API가 제목을 잘라
    # "법안 발의" 중 "발의"가 날아가는 경우(원전 입법 기사 실데이터)가 확인됨 —
    # 새 키워드 추가가 아니라 기존 안전장치의 적용 범위만 넓히는 것.
    law = hit(title, LAW_TITLE) or hit(description, LAW_TITLE)
    follow = hit(title, FOLLOWUP) or hit(description, FOLLOWUP)
    exercise = hit(title, EXERCISE) or hit(description, EXERCISE)
    civic = hit(title, CIVIC_TITLE)
    business = hit(title, BUSINESS_TITLE)
    safety = hit(title, SAFETY)
    tech = hit(title, TECH)
    occ = hit(title, OCCURRENCE) or hit(description, OCCURRENCE)

    if not industries and (hit(title, PUBLIC_SECTOR_CONTEXT) or hit(description, PUBLIC_SECTOR_CONTEXT)):
        return {"classification": "EXCLUDED", "industry_matches": industries, "reasons": ["공공·비산업 근로 맥락, 특정 업종 단서 없음"]}
    if not is_industrial:
        return {"classification": "EXCLUDED", "industry_matches": industries, "reasons": ["산업 맥락 확인 불가"]}
    if (civic or business) and not tit_evt:
        return {"classification": "EXCLUDED", "industry_matches": industries, "reasons": [f"행정/경영 중심 기사: {civic or business}"]}
    # 입법/제도 기사는 제목의 사고 키워드 오탐(예: "화재예방법"의 "화재")보다 먼저 분리한다.
    if law:
        return {"classification": "LAW_POLICY", "industry_matches": industries, "reasons": [f"입법/제도 관련 제목: {law}"]}
    if exercise and not (occ and tit_evt):
        return {"classification": "SAFETY_TREND", "industry_matches": industries, "reasons": [f"훈련/시연 보도: {exercise}"]}
    if tit_evt:
        if follow:
            return {"classification": "INCIDENT_FOLLOWUP", "industry_matches": industries, "reasons": [f"사고 키워드+후속 단서: {tit_evt + follow}"]}
        return {"classification": "INCIDENT_REPORT", "industry_matches": industries, "reasons": [f"사고 키워드: {tit_evt}"]}
    if follow:
        # 사고/업종 단서가 본문에만 있고 제목에는 산업 맥락이 전혀 없으면, 모아보기 기사에
        # 우연히 섞인 문구일 가능성이 커 관련도가 낮다고 보고 기타로 내린다.
        if not (tit_industries or tit_context):
            return {"classification": "OTHER", "industry_matches": industries, "reasons": [f"후속 단서가 본문에만 있고 제목에 산업 맥락 없음: {follow}"]}
        return {"classification": "INCIDENT_FOLLOWUP", "industry_matches": industries, "reasons": [f"후속 보도 단서: {follow}"]}
    if safety:
        return {"classification": "SAFETY_TREND", "industry_matches": industries, "reasons": [f"안전/예방 키워드: {safety}"]}
    if tech:
        return {"classification": "MAINTENANCE_TECH", "industry_matches": industries, "reasons": [f"정비기술 키워드: {tech}"]}
    return {"classification": "REVIEW", "industry_matches": industries, "reasons": ["명확한 분류 근거 부족"]}


def classify_all(articles: list[dict]):
    results = []
    counts = {label: 0 for label in LABELS}
    for art in articles:
        title = art.get("title") or ""
        description = art.get("description") or ""
        result = classify(title, description)
        counts[result["classification"]] += 1
        results.append({**art, **result, "needs_source_verification": True})
    return results, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Task 1b: 뉴스 1차 분류 (규칙 기반, 네트워크 호출 없음)")
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

    in_path = args.input_dir / f"news_raw_{target.isoformat()}.json"
    if not in_path.exists():
        print(f"오류: 입력 파일이 없음: {in_path}", file=sys.stderr)
        return 2
    articles = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(articles, list):
        print(f"오류: {in_path}가 JSON 배열이 아님", file=sys.stderr)
        return 2
    if not articles:
        print(f"주의: {in_path.name}에 기사가 0건입니다. 빈 결과로 종료.", file=sys.stderr)

    results, counts = classify_all(articles)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"news_classified_{target.isoformat()}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    meta_path = args.output_dir / f"news_classified_{target.isoformat()}_meta.json"
    meta_path.write_text(json.dumps({
        "target_date_kst": target.isoformat(),
        "generated_at_kst": datetime.now(KST).isoformat(),
        "input_articles": len(articles),
        "counts": counts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    incidents = [r for r in results if r["classification"] in ("INCIDENT_REPORT", "INCIDENT_FOLLOWUP")]
    insights = [r for r in results if r["classification"] in ("SAFETY_TREND", "MAINTENANCE_TECH", "LAW_POLICY")]
    briefing_path = args.output_dir / f"briefing_candidates_{target.isoformat()}.json"
    briefing_path.write_text(json.dumps({
        "target_date_kst": target.isoformat(),
        "disclaimer": "제목·요약 기반 규칙 분류 결과입니다. 사고 원인/발생일은 원문 확인 전까지 미확인입니다.",
        "incidents": incidents,
        "safety_and_maintenance": insights,
        "review_count": counts["REVIEW"],
        "excluded_count": counts["EXCLUDED"],
        "other_count": counts["OTHER"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Task 1b: 뉴스 1차 분류")
    print("대상일(KST):", target.isoformat())
    print("입력 기사:", len(articles), "건")
    print("--- 분류 결과 ---")
    for label in LABELS:
        print(" ", label, counts[label], "건")
    print("출력:", out_path.resolve())
    print("브리핑 후보:", briefing_path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
