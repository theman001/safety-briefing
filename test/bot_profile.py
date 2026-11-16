#!/usr/bin/env python3
"""텔레그램 봇 이름/설명/명령어 메뉴 설정 (1회성, 로드맵 Task 아님).

프로필 사진은 Bot API에 메서드가 없어 @BotFather에서 /setuserpic으로 수동 설정해야 함.

사용법:
    python3 test/bot_profile.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 루트 모듈 import용

from dotenv_loader import load_dotenv
from subscriber_manage import _call

BOT_NAME = "산업안전 사고 브리핑"
SHORT_DESCRIPTION = (
    "매일 08:00 KST, 전날 산업안전·설비 사고 뉴스를 업종/원인/교훈 중심으로 "
    "요약해 드리는 개인용 브리핑 봇입니다."
)
DESCRIPTION = (
    "매일 아침 8시, 전날 발생한 산업안전·설비 사고 뉴스와 공공 통계를 수집해 "
    "업종·사고유형·핵심사실·정비 교훈 중심으로 요약해 보내드립니다.\n\n"
    "설비 이상을 조기에 파악하고 고장 원인을 이해해 정비 노하우를 쌓기 위한 "
    "개인용 브리핑 봇입니다. 사실 확인이 안 된 사고 원인은 추측 없이 "
    "'조사 중'으로 표시합니다.\n\n/start 를 보내면 구독이 시작됩니다."
)
COMMANDS = [{"command": "start", "description": "브리핑 구독 시작 (매일 08:00 KST)"}]


def main() -> int:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("환경변수 TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    _call(token, "setMyName", {"name": BOT_NAME})
    print("이름 설정 완료:", BOT_NAME)

    _call(token, "setMyShortDescription", {"short_description": SHORT_DESCRIPTION})
    print("짧은 설명 설정 완료")

    _call(token, "setMyDescription", {"description": DESCRIPTION})
    print("긴 설명 설정 완료")

    _call(token, "setMyCommands", {"commands": json.dumps(COMMANDS, ensure_ascii=False)})
    print("명령어 메뉴 설정 완료:", COMMANDS)

    return 0


if __name__ == "__main__":
    sys.exit(main())
