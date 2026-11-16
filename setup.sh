#!/usr/bin/env bash
# 산업안전 사고 브리핑 시스템 — 서버 초기 환경 설정 (Oracle Cloud, Ubuntu 기준).
# 반복 실행해도 안전함(idempotent) — 이미 돼 있는 건 건너뛴다.
# 사용법: git clone 받은 프로젝트 루트에서 ./setup.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=== 1. 필요 패키지 점검 ==="
need_apt_update=0
command -v git >/dev/null 2>&1 || { echo "git 없음 -> 설치 예정"; need_apt_update=1; }
command -v crontab >/dev/null 2>&1 || { echo "cron 없음 -> 설치 예정"; need_apt_update=1; }
if [ "$need_apt_update" = "1" ]; then
  sudo apt-get update -qq
  command -v git >/dev/null 2>&1 || sudo apt-get install -y -qq git
  command -v crontab >/dev/null 2>&1 || sudo apt-get install -y -qq cron
fi
sudo systemctl enable --now cron >/dev/null

python3 -c 'import sys; assert sys.version_info >= (3, 9), f"Python 3.9+ 필요 (현재 {sys.version})"'
echo "python3: $(python3 --version)"
echo "git: $(git --version)"
echo "cron: $(systemctl is-active cron)"
# 이 프로젝트는 표준 라이브러리만 쓴다(CLAUDE.md 원칙) — pip/venv/서드파티 패키지 설치 없음.

echo "=== 2. 타임존을 Asia/Seoul로 설정 (브리핑 08:00 KST 기준) ==="
sudo timedatectl set-timezone Asia/Seoul
echo "현재 타임존: $(timedatectl show --property=Timezone --value)"

echo "=== 3. cron 등록 ==="
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/output"
chmod +x "$PROJECT_DIR/run_daily.sh"

CRON1="0 8 * * * $PROJECT_DIR/run_daily.sh # safety-briefing-daily"
CRON2="0 9 * * * find $PROJECT_DIR/output -maxdepth 1 -type f -mtime +30 -delete # safety-briefing-cleanup"
(
  crontab -l 2>/dev/null | grep -v "safety-briefing-daily" | grep -v "safety-briefing-cleanup" || true
  echo "$CRON1"
  echo "$CRON2"
) | crontab -

echo "--- 등록된 crontab ---"
crontab -l

echo "=== 설정 완료 ==="
echo "다음 할 일: .env 파일을 '$PROJECT_DIR/.env'에 직접 올리세요 (git에는 포함되지 않습니다)."
