#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NAVER API HUB 산업안전·설비보전 뉴스 수집/사고 관련성 판별 v2.0

Python 3.9+, 표준 라이브러리만 사용.

실시간 수집 (Windows PowerShell):
    py naver_safety_news_v2.py

기존 업로드 ZIP으로 오프라인 재검증:
    py naver_safety_news_v2.py --offline-zip naver_probe_20261112_225408.zip --date 2026-11-11

출력:
    results.zip
      - metadata.json (검색/날짜 커버리지/오류 요약)
      - raw_*.json (API 원본 응답, 온라인 실행 시)
      - articles_all.csv (대상일 기사 전체, 정규화/분류 포함)
      - articles_incidents.csv (사고 보도/사고 후속)
      - articles_insights.csv (안전 동향/설비 기술)
      - articles_review.csv (판단 보류)
      - articles_excluded.csv (제외)
      - briefing_candidates.json (브리핑 후보, 근거 포함)
      - dedup_report.json (원문 URL 중복/제목 유사 기사 표시)

정확도 안전장치:
 - 네이버 검색 결과는 날짜 제한 파라미터가 없으므로 페이지를 넘겨 수집한 다음 pubDate로 필터.
 - 사고 발생일은 pubDate로 단정하지 않음. 기사 게시일만 확정 가능.
 - 사실 확인 이전에 사고 원인/동향 증감을 생성하지 않음.
 - TITLE/description이 검색 문맥에 따라 잘린 단편임: REVIEW/제외 기사도 보존.
 - API 키는 환경변수/입력값으로만 사용하고 어떤 파일에도 기록하지 않음.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import getpass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen
import zipfile

KST = timezone(timedelta(hours=9))
API_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# 검색 범위는 사고/정비 중심의 구체적인 구문으로 시작합니다. 이후 실제 누락 사례에 맞춰 조정.
QUERIES = [
    ("일반산업", "산업재해 사고"),
    ("정유석유화학", "정유공장 화재"),
    ("정유석유화학", "화학공장 누출"),
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
    ("자동차설비보전", "자동차 공장 사고"),
    ("자동차설비보전", "프레스 정비 사고"),
    ("자동차설비보전", "산업용 로봇 끼임"),
]
# 이미 제공받은 v1 ZIP에서 썼던 검색어 (오프라인 테스트용).
LEGACY_QUERIES = {
    "전체_산업재해": "산업재해",
    "정유_석유화학": "정유 화학공장 사고",
    "철강": "제철소 사고",
    "비철금속": "제련소 사고",
    "발전소": "발전소 설비 사고",
    "방산": "방산 공장 사고",
    "반도체": "반도체 공장 사고",
    "자동차_설비보전": "자동차 공장 설비 사고",
}

