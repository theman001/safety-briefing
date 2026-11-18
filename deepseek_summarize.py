#!/usr/bin/env python3
"""Task 4: daily_briefing_<date>.json을 DeepSeek API로 구조화 요약.

Python 3.9+, 표준 라이브러리만 사용. docs/03_tasks/task-04-deepseek-summarize.md 참고.

사용법:
    python3 test/deepseek_summarize.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"

VALID_CLASSIFICATIONS = {
    "INCIDENT_REPORT", "INCIDENT_FOLLOWUP", "SAFETY_TREND", "MAINTENANCE_TECH", "LAW_POLICY",
}

SYSTEM_PROMPT = (
    "너는 산업안전 사고 뉴스를 구조화 요약하는 보조원이다. "
    "사실 확인 전 사고 원인이나 발생일을 단정하지 않는다 — 원문(title/description)에 "
    "명시되지 않은 원인은 추측해서 채우지 말고 probable_cause를 null로 두고 "
    "needs_review를 true로 표시한다. "
    "입력 각 기사의 classification은 키워드 기반 1차 분류 결과로, 참고용 추정치일 뿐이다. "
    "그대로 믿지 말고 title/description 본문을 직접 읽고 그 분류가 실제로 맞는지 판단해 "
    "최종 classification을 결정하라. 예를 들어 1차 분류가 INCIDENT_REPORT나 "
    "INCIDENT_FOLLOWUP(사고 보도)으로 왔어도 실제 내용이 보험상품 소개, 법안/제도 추진, "
    "통계 발표처럼 특정 사고 1건을 보도하는 게 아니면 SAFETY_TREND 또는 LAW_POLICY로 "
    "교정하라. 반대로 1차 분류가 안전동향 등으로 왔어도 실제로 특정 사고를 보도하는 기사면 "
    "INCIDENT_REPORT나 INCIDENT_FOLLOWUP으로 교정하라. 최종 classification은 "
    "INCIDENT_REPORT/INCIDENT_FOLLOWUP/SAFETY_TREND/MAINTENANCE_TECH/LAW_POLICY 중 "
    "하나여야 한다(입력으로 들어오는 기사는 이미 이 5개 중 하나로 1차 분류된 것들만이므로, "
    "교정값도 이 범위 안에서 고른다). dropped가 true인 기사도 classification은 채운다. "
    "입력 기사에 stat_context가 있어도, 먼저 기사 본문(title/description)이 실제로 그 업종의 "
    "사고·설비 현장과 관련된 내용인지 판단하라. 정치/행정/일반 기사처럼 설비·사고와 무관한데 "
    "업종 매칭만 잘못 걸린 경우에는 stat_context를 무시하고 maintenance_lesson을 기사 실제 "
    "내용에 맞게 작성하거나(없으면 null). 실제로 관련 있을 때만 maintenance_lesson에 그 "
    "top_event_types 중 최소 1개 용어를 구체적으로 언급해 업종 통계와 연결하라. "
    "기사를 거를 때는 반드시 아래 순서로 판단한다. "
    "1단계(중복 판정) — 입력 기사 전체를 대상으로 사실상 동일한 사건(같은 사고/같은 발표/같은 "
    "보도자료)을 다른 매체가 보도했거나, 같은 발표를 다른 통계치·다른 제목으로 강조했을 뿐인 "
    "기사를 모두 찾아내라 — 숫자나 제목이 달라도 출처 사건이 같으면 동일 사건으로 본다. 가장 "
    "정보가 많은 1건만 dropped를 false로 두고, 나머지 중복 기사는 dropped를 true로, "
    "drop_reason에 '중복 (index N과 동일 사건)' 형태로 적어라. "
    "2단계(중요도 판정) — 1단계에서 중복으로 걸리지 않은 기사만 대상으로 저관련성/저중요도를 "
    "좁게 적용한다: 순수 행정 반복 공지(지자체·기관의 정기 안전교육 실시 안내, 단순 행사 "
    "참석·개최 소개, 제품/기업 홍보가 주목적인 기사)만 dropped를 true로 표시한다. 반대로 "
    "구체적인 정책 변화(제도 신설·확대), 안전 기술·관리체계의 도입이나 전환, 점검에서 실제로 "
    "발견된 위반사항이나 구체적 예방조치처럼 설비·안전관리에 실질적으로 참고할 내용이 있는 "
    "기사는 dropped를 false로 유지한다. dropped 여부가 애매하면 dropped를 false로 유지한다 "
    "(과잉 제거보다 과소 제거가 낫다). needs_review는 이 dropped 판단과는 무관하며, 오직 "
    "probable_cause(사고 원인)를 원문에서 확인할 수 없을 때만 true로 표시한다. "
    "dropped가 true인 원소는 industry 등 나머지 필드를 null로 둬도 된다. "
    "입력으로 주어진 기사 배열과 정확히 같은 개수의 결과를(모든 index에 대해 응답 필수, "
    "dropped인 기사도 반드시 포함), 각 원소에 원본 index를 포함해 "
    '{"summaries": [...]} 형태의 JSON 객체로만 응답한다. '
    "각 summaries 원소는 index(int), classification(string), dropped(bool), "
    "drop_reason(string|null), industry(string|null), incident_type(string|null), "
    "key_facts(string|null), probable_cause(string|null), maintenance_lesson(string|null), "
    "needs_review(bool) 필드를 가진다."
)


def build_request_payload(articles: list[dict]) -> dict:
    user_payload = [
        {
            "index": i,
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "classification": a.get("classification", ""),
            "matched_industry_terms": a.get("matched_industry_terms", []),
            "stat_context": a.get("stat_context"),
        }
        for i, a in enumerate(articles)
    ]
    return {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
        # 기본값(비-thinking 모드 8K)은 기사 수가 늘면 잘릴 수 있어 명시적으로 넉넉히 잡음.
        "max_tokens": 16000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }


def call_deepseek(api_key: str, payload: dict, retries: int = 3, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }, method="POST")
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as res:
                raw = res.read()
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status}")
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail[:500]}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"DeepSeek API 통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek API 응답이 JSON이 아님: {exc}") from None
    raise RuntimeError("재시도 초과")


def parse_summaries(response: dict, articles: list[dict]) -> list[dict]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"DeepSeek 응답 구조가 예상과 다름: {exc}") from None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"모델 응답 content가 JSON이 아님: {exc}") from None

    summaries = parsed.get("summaries")
    if not isinstance(summaries, list):
        raise RuntimeError("모델 응답에 summaries 배열이 없음")
    if len(summaries) != len(articles):
        raise RuntimeError(f"입력 {len(articles)}건 != 출력 {len(summaries)}건 (유실/중복 발생)")

    by_index = {}
    for item in summaries:
        idx = item.get("index")
        if idx is None or idx in by_index:
            raise RuntimeError(f"summaries 항목의 index가 비어있거나 중복됨: {item}")
        by_index[idx] = item

    result = []
    for i, article in enumerate(articles):
        if i not in by_index:
            raise RuntimeError(f"index {i}에 해당하는 요약이 없음")
        s = by_index[i]
        classification = s.get("classification")
        if classification not in VALID_CLASSIFICATIONS:
            print(f"index {i}: AI가 유효하지 않은 classification({classification!r})을 반환 — "
                  f"1차 분류({article.get('classification')!r})로 폴백", file=sys.stderr)
            classification = article.get("classification")
        result.append({
            "title": article.get("title"),
            "link": article.get("link"),
            "classification": classification,
            "dropped": bool(s.get("dropped", False)),
            "drop_reason": s.get("drop_reason"),
            "industry": s.get("industry"),
            "incident_type": s.get("incident_type"),
            "key_facts": s.get("key_facts"),
            "probable_cause": s.get("probable_cause"),
            "maintenance_lesson": s.get("maintenance_lesson"),
            "needs_review": bool(s.get("needs_review", False)),
        })
    return result


def split_dropped(results: list[dict]) -> tuple[list[dict], list[dict]]:
    """반환: (kept, dropped) — dropped는 감사(audit)용으로 title/link/classification/drop_reason만 남김."""
    kept = []
    dropped = []
    for r in results:
        if r["dropped"]:
            dropped.append({
                "title": r["title"], "link": r["link"],
                "classification": r["classification"], "drop_reason": r["drop_reason"],
            })
        else:
            kept.append({k: v for k, v in r.items() if k not in ("dropped", "drop_reason")})
    return kept, dropped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="daily_briefing_<date>.json을 DeepSeek로 구조화 요약")
    parser.add_argument("--date", help="대상일 YYYY-MM-DD (기본: output/ 안의 최신 daily_briefing_*.json)")
    parser.add_argument("--input-dir", type=Path, default=Path("output"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    args = parser.parse_args(argv)

    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("환경변수 DEEPSEEK_API_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    if args.date:
        in_path = args.input_dir / f"daily_briefing_{args.date}.json"
    else:
        candidates = sorted(args.input_dir.glob("daily_briefing_*.json"))
        if not candidates:
            print(f"{args.input_dir}에 daily_briefing_*.json이 없습니다. Task 3를 먼저 실행하세요.", file=sys.stderr)
            return 2
        in_path = candidates[-1]

    if not in_path.exists():
        print(f"{in_path} 없음. Task 3를 먼저 실행하세요.", file=sys.stderr)
        return 2

    data = json.loads(in_path.read_text(encoding="utf-8"))
    articles = list(data.get("incidents", [])) + list(data.get("safety_and_maintenance", []))
    target_date = data.get("target_date_kst", "unknown")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"summarized_briefing_{target_date}.json"

    if not articles:
        out_path.write_text(json.dumps({
            "target_date_kst": target_date,
            "generated_at_kst": datetime.now(KST).isoformat(),
            "model": MODEL,
            "input_count": 0,
            "kept_count": 0,
            "dropped_count": 0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "summaries": [],
            "dropped": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"입력 0건 — DeepSeek 호출 스킵, 빈 결과 저장: {out_path}")
        return 0

    payload = build_request_payload(articles)
    try:
        response = call_deepseek(api_key, payload)
        results = parse_summaries(response, articles)
    except RuntimeError as exc:
        print(f"요약 실패: {exc}", file=sys.stderr)
        return 1

    kept, dropped = split_dropped(results)
    usage = response.get("usage", {})
    out_path.write_text(json.dumps({
        "target_date_kst": target_date,
        "generated_at_kst": datetime.now(KST).isoformat(),
        "model": MODEL,
        "input_count": len(articles),
        "kept_count": len(kept),
        "dropped_count": len(dropped),
        "token_usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        },
        "summaries": kept,
        "dropped": dropped,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"요약 완료: {len(kept)}건 유지 / {len(dropped)}건 제외(중복·저관련) -> {out_path} "
          f"(prompt={usage.get('prompt_tokens')}, completion={usage.get('completion_tokens')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
