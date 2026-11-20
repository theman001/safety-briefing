#!/usr/bin/env python3
"""news_classify.py 분류 로직 self-check. 네트워크 호출 없음.

2026-11-16 Task 4 검증 중 실데이터로 발견한 두 가지 오분류(LAW_POLICY/OTHER 추가 계기)와
기존 정상 사례의 회귀 여부를 함께 확인한다.
"""
from news_classify import classify


def test_law_bill_not_misread_as_incident():
    title = "김종민 의원, '소방시설법' 및 '화재예방법' 개정안 패키지 발의"
    desc = "항만·발전소 등 대형 기반시설 중심이며, 폭발 위험이 큰 물질을 다루는 시설이 두 제도 모두에서 빠질 수 있는 구조다."
    result = classify(title, desc)
    assert result["classification"] == "LAW_POLICY", result


def test_roundup_article_with_only_description_hits_goes_to_other():
    title = "31.5점을 100점으로 적은 선관위, 특검이 서버에 들어갔다"
    desc = "한편 정의당은 한솔제지 장항공장 끼임 사고로 숨진 노동자를 추모하며 회사의 책임 규명을 요구했다. 반도체 초호황으로 3%대 후반 성장이 예상되는데 과실이 고루 돌아가지 않는다는 진단."
    result = classify(title, desc)
    assert result["classification"] == "OTHER", result


def test_known_good_incident_report_unaffected():
    title = "잇따른 설비 고장에 멈춰선 한국지엠 부평공장…노후화 문제 재부각"
    desc = "지난해에는 1995년 설치된 5000t급 프레스의 샤프트가 금속 피로 누적으로 절단된 것으로 추정되는 사고가 발생했다."
    result = classify(title, desc)
    assert result["classification"] == "INCIDENT_REPORT", result


def test_known_good_followup_with_title_evidence_unaffected():
    title = "한국지엠 부평공장 설비 고장 사고, 노후화 책임자 과실 조사"
    desc = "경찰은 사고 원인을 조사 중이다."
    result = classify(title, desc)
    assert result["classification"] == "INCIDENT_FOLLOWUP", result


def test_law_bill_with_truncated_title_caught_via_description():
    # 2026-11-18 Task7 실운영 실데이터: Naver API가 제목을 "...추..."로 잘라
    # "발의"가 사라져서 title-only LAW_TITLE 검사가 못 잡았던 사례. description까지
    # 보도록 확장한 수정이 이 케이스를 잡는지 확인.
    title = "원전 사고 '은폐 사각지대' 막는다…종업원·교사·공모자까지 처벌 추..."
    desc = "원전 사고 은폐를 막기 위해 종업원뿐 아니라 교사·공모자까지 처벌할 수 있도록 하는 법안이 발의됐다. 2012년 고리1호기 사건과 2024년 월성4호기 사례가 배경으로 꼽힌다."
    result = classify(title, desc)
    assert result["classification"] == "LAW_POLICY", result


def test_primary_sector_article_now_excluded_at_1b():
    # 2026-11-18 당시엔 이 기사(보험상품 소개가 "보상" 단어로 INCIDENT_FOLLOWUP에 걸림)를
    # 1b에서 더 패치하지 않고 Task 4(AI)가 교정하도록 뒀었다. 2026-11-20 5차(1차산업/운송업
    # 제외)로 PRIMARY_SECTOR_CONTEXT("농업")가 추가되면서, 이제는 1b 단계에서 바로
    # EXCLUDED된다 — task-01b-news-classify.md 5차의 명시적 검증 기준이기도 하다.
    title = "농업도 일터다... NH농협생명이 메우는 산재 안전망의 빈자리"
    desc = "NH농협생명이 자영농·가족종사자 대상 산재 안전망의 빈자리를 보완하는 보험·보상 체계를 소개."
    result = classify(title, desc)
    assert result["classification"] == "EXCLUDED", result


def test_pure_traffic_accident_not_excluded_at_1b_by_design():
    # 2026-11-20 실사례: "안전상황실" 일일 칼럼(순수 교통사고 한 줄 + 무관한 과거 재난
    # 나열)이 "숨져" 키워드만으로 INCIDENT_REPORT가 돼 실제 발송까지 샌 사건. "트럭"을
    # TRANSPORT_CONTEXT에 추가하는 방안은 건설현장 트럭 사고를 잘못 제외할 위험이 있어
    # 기각(사용자 결정) — 1b는 업종 단위 큰 틀 블랙리스트만 맡고, 이런 경계 사례는
    # Task 4(2차, 맥락 이해 재분류)가 처리한다. 이 테스트는 "1b는 의도적으로 이 케이스를
    # 그대로 통과시킨다"는 현재 설계를 문서화한다 — task-04-deepseek-summarize.md의
    # 보호 규칙 정교화(비산업 사건 재분류)가 이 역할을 대신 맡는다.
    title = "[안전상황실·19일] 전주서 도로 건너던 60대 트럭에 치여 숨져"
    desc = "사고는 위험물 저장시설과 주거지역 사이의 안전거리 확보, 가스 누출 감지와 긴급차단 체계의 중요성을 보여주는 대표적인 산업재해로 기록됐다."
    result = classify(title, desc)
    assert result["classification"] in ("INCIDENT_REPORT", "INCIDENT_FOLLOWUP"), result


if __name__ == "__main__":
    test_law_bill_not_misread_as_incident()
    test_roundup_article_with_only_description_hits_goes_to_other()
    test_known_good_incident_report_unaffected()
    test_known_good_followup_with_title_evidence_unaffected()
    test_law_bill_with_truncated_title_caught_via_description()
    test_primary_sector_article_now_excluded_at_1b()
    test_pure_traffic_accident_not_excluded_at_1b_by_design()
    print("OK")