# 하드코딩된 특정 기업명으로 판별하지 않습니다.
INDUSTRY_TERMS = {
    "정유·석유화학": ["정유공장", "정유", "석유화학", "화학공장", "정제시설", "정제공장", "석유정제", "반응기", "나프타", "화학단지", "석유시설"],
    "철강": ["제철소", "제철", "제강", "철강", "압연", "용광로", "고로 설비", "고로에서", "제강공장", "제철공장", "철강공장", "전기로 제강", "전기로 폭발"],
    "비철금속": ["제련소", "제련", "비철금속", "동제련", "아연제련", "니켈제련", "용해로", "용융금속", "주조설비"],
    "발전소": ["발전소", "화력발전", "원자력발전", "원전", "복합화력", "발전터빈", "발전설비", "증기터빈", "급수펌프", "보일러", "가스터빈"],
    "방산": ["방위산업", "방산", "군수공장", "탄약공장", "화약공장", "탄약제조", "방산설비", "화약제조", "무기제조", "군수품"],
    "반도체": ["반도체", "웨이퍼", "반도체공장", "반도체팹", "클린룸", "식각장비", "노광장비", "반도체장비", "스크러버"],
    "자동차·설비보전": ["자동차공장", "완성차", "차체공장", "자동차생산", "자동차 조립", "조립라인", "프레스", "컨베이어", "산업용로봇", "산업용 로봇", "설비보전", "예방정비", "설비정비", "정비작업", "생산라인", "유압설비", "공압설비", "공작기계"],
}
INDUSTRIAL_CONTEXT = [
    "공장", "산업현장", "작업자", "근로자", "정비", "설비", "기계", "공정", "생산시설",
    "제조", "제련", "제철", "발전소", "배관", "작업장", "안전보건", "산업재해", "산재",
    "압력용기", "회전체", "로봇", "터빈", "보일러", "저장탱크", "용해로", "화학시설"
]
EVENT_STRONG = [
    "화재", "폭발", "누출", "유출", "질식", "감전", "끼임", "협착", "추락", "붕괴", "파열",
    "감전사", "인명피해", "사망", "숨져", "숨진", "숨졌다", "숨지고", "다쳐", "부상",
    "설비 고장", "설비고장", "기계 고장", "기계고장", "가동중단", "가동 중단", "가동정지", "가동 정지",
    "작업중 사고", "작업 중 사고", "정전", "가스중독", "중독사", "넘어져", "매몰", "화학물질 유출",
]
EVENT_WEAK = ["사고", "산재", "재해", "재난", "위험", "피해"]
OCCURRENCE = ["발생", "일어나", "벌어져", "났", "나서", "숨져", "숨졌다", "다쳐", "잇따라", "긴급", "소방당국", "현장 출동", "발견", "사망", "중상", "가동중단", "가동 중단"]
FOLLOWUP = ["사고 원인", "사고원인", "사고 조사", "사고조사", "사고 재발", "재발 방지", "재발방지", "수사", "조사 결과", "조사결과", "법원", "재판", "판결", "기소", "산재 인정", "보상", "과실", "책임자", "형사처벌"]
PAST = ["과거", "지난해", "작년", "작년에", "지난달", "지난주", "작년 사고", "당시 사고", "발생했던", "발생한 지", "1년 전", "2년 전", "원인 밝혀"]
SAFETY = ["안전관리", "산업안전", "위험하면", "작업 멈추", "대피", "안전교육", "안전대책", "안전 대책", "작업중지권", "안전점검", "예방대책", "사고 예방", "재해 예방", "위험성평가", "안전 강화", "소방훈련", "안전훈련", "방재훈련", "대응훈련", "안전 수칙", "안전수칙", "안전보건", "중대재해", "안전 기술"]
TECH = ["예지보전", "예방정비", "설비보전", "설비 진단", "설비진단", "고장 예측", "고장예측", "이상 감지", "이상감지", "예측 정비", "예측정비", "유지보수", "정비 기술", "스마트 정비", "진동 진단", "설비 상태", "설비 수명", "결함 진단", "설비 고장", "설비고장"]
# 제목에 등장할 때만 경제/기업경영의 오탐 감점; 사고 키워드가 제목에 명확하면 제외하지 않음.
BUSINESS_TITLE = ["주가", "공시", "실적", "증시", "투자자", "주식", "경영권", "지분", "공개매수", "대여", "분기실적", "상장", "금융", "배당", "증권", "최고경영자", "대표이사", "대표 구속", "대표 불참", "사장 공백", "흑자경영", "재계 인사이드", "사외이사", "M&A", "개장 전", "시가총액", "민영화"]
CIVIC_TITLE = ["행정사무감사", "행감", "도의회", "시의회", "지방의회", "예산 집행", "시정 브리핑", "주요일정", "주요 일정", "시장 선거", "공공기관 인사", "브리핑 모음"]
# 안전훈련 기사에 나온 '화재·폭발'은 실제 발생한 사고가 아니라 가상 시나리오일 수 있음.
EXERCISE = ["모의훈련", "소방훈련", "방재훈련", "대응훈련", "훈련대회", "시연", "가상상황", "가상 상황", "대피훈련", "예방훈련", "화재 대응 훈련", "화재 대비 훈련"]

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "source", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "naver", "from", "referrer", "spm"}
CSV_FIELDS = ["published_kst", "title", "description", "originallink", "link", "canonical_url", "queries", "industry_matches", "industry_evidence", "classification", "score", "reasons", "needs_source_verification", "near_duplicate_of", "pubDate_raw"]


def norm_text(s: object) -> str:
    if not isinstance(s, str):
        return ""
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\s+", " ", s).strip()


