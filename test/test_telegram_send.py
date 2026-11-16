#!/usr/bin/env python3
"""telegram_send.py 포맷터/분할 로직 self-check. 네트워크 호출 없음."""
from telegram_send import article_block, assessment_block, build_sections, chunk_blocks, load_assessment, to_messages


def test_article_block_omits_null_fields():
    s = {"title": "제목", "industry": "농업", "incident_type": None, "key_facts": "사실",
         "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "http://x"}
    block = article_block(1, s)
    assert "🔧" not in block
    assert "💡" not in block
    assert "확인되지 않음(조사 중)" in block


def test_article_block_omits_needs_review_tag():
    # 사용자 피드백(2026-11-16): "검토필요" 표시 때문에 제목이 잘리는 느낌 -> 표시 삭제
    s = {"title": "제목", "industry": "철강", "incident_type": "화재", "key_facts": "사실",
         "probable_cause": "원인", "maintenance_lesson": "교훈", "needs_review": True, "link": "http://x"}
    block = article_block(1, s)
    assert "검토 필요" not in block
    assert "🔧 <b>화재</b>" in block
    assert "💡 <b>교훈:</b> 교훈" in block


def test_article_block_handles_null_industry_and_key_facts():
    # 실제 데이터에서 발견된 버그: SAFETY_TREND 기사는 industry가 null일 수 있는데
    # _esc(None)이 그대로 크래시했음 — fallback 텍스트로 처리돼야 함
    s = {"title": "제목", "industry": None, "incident_type": None, "key_facts": None,
         "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "http://x"}
    block = article_block(1, s)
    assert "업종 미확인" in block
    assert "세부 사실 확인 전" in block


def test_article_block_escapes_html_special_chars():
    # HTML parse_mode에서 <, >, &가 이스케이프 안 되면 "can't parse entities"로 전송 거부됨
    s = {"title": "S&OIL <위험>", "industry": "농업", "incident_type": None, "key_facts": "f",
         "probable_cause": None, "maintenance_lesson": None, "needs_review": False,
         "link": "http://x?a=1&b=2"}
    block = article_block(1, s)
    assert "S&amp;OIL &lt;위험&gt;" in block
    assert "href=\"http://x?a=1&amp;b=2\"" in block
    assert "<위험>" not in block  # 원문 그대로 노출되면 안 됨(파싱 에러 유발)


def test_article_block_does_not_escape_quotes_in_body_text():
    # 실제로 발견된 버그: html.escape(quote=True) 기본값이 본문의 "/'를 &quot;/&#x27;로
    # 바꿨는데, 텔레그램이 본문에서 이걸 안정적으로 디코드하지 않아 글자 그대로 노출됐었음.
    s = {"title": '"2월 수로" 오염', "industry": "화학", "incident_type": None, "key_facts": "f",
         "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "http://x"}
    block = article_block(1, s)
    assert '"2월 수로" 오염' in block
    assert "&quot;" not in block


def test_chunk_blocks_splits_at_article_boundary():
    blocks = ["A" * 3000, "B" * 2000]  # 합치면 5000+ > 4096, 블록 하나씩은 넘지 않음
    chunks = chunk_blocks(blocks, limit=4096)
    assert len(chunks) == 2
    assert chunks[0] == ["A" * 3000]
    assert chunks[1] == ["B" * 2000]
    assert all("".join(c)[:1] != "" for c in chunks)  # 블록이 잘리지 않고 통째로 들어감


def test_chunk_blocks_fits_when_under_limit():
    blocks = ["X" * 100, "Y" * 100]
    chunks = chunk_blocks(blocks, limit=4096)
    assert len(chunks) == 1
    assert chunks[0] == blocks


def test_build_sections_groups_by_classification_and_skips_empty():
    summaries = [
        {"title": "사고1", "classification": "INCIDENT_REPORT", "industry": "A", "incident_type": "화재",
         "key_facts": "f", "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "l"},
        {"title": "동향1", "classification": "LAW_POLICY", "industry": "B", "incident_type": None,
         "key_facts": "f", "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "l"},
        {"title": "제외됨", "classification": "OTHER", "industry": "C", "incident_type": None,
         "key_facts": "f", "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "l"},
    ]
    sections = build_sections(summaries, "2026-11-12")
    assert [s["title_base"] for s in sections] == [
        "🚨 오늘의 사고 (2026-11-12, 1건)",
        "📊 안전동향·정비기술 (2026-11-12, 1건)",
    ]
    assert "사고1" in sections[0]["chunks"][0]
    assert "동향1" in sections[1]["chunks"][0]
    assert "제외됨" not in sections[0]["chunks"][0] and "제외됨" not in sections[1]["chunks"][0]


def test_to_messages_numbers_chunks_only_when_multiple():
    sections = [{"title_base": "오늘의 사고 (d, 1건)", "chunks": ["body"]}]
    messages = to_messages(sections)
    assert messages == [{"title": "오늘의 사고 (d, 1건)", "body": "body"}]

    sections = [{"title_base": "오늘의 사고 (d, 2건)", "chunks": ["body1", "body2"]}]
    messages = to_messages(sections)
    assert messages[0]["title"] == "오늘의 사고 (d, 2건) (1/2)"
    assert messages[1]["title"] == "오늘의 사고 (d, 2건) (2/2)"


def test_assessment_block_renders_lists_and_fallback_when_empty():
    data = {"risk_level": "주의", "risk_reason": "강풍", "cross_insights": [],
            "key_warnings": [{"subject": "설비1", "detail": "경고1"}], "closing_message": "조심"}
    block = assessment_block(data)
    assert "🌡️ <b>위험지수</b>\n<code>주의</code> — 강풍" in block  # 소제목 느낌으로 줄바꿈
    assert "(해당 없음)" in block  # cross_insights 비어서 fallback
    assert "- <b>설비1</b>\n &gt; 경고1" in block  # 대상/내용 들여쓰기 2줄 (사용자 지정: " >" 접두)
    assert "<blockquote>☔️ <b>오늘의 한마디</b>\n조심</blockquote>" in block


def test_assessment_block_key_warnings_fallback_when_empty():
    data = {"risk_level": "관심", "risk_reason": "x", "cross_insights": [], "key_warnings": [], "closing_message": "x"}
    block = assessment_block(data)
    assert "- (해당 없음)" in block


def test_assessment_block_escapes_html_special_chars():
    data = {"risk_level": "주의", "risk_reason": "기온 > 33도 & 강풍", "cross_insights": ["A<B"],
             "key_warnings": [], "closing_message": "x"}
    block = assessment_block(data)
    assert "기온 &gt; 33도 &amp; 강풍" in block
    assert "A&lt;B" in block
    assert "A<B" not in block


def test_load_assessment_none_when_missing_file(tmp_path):
    assert load_assessment(str(tmp_path), "2026-11-16") is None


def test_load_assessment_none_when_skipped(tmp_path):
    import json
    p = tmp_path / "comprehensive_assessment_2026-11-16.json"
    p.write_text(json.dumps({"skipped": True}), encoding="utf-8")
    assert load_assessment(str(tmp_path), "2026-11-16") is None


def test_load_assessment_returns_data_when_valid(tmp_path):
    import json
    data = {"skipped": False, "risk_level": "관심", "closing_message": "x"}
    p = tmp_path / "comprehensive_assessment_2026-11-16.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_assessment(str(tmp_path), "2026-11-16")
    assert loaded == data


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    test_article_block_omits_null_fields()
    test_article_block_omits_needs_review_tag()
    test_article_block_handles_null_industry_and_key_facts()
    test_article_block_escapes_html_special_chars()
    test_article_block_does_not_escape_quotes_in_body_text()
    test_chunk_blocks_splits_at_article_boundary()
    test_chunk_blocks_fits_when_under_limit()
    test_build_sections_groups_by_classification_and_skips_empty()
    test_to_messages_numbers_chunks_only_when_multiple()
    test_assessment_block_renders_lists_and_fallback_when_empty()
    test_assessment_block_key_warnings_fallback_when_empty()
    test_assessment_block_escapes_html_special_chars()
    with tempfile.TemporaryDirectory() as d:
        test_load_assessment_none_when_missing_file(Path(d))
        test_load_assessment_none_when_skipped(Path(d))
        test_load_assessment_returns_data_when_valid(Path(d))
    print("OK")
