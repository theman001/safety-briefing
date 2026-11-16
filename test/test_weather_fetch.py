#!/usr/bin/env python3
"""weather_fetch.py 핵심 로직 self-check. 네트워크 호출 없음."""
from datetime import datetime, timezone, timedelta

from weather_fetch import base_time_candidates, parse_warnings, summarize_vilage

KST = timezone(timedelta(hours=9))


def test_base_time_candidates_picks_latest_announced():
    now = datetime(2026, 11, 16, 8, 5, tzinfo=KST)  # cron 실행 시각, 08시 회차는 아직 안 나옴
    top = base_time_candidates(now)[0]
    assert top == ("20261116", "0500")


def test_base_time_candidates_rolls_back_past_midnight():
    now = datetime(2026, 11, 16, 0, 30, tzinfo=KST)  # 02시 회차도 아직 안 나온 새벽
    top = base_time_candidates(now)[0]
    assert top == ("20261115", "2300")


def test_base_time_candidates_just_after_announce():
    now = datetime(2026, 11, 16, 14, 25, tzinfo=KST)  # 14:10 제공 직후
    top = base_time_candidates(now)[0]
    assert top == ("20261116", "1400")


def test_summarize_vilage_filters_today_and_aggregates():
    items = [
        {"fcstDate": "20261116", "category": "TMP", "fcstValue": "2"},
        {"fcstDate": "20261116", "category": "TMP", "fcstValue": "11"},
        {"fcstDate": "20261116", "category": "REH", "fcstValue": "70"},
        {"fcstDate": "20261116", "category": "POP", "fcstValue": "30"},
        {"fcstDate": "20261116", "category": "WSD", "fcstValue": "5.2"},
        {"fcstDate": "20261116", "category": "SKY", "fcstValue": "1"},
        {"fcstDate": "20261116", "category": "SKY", "fcstValue": "3"},
        {"fcstDate": "20261116", "category": "PTY", "fcstValue": "0"},
        {"fcstDate": "20261117", "category": "TMP", "fcstValue": "99"},  # 내일 데이터, 제외돼야 함
    ]
    summary, count = summarize_vilage(items, "20261116")
    assert count == 8
    assert summary == {
        "temp_min": 2, "temp_max": 11, "humidity_max": 70, "precip_prob_max": 30,
        "wind_speed_max": 5.2, "sky": ["맑음", "구름많음"], "precip_type": ["없음"],
    }


def test_summarize_vilage_empty_when_no_data_for_date():
    summary, count = summarize_vilage([{"fcstDate": "20261117", "category": "TMP", "fcstValue": "5"}], "20261116")
    assert count == 0
    assert summary["temp_min"] is None


def test_parse_warnings_latest_action_wins_per_phenomenon():
    items = [
        {"tmFc": 202611150130, "title": "[특보] 제11-10호 : 2026.11.15.01:30 / 강풍주의보 발표 (*)"},
        {"tmFc": 202611160700, "title": "[특보] 제11-11호 : 2026.11.16.07:00 / 강풍주의보 해제 (*)"},
        {"tmFc": 202611161800, "title": "[특보] 제11-20호 : 2026.11.16.18:00 / 풍랑주의보 발표 (*)"},
    ]
    active, unparsed = parse_warnings(items)
    assert active == ["풍랑주의보"]  # 강풍주의보는 이후 해제돼서 빠짐
    assert unparsed == []


def test_parse_warnings_splits_multiple_phenomena_and_keeps_unparsed():
    items = [
        {"tmFc": 202611160130, "title": "[특보] 제11-86호 : 2026.11.16.01:30 / 강풍주의보·풍랑주의보 발표 (*)"},
        {"tmFc": 202611161900, "title": "형식이 다른 제목"},
    ]
    active, unparsed = parse_warnings(items)
    assert active == ["강풍주의보", "풍랑주의보"]
    assert unparsed == ["형식이 다른 제목"]


def test_parse_warnings_flags_same_name_conflicting_action_as_unparsed():
    # 실제 stnId=159 응답에서 나온 형식: 해역별로 한쪽은 해제·다른 쪽은 변경인데
    # 구역 구분이 title에 없어 어느 쪽이 우리 지역인지 알 수 없음 -> 추측하지 않고 보존.
    items = [{"tmFc": 202611100900, "title": "[특보] 제11-16호 : 2026.11.10.09:00 / 풍랑주의보 해제·풍랑주의보 변경 (*)"}]
    active, unparsed = parse_warnings(items)
    assert active == []
    assert len(unparsed) == 1


if __name__ == "__main__":
    test_base_time_candidates_picks_latest_announced()
    test_base_time_candidates_rolls_back_past_midnight()
    test_base_time_candidates_just_after_announce()
    test_summarize_vilage_filters_today_and_aggregates()
    test_summarize_vilage_empty_when_no_data_for_date()
    test_parse_warnings_latest_action_wins_per_phenomenon()
    test_parse_warnings_splits_multiple_phenomena_and_keeps_unparsed()
    test_parse_warnings_flags_same_name_conflicting_action_as_unparsed()
    print("OK")
