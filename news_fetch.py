#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task 1a: 산업안전 뉴스 원시 수집 (네이버 뉴스 API → 날짜 필터 → 중복 제거 → 느슨한 산업 맥락 필터).

분류(레이블링)는 하지 않음 — 이 스크립트가 통과시킨 기사는 전부 Task 1b가 받아 최종 레이블을 매긴다.
표준 라이브러리만 사용. 환경변수 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 필요.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import resource
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))
API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# 업종별 검색어 초안 (naver.py 참고). Task 1a 실데이터 검증 후 조정 가능.
QUERIES = [
    ("정유·석유화학", "정유공장 화재"),
    ("정유·석유화학", "화학공장 누출"),
    ("철강", "제철소 사고"),
    ("철강", "압연기 끼임"),
    ("비철금속", "제련소 사고"),
    ("비철금속", "용해로 폭발"),
    ("발전소", "발전소 설비 사고"),
    ("발전소", "발전소 정비 사고"),
    ("방산", "방산 공장 사고"),
    ("방산", "화약공장 폭발"),
    ("반도체", "반도체 공장 사고"),
    ("반도체", "반도체 가스 누출"),
    ("자동차·설비보전", "자동차 공장 사고"),
    ("자동차·설비보전", "프레스 정비 사고"),
    ("자동차·설비보전", "산업용 로봇 끼임"),
    ("일반산업", "산업재해 사고"),
]

INDUSTRY_TERMS = {
    "정유·석유화학": ["정유공장", "정유", "석유화학", "화학공장", "정제시설", "정제공장", "석유정제", "반응기", "나프타", "화학단지", "석유시설"],
    "철강": ["제철소", "제철", "제강", "철강", "압연", "용광로", "고로", "전기로"],
    "비철금속": ["제련소", "제련", "비철금속", "동제련", "아연제련", "니켈제련", "용해로", "용융금속", "주조설비"],
    "발전소": ["발전소", "화력발전", "원자력발전", "원전", "복합화력", "발전터빈", "발전설비", "증기터빈", "급수펌프", "보일러", "가스터빈"],
    "방산": ["방위산업", "방산", "군수공장", "탄약공장", "화약공장", "탄약제조", "방산설비", "화약제조", "무기제조", "군수품"],
    "반도체": ["반도체", "웨이퍼", "반도체공장", "반도체팹", "클린룸", "식각장비", "노광장비", "반도체장비", "스크러버"],
    "자동차·설비보전": ["자동차공장", "완성차", "차체공장", "자동차생산", "자동차 조립", "조립라인", "프레스", "컨베이어", "산업용로봇", "설비보전", "예방정비", "설비정비", "정비작업", "생산라인", "유압설비", "공압설비", "공작기계"],
}
# 업종 특정 키워드가 없어도 "산업 현장" 맥락이면 통과시키는 일반 용어 (재현율 우선).
INDUSTRIAL_CONTEXT = [
    "공장", "산업현장", "작업자", "근로자", "정비", "설비", "기계", "공정", "생산시설",
    "제조", "제련", "제철", "발전소", "배관", "작업장", "안전보건", "산업재해", "산재",
    "압력용기", "회전체", "로봇", "터빈", "보일러", "저장탱크", "용해로", "화학시설",
]

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "naver", "from", "referrer", "spm"}


