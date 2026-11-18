# Task 6. 스케줄링/운영

상태: **완료 — 실서버 실데이터 검증 통과, 승인됨** (2026-11-16)

> 사용자가 설정을 구체적으로 지시(`setup.sh` 구조, cron1/cron2 역할)해서 별도 `/plan-task` 라운드 없이 바로 이 문서에 구상을 기록하고 구현했다.

## 목표
서버(Oracle Cloud, Ubuntu)에 프로젝트를 배포하고, 매일 08:00 KST에 Task 1~5 파이프라인 전체를 자동 실행하며, `output/` 파일을 30일 지나면 자동 정리한다.

## 입력
- 서버 접속 정보(사용자 제공): `144.24.73.238` / `ubuntu` / SSH 키 `.ssh/ssh-key-2026-11-11.key`
- 배포 방식(사용자 결정): `~/safety-briefing` 디렉터리에서 `git clone` → `./setup.sh` 실행
- 서버 환경(점검 완료, 2026-11-16): Ubuntu 24.04.5 LTS, Python 3.12.3, 952MiB RAM, git/cron 미설치 상태였으나 수동 설치 완료, 타임존 UTC(→ Asia/Seoul로 변경 필요)

## 처리 로직 개요
### `run_daily.sh` (cron1이 매일 08:00 KST에 호출)
프로젝트 루트에서 Task 1~5의 파이썬 스크립트를 순서대로 호출: `subscriber_manage.py`(구독자 목록 최신화) → `news_fetch.py` → `news_classify.py` → `accident_stats.py` → `merge_briefing.py` → `deepseek_summarize.py` → `telegram_send.py`. 각 스크립트가 이미 "입력 파일 없음 → 명시적 에러/스킵"을 자체적으로 처리하므로, 중간 단계가 실패해도 별도 재시도/중단 로직 없이 다음 단계를 그냥 호출한다(ponytail: 각 스크립트의 기존 예외 처리를 재사용, 오케스트레이션 레이어에 로직 중복 안 함). 전체 출력은 `logs/run_<날짜>.log`에 append.

### `setup.sh` (최초 배포 시 1회, 반복 실행해도 안전)
1. **패키지 점검**: `git`/`crontab` 명령 존재 여부 확인 → 없으면만 `apt-get install`(이미 있으면 건너뜀, idempotent). `python3` 버전 3.9+ 확인. 이 프로젝트는 표준 라이브러리만 쓰므로 pip/venv/서드파티 패키지는 설치하지 않음(CLAUDE.md 원칙).
2. **타임존을 Asia/Seoul로 설정**: cron 시각을 "08:00"으로 그대로 등록하려면 시스템 타임존이 KST여야 함(UTC 상태면 실제로는 17:00 KST에 실행됨). `sudo timedatectl set-timezone Asia/Seoul`.
3. **cron 등록**: `crontab`에 두 줄 추가(기존 동일 태그 줄은 먼저 제거 후 재등록 — 반복 실행해도 중복 안 쌓임):
   - `cron1`: `0 8 * * * <PROJECT_DIR>/run_daily.sh` — 매일 08:00 KST 파이프라인 실행
   - `cron2`: `0 9 * * * find <PROJECT_DIR>/output -maxdepth 1 -type f -mtime +30 -delete` — **output 파일 30일 라이프사이클**, 파이프라인 실행 1시간 뒤(09:00)로 잡아 당일 생성 파일과 안 겹치게 함

## 출력
- 서버의 `crontab -l`에 두 작업 등록
- `logs/run_<날짜>.log` — 매일 실행 로그
- `output/` 디렉터리가 30일 넘은 파일 없이 유지됨

## 예외 처리
- `setup.sh`는 `set -euo pipefail`로 중간 실패 시 즉시 중단(불완전한 상태로 "설정 완료"를 내보내지 않음)
- cron 등록은 기존 태그(`# safety-briefing-daily`/`# safety-briefing-cleanup`) 줄만 치환 — 사용자가 직접 등록한 다른 crontab 항목은 건드리지 않음
- `.env`는 git에 포함되지 않으므로 `setup.sh` 마지막에 "`.env`를 직접 올리라"고 안내만 하고 끝남(자동화 범위 밖, 비밀키이므로 당연히 수동)

## 사용할 라이브러리/도구
- bash(coreutils), `apt-get`, `crontab`, `timedatectl` — 전부 Ubuntu 표준 도구, 추가 설치 없음

