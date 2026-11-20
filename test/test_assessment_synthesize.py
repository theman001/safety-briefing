#!/usr/bin/env python3
"""assessment_synthesize.py 핵심 로직 self-check. 네트워크 호출 없음."""
import json

from assessment_synthesize import apply_official_floor, build_request_payload, parse_assessment


def _fake_response(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}


def test_parse_assessment_accepts_valid_response():
    content = {
        "risk_level": "주의", "risk_reason": "강풍",
        "key_warnings": [{"subject": "설비1", "reason": "근거1", "action": "조치1"}],
        "closing_message": "오늘의 한마디",
    }
    result = parse_assessment(_fake_response(content))
    assert result["risk_level"] == "주의"
    assert result["key_warnings"] == [{"subject": "설비1", "reason": "근거1", "action": "조치1"}]
    assert "cross_insights" not in result


def test_parse_assessment_rejects_key_warning_without_subject():
    content = {"risk_level": "관심", "risk_reason": "x",
               "key_warnings": [{"reason": "경고1", "action": "조치1"}], "closing_message": "x"}
    try:
        parse_assessment(_fake_response(content))
        assert False, "에러가 나야 함"
    except RuntimeError:
        pass


def test_parse_assessment_rejects_key_warning_without_action():
    content = {"risk_level": "관심", "risk_reason": "x",
               "key_warnings": [{"subject": "설비1", "reason": "경고1"}], "closing_message": "x"}
    try:
        parse_assessment(_fake_response(content))
        assert False, "에러가 나야 함"
    except RuntimeError:
        pass


def test_parse_assessment_rejects_invalid_risk_level():
    content = {"risk_level": "매우위험", "risk_reason": "x", "key_warnings": [], "closing_message": "x"}
    try:
        parse_assessment(_fake_response(content))
        assert False, "에러가 나야 함"
    except RuntimeError:
        pass


def test_parse_assessment_rejects_missing_closing_message():
    content = {"risk_level": "관심", "risk_reason": "x", "key_warnings": [], "closing_message": ""}
    try:
        parse_assessment(_fake_response(content))
        assert False, "에러가 나야 함"
    except RuntimeError:
        pass


def test_apply_official_floor_forces_warning_level():
    result = {"risk_level": "관심", "risk_reason": "날씨 평이함", "key_warnings": [], "closing_message": "x"}
    out = apply_official_floor(result, ["강풍주의보", "풍랑주의보"])
    assert out["risk_level"] == "경고"
    assert "강풍주의보·풍랑주의보" in out["risk_reason"]
    assert "날씨 평이함" in out["risk_reason"]


def test_apply_official_floor_noop_when_no_active_warnings():
    result = {"risk_level": "관심", "risk_reason": "날씨 평이함", "key_warnings": [], "closing_message": "x"}
    out = apply_official_floor(result, [])
    assert out == result


def test_build_request_payload_splits_incidents_and_trends():
    weather = {"summary": {"temp_max": 10}, "official_warnings": {"active": ["강풍주의보"]}}
    incidents = [{"industry": "철강", "incident_type": "화재", "key_facts": "f", "probable_cause": "c"}]
    trends = [{"industry": "발전소", "key_facts": "f2", "maintenance_lesson": "m"}]
    payload = build_request_payload(weather, incidents, trends)
    body = json.loads(payload["messages"][1]["content"])
    assert body["today_incidents"][0]["industry"] == "철강"
    assert body["today_trends"][0]["maintenance_lesson"] == "m"
    assert body["official_warnings_active"] == ["강풍주의보"]


if __name__ == "__main__":
    test_parse_assessment_accepts_valid_response()
    test_parse_assessment_rejects_key_warning_without_subject()
    test_parse_assessment_rejects_key_warning_without_action()
    test_parse_assessment_rejects_invalid_risk_level()
    test_parse_assessment_rejects_missing_closing_message()
    test_apply_official_floor_forces_warning_level()
    test_apply_official_floor_noop_when_no_active_warnings()
    test_build_request_payload_splits_incidents_and_trends()
    print("OK")
