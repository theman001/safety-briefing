#!/usr/bin/env python3
"""DeepSeek 요약 결과를 섹션별 메시지로 구독자 전원에게 전송. Task 5b.

Python 3.9+, 표준 라이브러리만 사용.

사용법:
    python3 test/telegram_send.py --date 2026-11-12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from html import escape as _html_escape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))
MESSAGE_LIMIT = 4096
TITLE_OVERHEAD_RESERVE = 200  # 전송 시 본문 앞에 붙는 "제목+빈줄"의 여유분 (청크 번호 포함해도 충분)
BODY_LIMIT = MESSAGE_LIMIT - TITLE_OVERHEAD_RESERVE
SUBSCRIBERS_PATH = "subscribers.json"


def _esc(s: str) -> str:
    """본문 텍스트용 — 따옴표는 안 건드린다.

    html.escape(quote=True) 기본값은 "/'를 &quot;/&#x27;로 바꾸는데, 텔레그램 HTML
    parse_mode는 본문 텍스트 안에서 이런 엔티티를 안정적으로 디코드하지 않아 실제로
    "&quot;"가 글자 그대로 노출되는 걸 실측으로 확인했다. 본문에서는 따옴표가 HTML
    문법상 특수문자가 아니므로 이스케이프할 필요도 없다.
    """
    return _html_escape(s, quote=False)


def _esc_attr(s: str) -> str:
    """href 속성값용 — 속성 안의 "는 구문을 깨므로 여기서만 escape(quote=True)."""
    return _html_escape(s, quote=True)


def tg_len(s: str) -> int:
    """텔레그램이 실제로 세는 길이(UTF-16 코드유닛 수) — 서로게이트 페어 이모지는 len()과 다름."""
    return len(s.encode("utf-16-le")) // 2

INCIDENT_CLASSIFICATIONS = {"INCIDENT_REPORT", "INCIDENT_FOLLOWUP"}
TREND_CLASSIFICATIONS = {"SAFETY_TREND", "MAINTENANCE_TECH", "LAW_POLICY"}
SECTION_GROUPS = [("🚨 오늘의 사고", INCIDENT_CLASSIFICATIONS), ("📊 안전동향·정비기술", TREND_CLASSIFICATIONS)]


class BotBlocked(Exception):
    """수신자가 봇을 차단함 (HTTP 403)."""


def _send_message(token: str, chat_id: int, text: str, retries: int = 3, timeout: int = 10) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
    for attempt in range(retries):
        try:
            with urlopen(url, data=data, timeout=timeout) as res:
                body = json.loads(res.read().decode("utf-8"))
                if not body.get("ok"):
                    raise RuntimeError(f"telegram API 오류: {body}")
                return
        except HTTPError as exc:
            if exc.code == 403:
                raise BotBlocked(f"chat_id={chat_id} 봇 차단(403)") from None
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"통신 오류: {type(exc).__name__}") from None
    raise RuntimeError("재시도 초과")


def article_block(i: int, s: dict) -> str:
    """HTML parse_mode 전제 — 뉴스 원문/AI 생성 텍스트는 전부 _esc()로 이스케이프한다.

    기사 제목·URL에 <, >, &가 우연히 들어있으면(예: 'S&OIL') 이스케이프 없이는
    텔레그램이 'can't parse entities'로 전송을 거부한다.
    """
    industry = _esc(s.get("industry") or "업종 미확인")
    key_facts = _esc(s.get("key_facts") or "세부 사실 확인 전")
    type_part = f" · 🔧 <b>{_esc(s['incident_type'])}</b>" if s.get("incident_type") else ""
    lines = [
        f"{i}. <b>{_esc(s['title'])}</b>",
        f"🏭 {industry}{type_part}",
        f"📝 {key_facts}",
    ]
    if s.get("probable_cause"):
        lines.append(f"🔍 <b>원인:</b> {_esc(s['probable_cause'])}")
    if s.get("maintenance_lesson"):
        lines.append(f"💡 <b>교훈:</b> {_esc(s['maintenance_lesson'])}")
    lines.append(f'🔗 <a href="{_esc_attr(s["link"])}">기사 원문</a>')
    return "\n".join(lines)


