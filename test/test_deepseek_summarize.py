#!/usr/bin/env python3
"""deepseek_summarize.py 핵심 로직(페이로드 구성, 응답 파싱, dropped 분리) self-check. 네트워크 호출 없음."""
import json

from deepseek_summarize import MODEL, build_request_payload, parse_summaries, split_dropped


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


def test_parse_summaries_matches_by_index_and_preserves_original_fields():
    articles = [
        {"title": "t0", "link": "l0", "classification": "C0"},
        {"title": "t1", "link": "l1", "classification": "C1"},
    ]
    response = {"choices": [{"message": {"content": json.dumps({
        "summaries": [
            {"index": 1, "dropped": False, "drop_reason": None, "industry": "i1", "incident_type": "e1", "key_facts": "k1", "probable_cause": None, "maintenance_lesson": "m1", "needs_review": True},
            {"index": 0, "dropped": False, "drop_reason": None, "industry": "i0", "incident_type": "e0", "key_facts": "k0", "probable_cause": "c0", "maintenance_lesson": "m0", "needs_review": False},
        ]
    })}}]}
    result = parse_summaries(response, articles)
    assert result[0]["title"] == "t0"
    assert result[0]["industry"] == "i0"
    assert result[1]["title"] == "t1"
    assert result[1]["needs_review"] is True


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
    test_parse_summaries_matches_by_index_and_preserves_original_fields()
    test_parse_summaries_detects_count_mismatch()
    test_split_dropped_separates_and_strips_fields()
    print("OK")
