#!/usr/bin/env python3
"""telegram_send.py 포맷터/분할 로직 self-check. 네트워크 호출 없음."""
from telegram_send import article_block, build_sections, chunk_blocks, to_messages


def test_article_block_omits_null_fields():
    s = {"title": "제목", "industry": "농업", "incident_type": None, "key_facts": "사실",
         "probable_cause": None, "maintenance_lesson": None, "needs_review": False, "link": "http://x"}
    block = article_block(1, s)
    assert "🔧" not in block
    assert "💡" not in block
    assert "확인되지 않음(조사 중)" in block


def test_article_block_marks_needs_review():
    s = {"title": "제목", "industry": "철강", "incident_type": "화재", "key_facts": "사실",
         "probable_cause": "원인", "maintenance_lesson": "교훈", "needs_review": True, "link": "http://x"}
    block = article_block(1, s)
    assert "⚠️ 검토 필요" in block
    assert "🔧 화재" in block
    assert "💡 교훈: 교훈" in block


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


if __name__ == "__main__":
    test_article_block_omits_null_fields()
    test_article_block_marks_needs_review()
    test_chunk_blocks_splits_at_article_boundary()
    test_chunk_blocks_fits_when_under_limit()
    test_build_sections_groups_by_classification_and_skips_empty()
    test_to_messages_numbers_chunks_only_when_multiple()
    print("OK")
