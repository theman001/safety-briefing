#!/usr/bin/env python3
"""Task 3b: daily_briefing_<date>.json의 각 기사에 원문 전체(full_text)를 덧붙인다.

Python 3.9+, 표준 라이브러리만 사용. docs/03_tasks/task-03b-fulltext-fetch.md 참고.
공식 API가 아니라 언론사 웹페이지를 직접 GET해서 알려진 2개 패턴(Naver dic_area,
공통 CMS article-view-content-div)만 추출 시도한다 — 안 맞으면 description으로 폴백.

사용법:
    python3 test/fulltext_fetch.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
USER_AGENT = "safety-briefing-fulltext-fetch/3b"

# 2026-11-20: 정규식 경계 매칭(`</div>\s*</div>`)이 기사 본문이 사진/캡션으로 시작할 때
# 중첩 div에서 조기 종료되는 버그, HTML 주석 안쪽 텍스트가 새어나오는 버그가 실데이터로
# 확인됨(task-03b-fulltext-fetch.md 검증기록 참고) — 태그 depth를 제대로 추적하는
# HTMLParser로 교체. 두 사이트 템플릿의 본문 컨테이너 id.
TARGET_IDS = {"dic_area": "naver_dic_area", "article-view-content-div": "common_cms"}
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
WS_RE = re.compile(r'\s+')
CHARSET_RE = re.compile(rb'charset=["\']?([\w-]+)', re.I)


class _ArticleBodyExtractor(HTMLParser):
    """목표 id를 가진 요소의 텍스트만, 짝이 맞는 닫는 태그까지 정확히 추적해 수집한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.collecting = False
        self.collect_marker = -1
        self.skip_tag: str | None = None
        self.text_parts: list[str] = []
        self.active_source: str | None = None
        self.done = False

    def handle_starttag(self, tag, attrs):
        if not self.done and not self.collecting:
            attr_id = dict(attrs).get("id")
            if attr_id in TARGET_IDS:
                self.collecting = True
                self.collect_marker = len(self.stack)
                self.active_source = TARGET_IDS[attr_id]
        if self.collecting:
            self.text_parts.append(" ")  # 태그 경계에 공백 — 인접 텍스트가 붙어버리는 것 방지
        if self.collecting and tag in ("script", "style") and self.skip_tag is None:
            self.skip_tag = tag
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return  # self-closed void 태그(<img .../>)는 handle_starttag에서 push 안 했으므로 pop도 안 함
        if self.skip_tag == tag:
            self.skip_tag = None
        if self.stack:
            self.stack.pop()
        if self.collecting:
            self.text_parts.append(" ")
            if len(self.stack) == self.collect_marker:
                self.collecting = False
                self.done = True

    def handle_data(self, data):
        if self.collecting and self.skip_tag is None:
            self.text_parts.append(data)


def extract_full_text(html_doc: str) -> tuple[str | None, str]:
    parser = _ArticleBodyExtractor()
    try:
        parser.feed(html_doc)
    except Exception:
        return None, "fallback_description"
    if not parser.text_parts:
        return None, "fallback_description"
    text = WS_RE.sub(" ", "".join(parser.text_parts)).strip()
    if not text:
        return None, "fallback_description"
    return text, parser.active_source


def detect_charset(content_type: str, body: bytes) -> str:
    m = re.search(r'charset=([\w-]+)', content_type, re.I)
    if m:
        return m.group(1)
    m = CHARSET_RE.search(body[:2000])
    if m:
        return m.group(1).decode("ascii", "ignore")
    return "utf-8"


def fetch_html(url: str, retries: int = 2, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as res:
                body = res.read(8_000_000)
                charset = detect_charset(res.headers.get("Content-Type", ""), body)
                return body.decode(charset, errors="replace")
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"통신 오류: {type(exc).__name__}") from None
    raise RuntimeError("재시도 실패")


def enrich_article(article: dict) -> dict:
    url = article.get("link") or article.get("originallink")
    if not url:
        return {**article, "full_text": None, "full_text_source": "fallback_description"}
    try:
        html_doc = fetch_html(url)
    except RuntimeError:
        return {**article, "full_text": None, "full_text_source": "fetch_failed"}
    full_text, source = extract_full_text(html_doc)
    return {**article, "full_text": full_text, "full_text_source": source}


def enrich_all(articles: list[dict]) -> list[dict]:
    return [enrich_article(a) for a in articles]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="daily_briefing_<date>.json에 기사 원문 전체(full_text)를 추가")
    parser.add_argument("--date", help="대상일 YYYY-MM-DD (기본: output/ 안의 최신 daily_briefing_*.json)")
    parser.add_argument("--input-dir", type=Path, default=Path("output"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args(argv)

    if args.date:
        in_path = args.input_dir / f"daily_briefing_{args.date}.json"
    else:
        candidates = sorted(args.input_dir.glob("daily_briefing_2*.json"))
        if not candidates:
            print(f"{args.input_dir}에 daily_briefing_*.json이 없습니다. Task 3를 먼저 실행하세요.", file=sys.stderr)
            return 2
        in_path = candidates[-1]

    if not in_path.exists():
        print(f"{in_path} 없음. Task 3를 먼저 실행하세요.", file=sys.stderr)
        return 2

    data = json.loads(in_path.read_text(encoding="utf-8"))
    target_date = data.get("target_date_kst", "unknown")

    data["incidents"] = enrich_all(data.get("incidents", []))
    data["safety_and_maintenance"] = enrich_all(data.get("safety_and_maintenance", []))
    data["fulltext_enriched_at_kst"] = datetime.now(KST).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"daily_briefing_enriched_{target_date}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    all_articles = data["incidents"] + data["safety_and_maintenance"]
    counts: dict[str, int] = {}
    for a in all_articles:
        src = a["full_text_source"]
        counts[src] = counts.get(src, 0) + 1
    print(f"완료: {len(all_articles)}건 처리 -> {out_path}")
    print(f"full_text_source 분포: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
