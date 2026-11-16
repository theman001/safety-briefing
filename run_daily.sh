#!/usr/bin/env bash
# 산업안전 사고 브리핑 파이프라인 전체 실행 (Task 1~5). cron1이 매일 08:00 KST에 호출한다.
# 각 파이썬 스크립트는 입력 파일이 없으면 스스로 명확히 실패/스킵하므로, 여기서는 순서대로
# 호출만 한다 — 중간 단계가 실패해도 다음 단계가 알아서 "입력 없음"으로 조용히 끝난다(ponytail: 별도 재시도/중단 로직 없음).
cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p logs

{
  echo "=== $(date -Iseconds) 시작 ==="
  python3 subscriber_manage.py
  python3 news_fetch.py
  python3 news_classify.py
  python3 accident_stats.py
  python3 merge_briefing.py
  python3 deepseek_summarize.py
  python3 telegram_send.py
  echo "=== $(date -Iseconds) 종료 ==="
} >> "logs/run_$(date +%F).log" 2>&1
