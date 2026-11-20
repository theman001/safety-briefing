#!/usr/bin/env python3
"""fulltext_fetch.py 핵심 로직(HTMLParser 기반 본문 추출, charset 감지) self-check. 네트워크 호출 없음."""
from fulltext_fetch import detect_charset, extract_full_text


def test_extract_full_text_naver_pattern():
    doc = '<html><body><article><div id="dic_area" class="go_trans">첫째 문단. <b>둘째</b> 문단.</div></article></body></html>'
    text, source = extract_full_text(doc)
    assert source == "naver_dic_area"
    assert text == "첫째 문단. 둘째 문단."


def test_extract_full_text_common_cms_pattern():
    doc = '<div id="article-view-content-div">본문 내용 &amp; 특수문자.</div></div>'
    text, source = extract_full_text(doc)
    assert source == "common_cms"
    assert text == "본문 내용 & 특수문자."


def test_extract_full_text_no_match_falls_back():
    doc = "<html><body><p>알 수 없는 구조</p></body></html>"
    text, source = extract_full_text(doc)
    assert text is None
    assert source == "fallback_description"


def test_extract_full_text_strips_script_and_style():
    doc = ('<article><div id="dic_area">본문 시작.'
           '<script>var x = 1;</script><style>.a{color:red}</style>'
           '본문 끝.</div></article>')
    text, source = extract_full_text(doc)
    assert source == "naver_dic_area"
    assert "var x" not in text and "color:red" not in text
    assert text == "본문 시작. 본문 끝."


def test_extract_full_text_survives_leading_photo_caption_nested_divs():
    # 2026-11-20 실데이터 버그: 본문이 사진 캡션(figure > div > div)으로 시작하면
    # 정규식 방식은 그 안의 첫 </div></div>에서 조기 종료됐음("NH농협생명" 기사 12자만
    # 추출). HTMLParser는 깊이를 추적하므로 진짜 짝 맞는 바깥쪽 닫는 태그까지 읽어야 함.
    doc = (
        '<div id="article-view-content-div">'
        '<div style="text-align:center">'
        '<figure><div class="IMGFLOATING"><div class="IMGFLOATING">'
        '<img alt="사진=출처" src="x.jpg"/>'
        '</div></div></figure>'
        '</div>'
        '진짜 본문은 사진 캡션 뒤에 이어진다.'
        '</div></div>'
    )
    text, source = extract_full_text(doc)
    assert source == "common_cms"
    assert "진짜 본문은 사진 캡션 뒤에 이어진다." in text
    assert len(text) > len("사진=출처")


def test_extract_full_text_excludes_comment_content():
    # 2026-11-20 실데이터 버그: 본문 앞 HTML 주석 안쪽 텍스트가 태그제거 정규식의
    # 허점으로 새어나오고 주석을 닫는 "-->"만 글자로 남았음("강진군" 기사). HTMLParser는
    # 주석을 handle_data가 아니라 handle_comment로 받으므로 아예 수집되지 않아야 한다.
    doc = (
        '<div id="dic_area">'
        '<!-- <div class="article-head-sub">숨겨진 캡션</div> -->'
        '진짜 본문.'
        '</div></article>'
    )
    text, source = extract_full_text(doc)
    assert source == "naver_dic_area"
    assert "숨겨진 캡션" not in text
    assert "-->" not in text
    assert text == "진짜 본문."


def test_detect_charset_from_content_type_header():
    assert detect_charset("text/html; charset=EUC-KR", b"") == "EUC-KR"


def test_detect_charset_from_meta_tag():
    body = b'<html><head><meta charset="utf-8"></head></html>'
    assert detect_charset("text/html", body) == "utf-8"


def test_detect_charset_default_utf8():
    assert detect_charset("text/html", b"<html></html>") == "utf-8"


if __name__ == "__main__":
    test_extract_full_text_naver_pattern()
    test_extract_full_text_common_cms_pattern()
    test_extract_full_text_no_match_falls_back()
    test_extract_full_text_strips_script_and_style()
    test_extract_full_text_survives_leading_photo_caption_nested_divs()
    test_extract_full_text_excludes_comment_content()
    test_detect_charset_from_content_type_header()
    test_detect_charset_from_meta_tag()
    test_detect_charset_default_utf8()
    print("OK")
