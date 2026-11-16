#!/usr/bin/env python3
"""텔레그램 구독자 자동 관리 (등록/해제). Task 5a.

Python 3.9+, 표준 라이브러리만 사용. getUpdates 폴링 방식 (웹훅/상시 서버 불필요 —
Telegram이 미확인 업데이트를 최대 24시간 보관하므로 배치로 가끔 호출해도 됨).

사용법:
    python3 test/subscriber_manage.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))
SUBSCRIBERS_PATH = "subscribers.json"
DEFAULT_MAX_SUBSCRIBERS = 10


def _call(token: str, method: str, params: dict, retries: int = 3, timeout: int = 10) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urlencode(params).encode("utf-8")
    for attempt in range(retries):
        try:
            with urlopen(url, data=data, timeout=timeout) as res:
                body = json.loads(res.read().decode("utf-8"))
                if not body.get("ok"):
                    raise RuntimeError(f"telegram API 오류: {body}")
                return body
        except HTTPError as exc:
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


def load_subscribers(path: str) -> dict | None:
    """없으면 새 상태 반환. 손상되어 있으면 None (덮어쓰지 않도록 호출측에서 처리)."""
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


def process_updates(token: str, state: dict, max_subscribers: int) -> list[str]:
    """업데이트를 처리해 state를 직접 갱신한다. 사람이 읽을 로그 라인 목록을 반환."""
    logs: list[str] = []
    subscribers = state["subscribers"]
    by_chat_id = {s["chat_id"]: s for s in subscribers}

    resp = _call(token, "getUpdates", {
        "offset": state["last_update_id"] + 1,
        "allowed_updates": json.dumps(["message", "my_chat_member"]),
        "timeout": 0,
    })
    updates = resp["result"]

    for update in updates:
        state["last_update_id"] = update["update_id"]

        message = update.get("message")
        if message and message.get("text") == "/start" and message.get("chat", {}).get("type") == "private":
            chat = message["chat"]
            chat_id = chat["id"]
            if chat_id in by_chat_id:
                logs.append(f"chat_id={chat_id} 이미 구독 중 (멱등, 무시)")
            elif len(subscribers) < max_subscribers:
                entry = {
                    "chat_id": chat_id,
                    "first_name": chat.get("first_name"),
                    "username": chat.get("username"),
                    "joined_at_kst": datetime.now(KST).isoformat(),
                }
                subscribers.append(entry)
                by_chat_id[chat_id] = entry
                logs.append(f"chat_id={chat_id} 신규 등록")
                _try_send(token, chat_id, "구독이 시작되었습니다. 매일 08:00 KST 브리핑을 받습니다.")
            else:
                logs.append(f"chat_id={chat_id} 등록 거부 (정원 {max_subscribers}명 초과)")
                _try_send(token, chat_id, f"구독 인원이 가득 찼습니다 (최대 {max_subscribers}명).")
            continue

        member_update = update.get("my_chat_member")
        if member_update:
            status = member_update.get("new_chat_member", {}).get("status")
            chat_id = member_update["chat"]["id"]
            if status in ("kicked", "left") and chat_id in by_chat_id:
                subscribers[:] = [s for s in subscribers if s["chat_id"] != chat_id]
                del by_chat_id[chat_id]
                logs.append(f"chat_id={chat_id} 구독 해제 감지(status={status}) -> 제거")

    return logs


def _try_send(token: str, chat_id: int, text: str) -> None:
    try:
        _call(token, "sendMessage", {"chat_id": chat_id, "text": text})
    except RuntimeError as exc:
        print(f"안내 메시지 전송 실패(chat_id={chat_id}): {exc}", file=sys.stderr)


def main(argv=None) -> int:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("환경변수 TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.", file=sys.stderr)
        return 2
    max_subscribers = int(os.environ.get("TELEGRAM_MAX_SUBSCRIBERS", DEFAULT_MAX_SUBSCRIBERS))

    state = load_subscribers(SUBSCRIBERS_PATH)
    if state is None:
        print(f"{SUBSCRIBERS_PATH}가 손상되어 읽을 수 없습니다. 덮어쓰지 않고 중단합니다.", file=sys.stderr)
        return 1

    try:
        logs = process_updates(token, state, max_subscribers)
    except RuntimeError as exc:
        print(f"getUpdates 실패: {exc}", file=sys.stderr)
        return 1

    save_subscribers(SUBSCRIBERS_PATH, state)

    if logs:
        for line in logs:
            print(line)
    else:
        print("신규 이벤트 없음")
    print(f"현재 구독자 {len(state['subscribers'])}/{max_subscribers}명")
    return 0


if __name__ == "__main__":
    sys.exit(main())