def norm_text(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\s+", " ", s).strip()


def compressed(s: str) -> str:
    return re.sub(r"\s+", "", s.casefold())


def hit(text: str, terms: list[str]) -> list[str]:
    c = compressed(text)
    found = []
    for term in terms:
        term_c = compressed(term)
        if term == "방산":
            # '방산면'은 방위산업과 무관한 지명.
            if term_c in c.replace("방산면", ""):
                found.append(term)
        elif term_c in c:
            found.append(term)
    return found


def industry_filter(title: str, description: str) -> tuple[bool, list[str]]:
    """(통과여부, 매칭된 업종 목록). 업종 키워드나 일반 산업 맥락 용어가 하나라도 있으면 통과."""
    matches = [industry for industry, terms in INDUSTRY_TERMS.items() if hit(title, terms) or hit(description, terms)]
    if matches:
        return True, matches
    if hit(title, INDUSTRIAL_CONTEXT) or hit(description, INDUSTRIAL_CONTEXT):
        return True, []
    return False, []


def parse_pubdate(s: str):
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            return None
        return d.astimezone(KST)
    except (ValueError, TypeError, OverflowError, AttributeError):
        return None


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        if p.scheme not in ("http", "https") or not p.netloc:
            return ""
        query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")])
        return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/") or "/", query, ""))
    except ValueError:
        return ""


@dataclass
class Article:
    title: str
    description: str
    originallink: str
    link: str
    canonical_url: str
    published_kst: str
    pubDate_raw: str
    matched_queries: set = field(default_factory=set)
    matched_industries: list = field(default_factory=list)

    def to_dict(self):
        return {
            "title": self.title,
            "description": self.description,
            "originallink": self.originallink,
            "link": self.link,
            "canonical_url": self.canonical_url,
            "published_kst": self.published_kst,
            "pubDate_raw": self.pubDate_raw,
            "matched_queries": sorted(self.matched_queries),
            "matched_industry_terms": self.matched_industries,
        }


def fetch_page(query: str, start: int, display: int, client_id: str, secret: str, retries: int = 3) -> dict:
    params = {"query": query, "display": display, "start": start, "sort": "date", "format": "json"}
    req = Request(API_URL + "?" + urlencode(params), headers={
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": secret,
        "Accept": "application/json",
        "User-Agent": "safety-briefing-news-fetch/1a",
    })
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=25) as res:
                body = res.read(8_000_000)
                return json.loads(body.decode("utf-8-sig"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError:
            raise RuntimeError("응답이 정상 JSON이 아님") from None
    raise RuntimeError("재시도 실패")


def collect_query(industry: str, query: str, target: date, max_pages: int, display: int, delay: float, client_id: str, secret: str):
    status = {"industry": industry, "query": query, "pages_fetched": 0, "items_fetched": 0, "ok": True, "error": None}
    raw_items = []
    for page in range(max_pages):
        start = 1 + page * display
        if start + display - 1 > 1000:  # NAVER 검색 API start 상한
            break
        try:
            data = fetch_page(query, start, display, client_id, secret)
        except RuntimeError as exc:
            status["ok"] = False
            status["error"] = str(exc)
            break
        items = data.get("items", [])
        if not isinstance(items, list):
            status["ok"] = False
            status["error"] = "items 필드가 배열이 아님"
            break
        status["pages_fetched"] += 1
        status["items_fetched"] += len(items)
        raw_items.extend(items)
        dates = [d for it in items if isinstance(it, dict) and (d := parse_pubdate(it.get("pubDate", "")))]
        if not items or len(items) < display:
            break
        if dates and all(d.date() < target for d in dates):
            break
        time.sleep(delay)
    return raw_items, status


def collect_live(target: date, queries, max_pages: int, display: int, delay: float, client_id: str, secret: str):
    query_items = []
    query_status = []
    for i, (industry, query) in enumerate(queries, start=1):
        print(f"[{i}/{len(queries)}] {industry} / {query}")
        raw_items, status = collect_query(industry, query, target, max_pages, display, delay, client_id, secret)
        query_items.append((industry, query, raw_items))
        query_status.append(status)
        time.sleep(delay)
    return query_items, query_status


def normalize(query_items, target: date):
    raw_total = 0
    invalid_dates = 0
    outside_target = 0
    duplicate_count = 0
    industry_dropped = 0
    dropped_sample = []
    seen_keys = set()
    stored: dict[str, Article] = {}

    for industry, query, items in query_items:
        for item in items:
            raw_total += 1
            if not isinstance(item, dict):
                continue
            dt = parse_pubdate(item.get("pubDate", ""))
            if not dt:
                invalid_dates += 1
                continue
            if dt.date() != target:
                outside_target += 1
                continue
            title = norm_text(item.get("title", ""))
            description = norm_text(item.get("description", ""))
            original = item.get("originallink", "")
            link = item.get("link", "")
            canon = canonical_url(original) or canonical_url(link)
            key = canon or "content:" + hashlib.sha256((title + "|" + dt.isoformat()).encode()).hexdigest()

            if key in seen_keys:
                duplicate_count += 1
                if key in stored:
                    stored[key].matched_queries.add(query)
                continue
            seen_keys.add(key)

            passed, industries = industry_filter(title, description)
            if not passed:
                industry_dropped += 1
                if len(dropped_sample) < 30:
                    dropped_sample.append({"title": title, "query": query})
                continue
            stored[key] = Article(title, description, original, link, canon, dt.isoformat(), item.get("pubDate", ""), {query}, industries)

    articles = list(stored.values())
    articles.sort(key=lambda a: a.published_kst, reverse=True)
    counts = {
        "raw_items_total": raw_total,
        "invalid_dates": invalid_dates,
        "outside_target_day": outside_target,
        "duplicate_urls": duplicate_count,
        "industry_filter_dropped": industry_dropped,
        "industry_filter_passed": len(articles),
    }
    return articles, counts, dropped_sample


def main(argv=None):
    parser = argparse.ArgumentParser(description="Task 1a: 산업안전 뉴스 원시 수집 (분류 없음)")
    parser.add_argument("--date", default=None, help="대상일(KST), YYYY-MM-DD. 기본: 어제")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args(argv)

    if args.max_pages < 1 or not 1 <= args.display <= 100 or args.delay < 0:
        parser.error("--max-pages >=1, --display 1~100, --delay >=0 필수")

    load_dotenv()
    client_id = os.environ.get("NAVER_CLIENT_ID")
    secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not secret:
        print("오류: NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 필요합니다 (.env 파일 또는 환경변수).", file=sys.stderr)
        return 2

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            parser.error("--date는 YYYY-MM-DD 형식이어야 합니다")
    else:
        target = (datetime.now(KST) - timedelta(days=1)).date()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_time = time.monotonic()

    print("Task 1a: 산업안전 뉴스 원시 수집")
    print("대상일(KST):", target.isoformat())

    query_items, query_status = collect_live(target, QUERIES, args.max_pages, args.display, args.delay, client_id, secret)
    articles, counts, dropped_sample = normalize(query_items, target)

    elapsed = time.monotonic() - start_time
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    out_path = args.output_dir / f"news_raw_{target.isoformat()}.json"
    out_path.write_text(json.dumps([a.to_dict() for a in articles], ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "target_date_kst": target.isoformat(),
        "generated_at_kst": datetime.now(KST).isoformat(),
        "api_endpoint": API_URL,
        "queries": query_status,
        "counts": counts,
        "dropped_sample": dropped_sample,
        "elapsed_seconds": round(elapsed, 1),
        "peak_rss_kb": peak_rss_kb,
    }
    meta_path = args.output_dir / f"news_raw_{target.isoformat()}_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n--- 결과 ---")
    print("필터 통과(1b로 전달):", counts["industry_filter_passed"], "건")
    print("산업 맥락 필터 드롭:", counts["industry_filter_dropped"], "건")
    print("중복 제거:", counts["duplicate_urls"], "건")
    print("peak RSS:", f"{peak_rss_kb / 1024:.1f} MB" if peak_rss_kb else "N/A")
    print("실행 시간:", f"{elapsed:.1f}s")
    print("출력:", out_path.resolve())
    print("메타:", meta_path.resolve())

    failed = [s for s in query_status if not s["ok"]]
    if failed:
        print(f"\n주의: {len(failed)}개 쿼리 실패:", file=sys.stderr)
        for s in failed:
            print(f"  - {s['industry']}/{s['query']}: {s['error']}", file=sys.stderr)

    if counts["industry_filter_passed"] == 0:
        print("주의: 필터 통과 기사 0건. 날짜/쿼리/필터 기준을 재확인하세요.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