## 검증 기록 (2026-11-16)
- 서버 환경 점검: Python 3.9+/stdlib 전 모듈 정상, pip 없음(의도대로 불필요), git/cron 없어서 수동 설치 후 재확인 — 정상.
- `setup.sh`/`run_daily.sh`를 실제 서버(`~/safety-briefing/`)에 scp로 올려 단계별 실행:
  - [x] 패키지 점검 부분 — idempotent 동작 확인(이미 설치돼 있어 건너뜀)
  - [x] 타임존 변경 — 실제로 `Asia/Seoul`로 바뀜을 `timedatectl`로 확인
  - [x] `logs/`/`output/` 디렉터리 생성, 스크립트 실행권한 부여 — 확인
  - [x] **cron 등록(`crontab -`)** — 최초엔 로컬 자동 모드 분류기가 "원격 서버 상시 반복 작업 등록"을 위험 동작으로 분류해 거부했으나, 사용자가 Bash 권한을 승인한 뒤 정상 등록. `crontab -l`로 두 작업(cron1 08:00, cron2 09:00) 확인.
  - [x] **서버 실배포 + `run_daily.sh` 실제 실행 2회 검증** — `~/safety-briefing`을 비우고 `git clone`, `.env` scp로 전달(600 권한), 1차 실행에서 전체 파이프라인(1a→1b→2b→3→4→5a→5b) 실데이터로 끝까지 성공, 실제 텔레그램 전송 확인. **중요한 발견**: 1차 실행 때 "구독이 시작되었습니다" 환영 메시지가 다시 발송됨 — 원인은 `subscribers.json`이 `.gitignore` 대상이라 새로 clone한 서버엔 없었고, `last_update_id: 0`부터 시작해 최근 24시간 내 `/start` 이벤트(테스트 중 보낸 것)를 다시 읽어 재등록 처리한 것. **버그 아님**: 2차 실행에서 "신규 이벤트 없음"으로 정상 동작, 환영 메시지도 다시 안 옴 — `subscribers.json`이 서버에 한 번 생기면 이후 cron 실행에서는 반복 안 됨(사용자 실제 수신 확인: "메시지 안왔다").
  - [x] cron2(30일 정리) 로직 검증 — `touch -d`로 35일 전/10일 전 가짜 파일을 만들어 `find ... -mtime +30 -delete` 실행, 35일 전 파일만 삭제되고 10일 전 파일은 남는 것 확인. 테스트 파일은 삭제해 정리.

## 추가 반영 (2026-11-17, Task 7 시범 운영 중 발견)
- **실제 버그**: 다른 사용자가 `/start`를 보냈는데 `subscribers.json`에 추가되지 않고 환영 메시지도 안 옴 — 봇 소유자 여부와는 무관(코드상 그런 구분 없음, 실제로 수동 재실행하자 즉시 정상 등록됨). **원인**: `subscriber_manage.py`가 `run_daily.sh` 안에서 하루 1번(08:00)만 `getUpdates`를 폴링하므로, 그 시각 이후 `/start`한 사람은 다음날 08:00까지 Telegram 서버에 대기만 되고 처리가 안 됨.
- **해결**: `subscriber_manage.py`만 따로 더 자주 도는 cron3 추가 — `getUpdates`가 신규 여부 확인 자체이므로(사전 체크로 호출을 아낄 방법 없음, 이미 `timeout:0`으로 단발 호출 최소화된 상태) 호출 자체는 가볍다고 판단, 15분 간격(정각충돌 방지로 `5,20,35,50 * * * *`, cron1의 `0 8 * * *`과 겹치지 않게 분을 밀어 `subscribers.json` 동시 read-modify-write 경쟁 방지)으로 서버 crontab에 추가:
  - `cron3`: `5,20,35,50 * * * * cd /home/ubuntu/safety-briefing && python3 subscriber_manage.py >> logs/subscriber_poll.log 2>&1 # safety-briefing-subscriber-poll`
  - 서버에서 수동 실행으로 즉시 검증: 대기 중이던 실사용자 2명(`chat_id=9080688379`, `7140385166`)이 정상 등록되고 환영 메시지 전송됨 확인(구독자 1명→3명).
- `run_daily.sh` 안의 `subscriber_manage.py` 호출은 그대로 유지(cron1 실행 때도 한 번 더 확인하는 거라 중복 호출이지만, 멱등 처리라 문제 없음).

## 다음 행동
없음 — Task 6 완료(+ 위 cron3 보강). 계속 Task 7(엔드투엔드 1주일 시범 운영): 실제 cron이 매일 08:00 KST에 돌면서 분류/요약 품질을 며칠 지켜보는 단계.