def compressed(s: str) -> str:
    return re.sub(r"\s+", "", s.casefold())


def hit(text: str, terms: list[str]) -> list[str]:
    c = compressed(text)
    result = []
    for term in terms:
        term_compact = compressed(term)
        if term == "방산":
            # '방산면'은 방위산업과 무관한 지명일 수 있음.
            if term_compact in c.replace("방산면", ""):
                result.append(term)
        elif term_compact in c:
            result.append(term)
    return result


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


def industry_details(title: str, description: str):
    matches = []
    evidence = {}
    for industry, terms in INDUSTRY_TERMS.items():
        th = hit(title, terms)
        dh = hit(description, terms)
        if th or dh:
            matches.append(industry)
            evidence[industry] = {"title": th[:4], "description": dh[:4]}
    return matches, evidence


def classify(title: str, description: str) -> dict:
    """투명한 결정규칙: 명확한 보도만 자동 채택, 애매하면 REVIEW.

    규칙 점수는 검증된 통계 모형의 확률이 아니라 관찰 가능한 근거의 휴리스틱.
    """
    industries, evidence = industry_details(title, description)
    tit_evt = hit(title, EVENT_STRONG)
    desc_evt = hit(description, EVENT_STRONG)
    tit_weak = hit(title, EVENT_WEAK)
    tit_occ = hit(title, OCCURRENCE)
    tit_follow = hit(title, FOLLOWUP)
    desc_follow = hit(description, FOLLOWUP)
    tit_safety = hit(title, SAFETY)
    tit_tech = hit(title, TECH)
    desc_safety = hit(description, SAFETY)
    desc_tech = hit(description, TECH)
    tit_business = hit(title, BUSINESS_TITLE)
    tit_civic = hit(title, CIVIC_TITLE)
    tit_exercise = hit(title, EXERCISE)
    desc_exercise = hit(description, EXERCISE)
    tit_indust = hit(title, INDUSTRIAL_CONTEXT)
    desc_indust = hit(description, INDUSTRIAL_CONTEXT)
    tit_past = hit(title, PAST)
    is_industrial = bool(industries or tit_indust or desc_indust)
    # 자동차 단독 보도(교통사고) 등 산업 맥락이 없으면 검토 또는 제외.
    specific_in_title = any(v["title"] for v in evidence.values())
    specific_in_desc = any(v["description"] for v in evidence.values())

    score = 0
    reasons = []
    if specific_in_title:
        score += 4
        reasons.append("제목에 대상 산업/설비 단서")
    elif specific_in_desc:
        score += 1
        reasons.append("요약에만 대상 산업/설비 단서")
    elif tit_indust:
        score += 2
        reasons.append("제목에 산업 현장 단서")
    if tit_evt:
        score += 5
        reasons.append("제목에 구체적 사고/고장 단서: " + ", ".join(tit_evt[:3]))
    elif tit_weak:
        score += 1
        reasons.append("제목에 일반 사고 표현(사실 확인 필요)")
    if tit_occ:
        score += 1
    if tit_follow:
        score += 3
        reasons.append("제목에 조사·후속 보도 단서")
    if tit_safety:
        score += 3
        reasons.append("제목에 안전·예방 관련 단서")
    if tit_tech:
        score += 3
        reasons.append("제목에 설비기술 관련 단서")
    if desc_evt and not tit_evt:
        score += 1
        reasons.append("사고 단서는 기사 요약에만 존재")
    if tit_business:
        score -= 5
        reasons.append("제목에 경제·경영 분쟁 단서")
    if tit_civic:
        score -= 4
        reasons.append("제목에 행정·정책 단서(사고 직접성 낮음)")

    label = "REVIEW"
    if not is_industrial:
        label = "EXCLUDED"
        reasons.append("산업/설비 맥락 확인 불가")
    elif (tit_business or tit_civic) and not (tit_evt and (tit_occ or tit_follow)) and not (tit_tech and specific_in_title):
        label = "EXCLUDED"
        reasons.append("주된 주제가 산업사고·안전·보전이 아님")
    elif tit_exercise and not (tit_occ and not hit(title, ["가상", "모의"])):
        label = "SAFETY_TREND"
        reasons.append("훈련/시연 보도: 실제 사고로 분류하지 않음")
    elif tit_tech and (specific_in_title or tit_indust) and not (tit_occ and tit_evt and not hit(title, ["예측", "진단", "방지", "예방"])):
        # '설비 고장 예측'은 고장 발생이 아니라 보전 기술 소개임.
        label = "MAINTENANCE_TECH"
    elif tit_evt and specific_in_title and not tit_exercise:
        # 실제 사고에 대한 후속 보도 단서가 명확한 경우만 후속으로 분류
        if tit_follow and (tit_past or not tit_occ):
            label = "INCIDENT_FOLLOWUP"
        elif tit_past and (tit_follow or desc_follow):
            label = "INCIDENT_FOLLOWUP"
        elif tit_occ or len(tit_evt) >= 1:
            label = "INCIDENT_REPORT"
        else:
            label = "REVIEW"
    elif tit_evt and (tit_indust or (specific_in_desc and tit_occ)) and not tit_exercise:
        if tit_follow and not tit_occ:
            label = "INCIDENT_FOLLOWUP"
        else:
            label = "INCIDENT_REPORT" if tit_occ else "REVIEW"
    elif tit_follow and (tit_weak or desc_evt or specific_in_title) and (tit_indust or specific_in_title):
        label = "INCIDENT_FOLLOWUP"
    elif tit_safety and (specific_in_title or tit_indust):
        label = "SAFETY_TREND"
    elif tit_tech and (specific_in_title or tit_indust):
        label = "MAINTENANCE_TECH"
    elif (tit_weak or desc_evt) and (specific_in_desc or tit_indust):
        label = "REVIEW"
    elif (desc_safety or desc_tech) and specific_in_title:
        label = "REVIEW"
    else:
        label = "EXCLUDED"
        reasons.append("제목에서 사고/예방/보전 중심 내용을 확인하지 못함")

    # 위험한 오탐: 제목은 평범한 기사인데 요약에 사고와 제련소가 서로 다른 문맥으로 나온 경우
    if label == "INCIDENT_REPORT" and not tit_evt and not tit_occ:
        label = "REVIEW"
    if label == "INCIDENT_REPORT" and tit_exercise:
        label = "SAFETY_TREND"
    if label == "INCIDENT_REPORT" and tit_past and (tit_follow or desc_follow):
        label = "INCIDENT_FOLLOWUP"
    if label == "INCIDENT_REPORT" and not specific_in_title and not tit_indust and not (specific_in_desc and tit_occ):
        label = "REVIEW"
    if label in {"INCIDENT_REPORT", "INCIDENT_FOLLOWUP"} and (tit_business or tit_civic) and not tit_evt:
        label = "REVIEW"

    return {
        "classification": label,
        "score": score,
        "industry_matches": industries,
        "industry_evidence": evidence,
        "reasons": reasons,
        "needs_source_verification": True,  # 네이버 제목/요약만 확인한 것이므로 전 기사 원문 확인 필요
    }


