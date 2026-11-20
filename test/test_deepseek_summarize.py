#!/usr/bin/env python3
"""deepseek_summarize.py 핵심 로직(페이로드 구성, 응답 파싱, dropped 분리) self-check. 네트워크 호출 없음."""
import json
import tempfile
from pathlib import Path

from deepseek_summarize import MODEL, build_request_payload, parse_summaries, resolve_input_path, split_dropped


def test_build_request_payload_shape():
    articles = [{"title": "a", "description": "b", "classification": "INCIDENT_REPORT", "matched_industry_terms": ["철강"], "stat_context": None}]
    payload = build_request_payload(articles)
    assert payload["model"] == MODEL
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] >= 8192
    user_content = json.loads(payload["messages"][1]["content"])
    assert user_content[0]["index"] == 0
    assert user_content[0]["title"] == "a"
    assert user_content[0]["full_text"] is None  # 2026-11-20: Task3b 안 거친 기사는 키 없어도 안전하게 null


def test_build_request_payload_includes_full_text_when_present():
    articles = [{"title": "a", "description": "짧은 요약", "full_text": "원문 전체 내용...", "classification": "INCIDENT_REPORT"}]
    payload = build_request_payload(articles)
    user_content = json.loads(payload["messages"][1]["content"])
    assert user_content[0]["full_text"] == "원문 전체 내용..."
    assert user_content[0]["description"] == "짧은 요약"  # full_text가 있어도 description은 유지(폴백 대비)


def test_parse_summaries_matches_by_index_and_preserves_original_fields():
    articles = [
        {"title": "t0", "link": "l0", "classification": "C0"},
        {"title": "t1", "link": "l1", "classification": "C1"},
    ]
    response = {"choices": [{"message": {"content": json.dumps({
        "summaries": [
            {"index": 1, "classification": "SAFETY_TREND", "dropped": False, "drop_reason": None, "industry": "i1", "incident_type": "e1", "key_facts": "k1", "probable_cause": None, "maintenance_lesson": "m1", "needs_review": True},
            {"index": 0, "classification": "INCIDENT_REPORT", "dropped": False, "drop_reason": None, "industry": "i0", "incident_type": "e0", "key_facts": "k0", "probable_cause": "c0", "maintenance_lesson": "m0", "needs_review": False},
        ]
    })}}]}
    result = parse_summaries(response, articles)
    assert result[0]["title"] == "t0"
    assert result[0]["industry"] == "i0"
    assert result[1]["title"] == "t1"
    assert result[1]["needs_review"] is True


def test_parse_summaries_uses_ai_corrected_classification():
    # 2026-11-18: 1b의 classification은 참고용 추정치일 뿐, AI가 본문 맥락으로 교정한
    # 값을 최종으로 써야 한다 (키워드 과매칭으로 INCIDENT_FOLLOWUP으로 잘못 왔던 보험
    # 상품 기사를 AI가 SAFETY_TREND로 교정하는 실제 사례를 본떠 구성).
    articles = [{"title": "보험 기사", "link": "l0", "classification": "INCIDENT_FOLLOWUP"}]
    response = {"choices": [{"message": {"content": json.dumps({
        "summaries": [
            {"index": 0, "classification": "SAFETY_TREND", "dropped": False, "drop_reason": None,
             "industry": None, "incident_type": None, "key_facts": "k", "probable_cause": None,
             "maintenance_lesson": None, "needs_review": False},
        ]
    })}}]}
    result = parse_summaries(response, articles)
    assert result[0]["classification"] == "SAFETY_TREND"


def test_parse_summaries_falls_back_to_original_classification_when_ai_value_invalid():
    # AI가 허용된 5개 라벨 밖의 값을 반환하거나 비워두면, 조용히 버리지 않고 1b 원본값으로
    # 폴백해야 한다(사실 확인 안 된 값을 침묵 수용하지 않는다는 프로젝트 원칙).
    articles = [{"title": "t0", "link": "l0", "classification": "INCIDENT_REPORT"}]
    response = {"choices": [{"message": {"content": json.dumps({
        "summaries": [
            {"index": 0, "classification": "NOT_A_REAL_LABEL", "dropped": False, "drop_reason": None,
             "industry": None, "incident_type": None, "key_facts": "k", "probable_cause": None,
             "maintenance_lesson": None, "needs_review": False},
        ]
    })}}]}
    result = parse_summaries(response, articles)
    assert result[0]["classification"] == "INCIDENT_REPORT"


def test_parse_summaries_detects_count_mismatch():
    articles = [{"title": "t0"}, {"title": "t1"}]
    response = {"choices": [{"message": {"content": json.dumps({"summaries": [
        {"index": 0, "dropped": False, "drop_reason": None, "industry": "i0", "incident_type": None, "key_facts": "k", "probable_cause": None, "maintenance_lesson": None, "needs_review": False},
    ]})}}]}
    try:
        parse_summaries(response, articles)
    except RuntimeError:
        pass
    else:
        raise AssertionError("건수 불일치를 감지하지 못함")


def test_resolve_input_path_prefers_enriched_when_present():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "daily_briefing_2026-11-19.json").write_text("{}")
        (d / "daily_briefing_enriched_2026-11-19.json").write_text("{}")
        assert resolve_input_path(d, "2026-11-19").name == "daily_briefing_enriched_2026-11-19.json"
        assert resolve_input_path(d, None).name == "daily_briefing_enriched_2026-11-19.json"


def test_resolve_input_path_falls_back_to_plain_when_no_enriched():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "daily_briefing_2026-11-19.json").write_text("{}")
        assert resolve_input_path(d, "2026-11-19").name == "daily_briefing_2026-11-19.json"
        assert resolve_input_path(d, None).name == "daily_briefing_2026-11-19.json"


def test_resolve_input_path_returns_none_when_nothing_exists():
    with tempfile.TemporaryDirectory() as d:
        assert resolve_input_path(Path(d), None) is None


def test_split_dropped_separates_and_strips_fields():
    results = [
        {"title": "t0", "link": "l0", "classification": "C0", "dropped": False, "drop_reason": None,
         "industry": "i0", "incident_type": "e0", "key_facts": "k0", "probable_cause": None,
         "maintenance_lesson": None, "needs_review": False},
        {"title": "t1", "link": "l1", "classification": "C1", "dropped": True, "drop_reason": "중복 (index 0과 동일 사건)",
         "industry": None, "incident_type": None, "key_facts": None, "probable_cause": None,
         "maintenance_lesson": None, "needs_review": False},
    ]
    kept, dropped = split_dropped(results)
    assert len(kept) == 1 and kept[0]["title"] == "t0"
    assert "dropped" not in kept[0] and "drop_reason" not in kept[0]
    assert len(dropped) == 1
    assert dropped[0] == {"title": "t1", "link": "l1", "classification": "C1", "drop_reason": "중복 (index 0과 동일 사건)"}


if __name__ == "__main__":
    test_build_request_payload_shape()
    test_build_request_payload_includes_full_text_when_present()
    test_parse_summaries_matches_by_index_and_preserves_original_fields()
    test_parse_summaries_uses_ai_corrected_classification()
    test_parse_summaries_falls_back_to_original_classification_when_ai_value_invalid()
    test_parse_summaries_detects_count_mismatch()
    test_resolve_input_path_prefers_enriched_when_present()
    test_resolve_input_path_falls_back_to_plain_when_no_enriched()
    test_resolve_input_path_returns_none_when_nothing_exists()
    test_split_dropped_separates_and_strips_fields()
    print("OK")