def chunk_blocks(blocks: list[str], limit: int = BODY_LIMIT) -> list[list[str]]:
    """기사 블록 경계에서만 끊는다 — 문장 중간 절단 없음. limit은 텔레그램 기준 길이(tg_len)로 잰다."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for b in blocks:
        blen = tg_len(b) + 1
        if blen > limit:
            if cur:
                chunks.append(cur)
                cur, cur_len = [], 0
            chunks.append([b[:limit]])  # ponytail: 기사 블록 자체가 한도 초과하는 극단적 경우만 강제 절단
            continue
        if cur and cur_len + blen > limit:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(b)
        cur_len += blen
    if cur:
        chunks.append(cur)
    return chunks


def build_sections(summaries: list[dict], date: str) -> list[dict]:
    """반환: [{"title_base", "chunks": [body, ...]}, ...] — 0건 그룹은 생략."""
    sections = []
    for label, classes in SECTION_GROUPS:
        items = [s for s in summaries if s["classification"] in classes]
        if not items:
            continue
        blocks = [article_block(i + 1, s) for i, s in enumerate(items)]
        chunks = ["\n\n".join(chunk) for chunk in chunk_blocks(blocks)]
        sections.append({"title_base": f"{label} ({date}, {len(items)}건)", "chunks": chunks})
    return sections


def assessment_block(data: dict) -> str:
    lines = [
        "🌡️ <b>위험지수</b>",
        f"<code>{_esc(data['risk_level'])}</code> — {_esc(data['risk_reason'])}",
        "",
        "<u><b>⚠️ 핵심 경고</b></u>",
    ]
    if data["key_warnings"]:
        for w in data["key_warnings"]:
            lines.append(f"▪️ <b>{_esc(w['subject'])}</b>")
            lines.append(f"⚡ {_esc(w['reason'])}")
            lines.append(f"✅ {_esc(w['action'])}")
    else:
        lines.append("- (해당 없음)")
    lines.append("")
    lines.append(f"<blockquote>☔️ <b>오늘의 한마디</b>\n{_esc(data['closing_message'])}</blockquote>")
    return "\n".join(lines)


def load_assessment(output_dir: str, date: str) -> dict | None:
    """Task 8b 결과를 읽는다 — 없거나 손상됐거나 skipped면 None(3번째 섹션만 조용히 생략)."""
    path = os.path.join(output_dir, f"comprehensive_assessment_{date}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return None
    if data.get("skipped") or not data.get("risk_level") or not data.get("closing_message"):
        return None
    return data


def to_messages(sections: list[dict]) -> list[dict]:
    """포맷터→전송기 계약: 섹션 목록을 [{"title", "body"}]로 평탄화."""
    messages = []
    for sec in sections:
        n = len(sec["chunks"])
        for k, body in enumerate(sec["chunks"], start=1):
            title = sec["title_base"] if n == 1 else f"{sec['title_base']} ({k}/{n})"
            messages.append({"title": title, "body": body})
    return messages


def load_subscribers(path: str) -> dict | None:
    if not os.path.exists(path):
        return {"last_update_id": 0, "subscribers": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def save_subscribers(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_to_subscriber(token: str, chat_id: int, messages: list[dict]) -> tuple[int, str, str | None]:
    """반환: (성공 전송 메시지 수, status('ok'/'blocked'/'failed'), error)."""
    sent = 0
    for msg in messages:
        text = f"<b>{msg['title']}</b>\n\n{msg['body']}"
        try:
            _send_message(token, chat_id, text)
            sent += 1
        except BotBlocked as exc:
            return sent, "blocked", str(exc)
        except RuntimeError as exc:
            return sent, "failed", f"{msg['title']} 전송 실패: {exc}"
    return sent, "ok", None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="요약 결과를 섹션별로 구독자에게 텔레그램 전송")
    parser.add_argument("--date", default=None, help="대상일(KST), YYYY-MM-DD. 기본: 어제")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args(argv)

    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("환경변수 TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    target = args.date or (datetime.now(KST) - timedelta(days=1)).date().isoformat()

    summary_path = os.path.join(args.output_dir, f"summarized_briefing_{target}.json")
    if not os.path.exists(summary_path):
        print(f"입력 파일이 없습니다: {summary_path}", file=sys.stderr)
        return 2
    with open(summary_path, encoding="utf-8") as f:
        summary_data = json.load(f)

    state = load_subscribers(SUBSCRIBERS_PATH)
    if state is None:
        print(f"{SUBSCRIBERS_PATH}가 손상되어 읽을 수 없습니다.", file=sys.stderr)
        return 1
    chat_ids = [s["chat_id"] for s in state["subscribers"]]
    if not chat_ids:
        print("구독자가 없습니다. 전송을 생략합니다.")
        return 0

    sections = build_sections(summary_data["summaries"], target)

    assessment = load_assessment(args.output_dir, target)
    if assessment:
        chunks = ["\n\n".join(chunk) for chunk in chunk_blocks([assessment_block(assessment)])]
        sections.append({"title_base": f"🧭 종합 평가 ({target})", "chunks": chunks})

    if not sections:
        print("전송할 내용이 없습니다(사고/안전동향 0건, 종합평가도 없음).")
        return 0
    messages = to_messages(sections)

    recipients = []
    blocked_ids = []
    for chat_id in chat_ids:
        sent, status, error = send_to_subscriber(token, chat_id, messages)
        recipients.append({"chat_id": chat_id, "sections_sent": sent, "status": status, "error": error})
        if status == "blocked":
            blocked_ids.append(chat_id)
        print(f"chat_id={chat_id}: {status} ({sent}/{len(messages)}건 전송)" + (f" - {error}" if error else ""))

    if blocked_ids:
        state["subscribers"] = [s for s in state["subscribers"] if s["chat_id"] not in blocked_ids]
        save_subscribers(SUBSCRIBERS_PATH, state)
        print(f"차단 감지로 구독자 목록에서 제거: {blocked_ids}")

    meta = {
        "target_date_kst": target,
        "sections": [{"title": sec["title_base"], "chunk_count": len(sec["chunks"])} for sec in sections],
        "recipients": recipients,
    }
    meta_path = os.path.join(args.output_dir, f"telegram_send_{target}_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    ok_count = sum(1 for r in recipients if r["status"] == "ok")
    print(f"완료: {ok_count}/{len(chat_ids)}명 전체 수신 성공 -> {meta_path}")
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