@dataclass
class Article:
    title: str
    description: str
    originallink: str
    link: str
    pubDate_raw: str
    published_kst: str
    canonical_url: str
    queries: set[str] = field(default_factory=set)
    near_duplicate_of: str = ""
    classification: str = ""
    score: int = 0
    industry_matches: list[str] = field(default_factory=list)
    industry_evidence: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    needs_source_verification: bool = True

    def key(self):
        return self.canonical_url or "content:" + hashlib.sha256((self.title+"|"+self.published_kst).encode()).hexdigest()

    def to_row(self):
        return {
            "published_kst": self.published_kst,
            "title": self.title,
            "description": self.description,
            "originallink": self.originallink,
            "link": self.link,
            "canonical_url": self.canonical_url,
            "queries": "; ".join(sorted(self.queries)),
            "industry_matches": "; ".join(self.industry_matches),
            "industry_evidence": json.dumps(self.industry_evidence, ensure_ascii=False),
            "classification": self.classification,
            "score": self.score,
            "reasons": "; ".join(self.reasons),
            "needs_source_verification": self.needs_source_verification,
            "near_duplicate_of": self.near_duplicate_of,
            "pubDate_raw": self.pubDate_raw,
        }


def normalize_articles(raw_sources, target_day: str):
    target = date.fromisoformat(target_day)
    stored = {}
    invalid_dates = 0
    outside_range = 0
    raw_total = 0
    duplicate_url = 0
    for query, data in raw_sources:
        for item in data.get("items", []):
            raw_total += 1
            if not isinstance(item, dict):
                continue
            dt = parse_pubdate(item.get("pubDate", ""))
            if not dt:
                invalid_dates += 1
                continue
            if dt.date() != target:
                outside_range += 1
                continue
            title = norm_text(item.get("title", ""))
            description = norm_text(item.get("description", ""))
            original = item.get("originallink", "")
            link = item.get("link", "")
            canonical = canonical_url(original) or canonical_url(link)
            art = Article(title, description, original, link, item.get("pubDate", ""), dt.isoformat(), canonical, {query})
            key = art.key()
            if key in stored:
                stored[key].queries.add(query)
                duplicate_url += 1
            else:
                stored[key] = art
    articles = list(stored.values())
    for art in articles:
        cl = classify(art.title, art.description)
        art.classification = cl["classification"]
        art.score = cl["score"]
        art.industry_matches = cl["industry_matches"]
        art.industry_evidence = cl["industry_evidence"]
        art.reasons = cl["reasons"]
        art.needs_source_verification = cl["needs_source_verification"]
    articles.sort(key=lambda a: (a.published_kst, a.score), reverse=True)
    near_duplicates = []
    for i, art in enumerate(articles):
        # 제목이 매우 흡사한 별도 매체 기사: 삭제하지 않고 '중복 의심' 링크만 남김.
        if len(art.title) < 15:
            continue
        for prev in articles[:i]:
            if art.published_kst[:10] != prev.published_kst[:10]:
                continue
            if not (set(art.industry_matches) & set(prev.industry_matches)):
                continue
            if SequenceMatcher(None, compressed(art.title), compressed(prev.title)).ratio() >= 0.9:
                art.near_duplicate_of = prev.key()
                near_duplicates.append({"url": art.key(), "maybe_duplicate_of": prev.key(), "title": art.title})
                break
    counts = {
        "raw_items": raw_total,
        "outside_target_day": outside_range,
        "invalid_dates": invalid_dates,
        "duplicate_urls_target_day": duplicate_url,
        "unique_target_day": len(articles),
        "categories": {name: sum(a.classification == name for a in articles) for name in ["INCIDENT_REPORT", "INCIDENT_FOLLOWUP", "SAFETY_TREND", "MAINTENANCE_TECH", "REVIEW", "EXCLUDED"]},
        "possible_near_duplicate_articles": len(near_duplicates),
    }
    return articles, counts, near_duplicates


