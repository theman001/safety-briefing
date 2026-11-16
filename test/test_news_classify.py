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


if __name__ == "__main__":
    test_law_bill_not_misread_as_incident()
    test_roundup_article_with_only_description_hits_goes_to_other()
    test_known_good_incident_report_unaffected()
    test_known_good_followup_with_title_evidence_unaffected()
    print("OK")
