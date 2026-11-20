#!/usr/bin/env python3
"""Task 8b: 날씨(8a) + 오늘 요약(Task 4)을 DeepSeek로 묶어 종합 평가 생성.

Python 3.9+, 표준 라이브러리만 사용. docs/03_tasks/task-08b-comprehensive-assessment.md 참고.

사용법 (프로젝트 루트에서):
    python3 test/assessment_synthesize.py [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"

INCIDENT_CLASSIFICATIONS = {"INCIDENT_REPORT", "INCIDENT_FOLLOWUP"}
TREND_CLASSIFICATIONS = {"SAFETY_TREND", "MAINTENANCE_TECH", "LAW_POLICY"}

RISK_LEVELS = ("관심", "주의", "경고")

SYSTEM_PROMPT = (
    "너는 산업안전 현장관리자가 아침 TBM(작업 전 안전회의)에서 쓸 '종합 평가'를 작성하는 보조원이다. "
    "입력은 오늘 아침 기준 서울의 날씨 요약(기온/습도/강수확률/풍속/하늘상태/강수형태)과 현재 발효 중인 "
    "공식 기상특보 목록, 그리고 오늘 발송되는 어제자 사고 기사 요약·안전동향/정비기술 기사 요약이다. "
    "아래 3가지를 작성하라. "
    "1) risk_level: 공식 특보가 있으면 반드시 '경고'로 판정하고 risk_reason에 특보명을 명시한다. 특보가 "
    "없으면 날씨 수치가 평소보다 상당히 높거나/낮거나/강한 수준인지, 그리고 사고 기사에 사망·중상 등 "
    "중대한 결과가 원문에 명시됐는지를 근거로 '주의' 또는 '관심' 중 하나를 고른다. 구체적인 숫자 임계값을 "
    "지어내지 말고, 특보 유무와 사고 원문에 실제로 적힌 사실만 근거로 쓴다. "
    "2) key_warnings: 오늘 특히 조심해야 할 점을 최대 3개까지, 각 항목을 subject(구체적 대상 — 설비명, "
    "작업 동작, 취약 구역), reason(그 상황이 오늘 왜 특히 위험한지 — 입력된 사고 원인·동향/정비기술 기법과 "
    "오늘 날씨 조건이 어떻게 겹치는지에 대한 근거), action(그 상황에서 구체적으로 무엇을 확인·조치해야 "
    "하는지)으로 나눠서 작성한다. reason과 action은 각각 간결한 한 문장(50자 내외, 아무리 길어도 한 문장을 "
    "넘기지 않는다)으로 쓴다. 기사 내용을 단순 재요약하지 말고 날씨·기사를 실제로 연결한 근거를 reason에 "
    "담고, '조심하자' 같은 추상적 당부가 아니라 실행 가능한 구체적 행동을 action에 담는다. **반드시 입력에 "
    "실제로 등장한 사고 원인·업종·기법이거나 날씨 수치 자체에서 직접 끌어온 것만 쓴다 — '끼임', '컨베이어' "
    "같은 입력에 없는 일반적인 산업안전 소재나 근거 없는 설비·상황을 개수를 채우려고 지어내지 않는다.** "
    "입력 사고·동향 기사 수보다 더 많은 경고를 억지로 만들지 말 것 — 근거 있는 경고가 1~2개뿐이면 그만큼만 "
    "쓰고, 사고나 동향 기사가 전부 없으면 날씨 정보만으로 만들 수 있는 경고만 담는다(그마저 없으면 빈 배열). "
    "3) closing_message: 오늘 날씨에 맞춘 한 문장짜리 마무리 안전 한마디. "
    "사실 확인 전 추측을 만들지 않는다 — 입력에 없는 사고 원인·설비·수치를 지어내지 않는다. "
    '{"risk_level": "관심"|"주의"|"경고", "risk_reason": string, '
    '"key_warnings": [{"subject": string, "reason": string, "action": string},...], '
    '"closing_message": string} 형태의 JSON 객체로만 응답한다.'
)


def _load_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def load_weather(output_dir: str) -> dict | None:
    today = datetime.now(KST).strftime("%Y%m%d")
    return _load_json(os.path.join(output_dir, f"weather_{today}.json"))


def load_briefing(output_dir: str, target: str) -> dict | None:
    return _load_json(os.path.join(output_dir, f"summarized_briefing_{target}.json"))


def build_request_payload(weather: dict, incidents: list[dict], trends: list[dict]) -> dict:
    user_payload = {
        "weather_summary": weather.get("summary"),
        "official_warnings_active": weather.get("official_warnings", {}).get("active", []),
        "today_incidents": [
            {"industry": s.get("industry"), "incident_type": s.get("incident_type"),
             "key_facts": s.get("key_facts"), "probable_cause": s.get("probable_cause")}
            for s in incidents
        ],
        "today_trends": [
            {"industry": s.get("industry"), "key_facts": s.get("key_facts"),
             "maintenance_lesson": s.get("maintenance_lesson")}
            for s in trends
        ],
    }
    return {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "stream": False,
        "max_tokens": 2000,
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


def parse_assessment(response: dict) -> dict:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"DeepSeek 응답 구조가 예상과 다름: {exc}") from None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"모델 응답 content가 JSON이 아님: {exc}") from None

    risk_level = parsed.get("risk_level")
    if risk_level not in RISK_LEVELS:
        raise RuntimeError(f"risk_level 값이 올바르지 않음: {risk_level!r}")
    risk_reason = parsed.get("risk_reason")
    if not risk_reason:
        raise RuntimeError("risk_reason이 비어있음")
    key_warnings = parsed.get("key_warnings")
    if not isinstance(key_warnings, list):
        raise RuntimeError("key_warnings가 배열이 아님")
    parsed_warnings = []
    for w in key_warnings:
        if not isinstance(w, dict) or not w.get("subject") or not w.get("reason") or not w.get("action"):
            raise RuntimeError(f"key_warnings 항목에 subject/reason/action이 없음: {w!r}")
        parsed_warnings.append({
            "subject": str(w["subject"]), "reason": str(w["reason"]), "action": str(w["action"]),
        })
    closing_message = parsed.get("closing_message")
    if not closing_message:
        raise RuntimeError("closing_message가 비어있음")

    return {
        "risk_level": risk_level,
        "risk_reason": str(risk_reason),
        "key_warnings": parsed_warnings,
        "closing_message": str(closing_message),
    }


def apply_official_floor(result: dict, active_warnings: list[str]) -> dict:
    """공식 특보가 떠 있으면 AI 판단과 무관하게 risk_level을 '경고'로 강제한다.

    안전신호를 전부 AI 판단에 맡기면 특보가 있는데도 낮춰 판단할 위험이 있다 — 그게
    브리핑에서 제일 위험한 실패 모드라 코드로 결정론적으로 막는다.
    """
    if not active_warnings:
        return result
    names = "·".join(active_warnings)
    reason = result.get("risk_reason") or ""
    if names not in reason:
        reason = f"공식 특보 발효 중({names})" + (f" — {reason}" if reason else "")
    return {**result, "risk_level": "경고", "risk_reason": reason}


def _write_skip(out_path: str, target: str, reason: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "target_date_kst": target,
            "generated_at_kst": datetime.now(KST).isoformat(),
            "model": MODEL,
            "skipped": True,
            "skip_reason": reason,
            "risk_level": None, "risk_reason": None,
            "key_warnings": [], "closing_message": None,
            "token_usage": {"prompt_tokens": None, "completion_tokens": None},
        }, f, ensure_ascii=False, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="날씨 + 오늘 요약을 묶어 종합 평가 생성")
    parser.add_argument("--date", default=None, help="대상일(사고/동향 기준, KST) YYYY-MM-DD. 기본: 어제")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args(argv)

    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("환경변수 DEEPSEEK_API_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2

    target = args.date or (datetime.now(KST) - timedelta(days=1)).date().isoformat()
    out_path = os.path.join(args.output_dir, f"comprehensive_assessment_{target}.json")

    weather = load_weather(args.output_dir)
    if weather is None:
        _write_skip(out_path, target, "날씨 데이터 없음(Task 8a 미실행 또는 실패)")
        print(f"스킵: 날씨 데이터 없음 -> {out_path}")
        return 0

    briefing = load_briefing(args.output_dir, target)
    if briefing is None:
        _write_skip(out_path, target, "요약 데이터 없음(Task 4 미실행 또는 실패)")
        print(f"스킵: 요약 데이터 없음({target}) -> {out_path}")
        return 0

    summaries = briefing.get("summaries", [])
    incidents = [s for s in summaries if s.get("classification") in INCIDENT_CLASSIFICATIONS]
    trends = [s for s in summaries if s.get("classification") in TREND_CLASSIFICATIONS]

    payload = build_request_payload(weather, incidents, trends)
    try:
        response = call_deepseek(api_key, payload)
        result = parse_assessment(response)
    except RuntimeError as exc:
        print(f"종합 평가 생성 실패: {exc}", file=sys.stderr)
        return 1

    active_warnings = weather.get("official_warnings", {}).get("active", [])
    result = apply_official_floor(result, active_warnings)

    usage = response.get("usage", {})
    os.makedirs(args.output_dir, exist_ok=True)
    out = {
        "target_date_kst": target,
        "generated_at_kst": datetime.now(KST).isoformat(),
        "model": MODEL,
        "skipped": False,
        "skip_reason": None,
        **result,
        "token_usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(
        f"종합 평가 생성 완료: 위험지수={result['risk_level']}, "
        f"사고 {len(incidents)}건/동향 {len(trends)}건 반영 -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