def get_credentials():
    user = os.environ.get("NAVER_CLIENT_ID") or input("NAVER Client ID: ").strip()
    secret = os.environ.get("NAVER_CLIENT_SECRET") or getpass.getpass("NAVER Client Secret: ")
    if not user or not secret:
        raise ValueError("Client ID/Secret이 비었습니다.")
    return user, secret


def fetch_one(query: str, start: int, display: int, user: str, secret: str, retries=3):
    params = {"query": query, "display": display, "start": start, "sort": "date", "format": "json"}
    req = Request(API_URL + "?" + urlencode(params), headers={
        "X-NCP-APIGW-API-KEY-ID": user,
        "X-NCP-APIGW-API-KEY": secret,
        "Accept": "application/json",
        "User-Agent": "Safety-Briefing-Source-Validation/2.0",
    })
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=25) as res:
                body = res.read(8_000_000)
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status}")
                return json.loads(body.decode("utf-8-sig"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries-1:
                time.sleep(2**attempt * 2)
                continue
            raise RuntimeError(f"네이버 API HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2**attempt * 2)
                continue
            raise RuntimeError(f"API 통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError:
            raise RuntimeError("응답이 정상 JSON이 아닙니다.") from None
    raise RuntimeError("재시도 실패")


def collect_live(day: str, max_pages: int, display: int, delay: float, outdir: Path, quick=False):
    user, secret = get_credentials()
    # --quick 역시 7개 산업을 모두 최소 한 번씩 검사합니다.
    queries = [QUERIES[i] for i in (0, 1, 3, 5, 7, 9, 11, 13)] if quick else QUERIES
    sources = []
    logs = []
    target = date.fromisoformat(day)
    for i, (industry, query) in enumerate(queries, start=1):
        completed = False
        pages = 0
        total_for_query = 0
        statuses = []
        print(f"[{i}/{len(queries)}] {industry} / {query}")
        for page in range(max_pages):
            start = 1 + page * display
            if start + display - 1 > 1000:  # NAVER 검색 API start 한도 보호
                break
            try:
                data = fetch_one(query, start, display, user, secret)
                pages += 1
                items = data.get("items", [])
                if not isinstance(items, list):
                    raise RuntimeError("items 필드가 배열이 아닙니다.")
                sources.append((query, data))
                safe_slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", industry + "_" + query)[:60]
                (outdir / f"raw_{i:02d}_{safe_slug}_p{page+1}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                total_for_query += len(items)
                dates = [dt.date() for item in items if isinstance(item, dict) if (dt := parse_pubdate(item.get("pubDate", "")))]
                yesterday_n = sum(d == target for d in dates)
                print(f"  p{page+1} {len(items)}건, 대상일 {yesterday_n}건")
                if not items or len(items) < display:
                    completed = True
                    statuses.append("검색 결과 마지막 페이지 도달")
                    break
                if dates and all(d < target for d in dates):
                    completed = True
                    statuses.append("현재 페이지 전부 대상일 이전 기사")
                    break
                if page + 1 >= max_pages:
                    statuses.append("최대 페이지 도달: 이전 날짜까지 미확인 가능")
                time.sleep(delay)
            except RuntimeError as exc:
                statuses.append(str(exc))
                print(f"  ! {exc}")
                break
        logs.append({"query": query, "industry": industry, "pages_fetched": pages, "items_fetched": total_for_query, "date_coverage_page_complete": completed, "notes": statuses})
        time.sleep(delay)
    return sources, logs


def collect_offline(zip_path: Path, day: str):
    sources = []
    logs = []
    with zipfile.ZipFile(zip_path) as z:
        try:
            meta = json.loads(z.read("metadata.json"))
        except (KeyError, json.JSONDecodeError):
            meta = {}
        reqs = meta.get("requests", [])
        for name in z.namelist():
            if not name.startswith("raw_") or not name.endswith(".json"):
                continue
            data = json.loads(z.read(name))
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                continue
            slug = name[len("raw_"):-len(".json")]
            q = LEGACY_QUERIES.get(slug)
            if not q:
                # 온라인 v2 ZIP(raw_XX_industry_query_pN.json)도 처리할 수 있도록
                m = re.search(r"raw_\d\d_.+?_p\d+\.json$", name)
                q = slug if not m else slug
            sources.append((q, data))
        # 오프라인 파일에는 이전 실행의 페이징 여부가 남아 있을 수 있음
        for req in reqs:
            logs.append({"query": req.get("query"), "status": req.get("status"), "pages_fetched": 1,
                         "date_coverage_page_complete": False, "notes": ["기존 1페이지 샘플: 전날 뉴스 전체 수집 보장 불가"]})
    return sources, logs


def dump_csv(path: Path, articles: list[Article]):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for a in articles:
            writer.writerow(a.to_row())


def save_reports(outdir: Path, articles: list[Article], counts: dict, near_duplicates: list, metadata: dict):
    incidents = [a for a in articles if a.classification in ("INCIDENT_REPORT", "INCIDENT_FOLLOWUP")]
    insights = [a for a in articles if a.classification in ("SAFETY_TREND", "MAINTENANCE_TECH")]
    review = [a for a in articles if a.classification == "REVIEW"]
    excluded = [a for a in articles if a.classification == "EXCLUDED"]
    for name, vals in [
        ("articles_all.csv", articles),
        ("articles_incidents.csv", incidents),
        ("articles_insights.csv", insights),
        ("articles_review.csv", review),
        ("articles_excluded.csv", excluded),
    ]:
        dump_csv(outdir / name, vals)
    (outdir / "dedup_report.json").write_text(json.dumps({
        "count_exact_url_duplicates": counts["duplicate_urls_target_day"],
        "possibly_similar_headlines_not_deleted": near_duplicates,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # 기사 원문 검증 전 후보 목록. 원문에 근거한 '사고 원인' 생성은 불가.
    briefing = {
        "target_date": metadata["target_day_kst"],
        "disclaimer": "이 파일은 검색 결과의 제목·요약으로 후보를 판별한 결과입니다. 사고 발생일/사고 원인은 원문 또는 공식 기록 확인 전에는 미확인입니다.",
        "incidents": [a.to_row() for a in incidents],
        "safety_and_maintenance": [a.to_row() for a in insights],
        "review_count": len(review),
    }
    (outdir / "briefing_candidates.json").write_text(json.dumps(briefing, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata["counts"] = counts
    (outdir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="NAVER 뉴스 A단계: 사고 관련성 규칙 판별 및 실데이터 저장")
    parser.add_argument("--offline-zip", type=Path, default=None, help="기존 NAVER ZIP을 사용하여 API 호출 없이 재분류")
    parser.add_argument("--date", default=None, help="분석할 기사 게시일(한국시간), YYYY-MM-DD. 기본 어제")
    parser.add_argument("--output-dir", type=Path, default=None, help="출력 폴더")
    parser.add_argument("--max-pages", type=int, default=5, help="검색어별 최대 페이지(기본 5)")
    parser.add_argument("--display", type=int, default=100, help="한 페이지 기사 수(기본 100)")
    parser.add_argument("--delay", type=float, default=0.4, help="연속 요청 간 대기 초(기본 0.4)")
    parser.add_argument("--quick", action="store_true", help="라이브 API에서 7개 산업+공통의 대표 검색어 8개만 시험")
    args = parser.parse_args(argv)
    if args.max_pages < 1 or not 1 <= args.display <= 100 or args.delay < 0:
        parser.error("--max-pages >=1, --display 1~100, --delay >=0 필수")
    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            parser.error("--date는 YYYY-MM-DD 형식이어야 합니다")
    elif args.offline_zip:
        try:
            with zipfile.ZipFile(args.offline_zip) as z:
                target = date.fromisoformat(json.loads(z.read("metadata.json"))["target_day_kst"])
        except (ValueError, KeyError, FileNotFoundError, zipfile.BadZipFile):
            target = (datetime.now(KST) - timedelta(days=1)).date()
    else:
        target = (datetime.now(KST) - timedelta(days=1)).date()
    now = datetime.now(KST)
    outdir = args.output_dir or Path.cwd() / f"safety_news_{target.isoformat()}_{now.strftime('%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    print("\nNAVER 산업안전 뉴스 A단계: 사고 관련성 필터 v2.0")
    print("게시일(KST):", target.isoformat())
    print("실행 모드:", "오프라인 재분석" if args.offline_zip else "NAVER API HUB 신규 수집")
    try:
        if args.offline_zip:
            raw_sources, req_log = collect_offline(args.offline_zip, str(target))
        else:
            raw_sources, req_log = collect_live(str(target), args.max_pages, args.display, args.delay, outdir, args.quick)
        articles, counts, near = normalize_articles(raw_sources, str(target))
        meta = {"script_version": "2.0", "target_day_kst": str(target), "generated_at_kst": now.isoformat(),
                "mode": "offline" if args.offline_zip else "live", "api_endpoint": API_URL,
                "credentials_saved": False, "requests": req_log,
                "classification_method": "transparent heuristic rules with uncertain cases held for review",
                "event_occurred_date_verified": False}
        save_reports(outdir, articles, counts, near, meta)
        zp = outdir.with_suffix(".zip")
        with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for f in sorted(outdir.iterdir()):
                if f.is_file():
                    z.write(f, f.name)
        print("\n--- 분석 결과 ---")
        print("대상일 URL 중복 제거 후:", counts["unique_target_day"], "건")
        for cat, num in counts["categories"].items():
            print(" ", cat, num, "건")
        print("유사 제목 의심(삭제 X):", counts["possible_near_duplicate_articles"], "건")
        print("결과 ZIP:", zp.resolve())
        if not articles:
            print("주의: 해당 날짜 기사 0건. 원본 날짜 범위/페이지 커버리지부터 확인하세요.")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print("실행 실패:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
