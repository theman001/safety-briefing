# Task 5a. 텔레그램 구독자 관리 (자동 등록/해제)

상태: **완료 — 실데이터 검증 통과, 승인됨, `subscriber_manage.py` 루트로 이동 완료 (2026-11-16)**

## 목표
텔레그램 `/start`로 구독자를 자동 등록하고, 봇 차단/구독해제 시 자동 삭제해 `subscribers.json`을 최신 상태로 유지한다. 최대 인원 수는 하드코딩 없이 `.env`의 `TELEGRAM_MAX_SUBSCRIBERS`로 정한다.

## 입력
- 텔레그램 Bot API `getUpdates` (실제 API, 폴링 방식 — 웹훅/상시 서버 없이도 됨: Telegram이 미확인 업데이트를 최대 24시간 보관하므로 배치 스크립트가 가끔 호출해 가져오면 됨)
- `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_MAX_SUBSCRIBERS`(기본 10 — 변수로, 코드에 하드코딩 안 함)
- 로컬 상태 파일: `subscribers.json`(없으면 최초 실행에서 새로 생성)

## 처리 로직 개요
1. `subscribers.json` 로드. 없으면 `{"last_update_id": 0, "subscribers": []}`로 초기화.
2. `getUpdates(offset=last_update_id+1, allowed_updates=["message","my_chat_member"], timeout=0)` 호출. `timeout=0`으로 즉시 반환(long-polling 안 씀 — 배치 스크립트라 오래 기다릴 이유 없음).
3. 각 update를 순서대로 처리:
   - `message.text == "/start"`(1:1 채팅) → `chat_id`/`first_name`/`username` 추출.
     - 이미 목록에 있으면 아무 것도 안 함(멱등).
     - 없고 현재 인원 < `TELEGRAM_MAX_SUBSCRIBERS` → 추가(`joined_at_kst` 기록) + 환영 메시지 전송.
     - 없고 인원이 가득 찼으면 **추가하지 않고** "구독 인원이 가득 찼습니다(최대 N명)" 안내만 전송.
   - `my_chat_member`에서 `new_chat_member.status`가 `kicked`(차단) 또는 `left` → 목록에 있으면 제거.
   - 그 외 update 타입은 무시.
4. 처리한 update들 중 가장 큰 `update_id + 1`로 `last_update_id` 갱신(다음 실행이 같은 이벤트를 또 처리하지 않도록).
5. `subscribers.json` 저장.

**확인 필요(실제 테스트 전까지 단정 안 함)**: 사용자가 봇을 "차단"하면 Telegram이 `my_chat_member` 업데이트로 `status: "kicked"`를 보내준다고 알고 있으나, 실제 동작은 Task 검증 단계에서 직접 테스트해 확인한다.

## 출력
- `subscribers.json`: `{"last_update_id": N, "subscribers": [{"chat_id": 123, "first_name": "...", "username": "...", "joined_at_kst": "..."}]}`
- 표준 출력에 신규 등록/삭제/현재 인원 요약

## 예외 처리
- `TELEGRAM_BOT_TOKEN` 없음 → 에러 종료(코드 2)
- `getUpdates` HTTP 실패 → 지수 백오프 재시도(최대 3회), 끝까지 실패하면 `last_update_id`를 갱신하지 않고(다음 실행이 같은 지점부터 재시도) 비정상 종료(exit 1)
- `subscribers.json`이 손상되어(JSON 파싱 실패) 못 읦으면 **덮어쓰지 않고 에러 종료** — 사용자 데이터라 함부로 초기화하지 않음, 수동 확인 요청
- 환영/정원초과 안내 메시지 전송 자체가 실패해도(네트워크 등) 등록/삭제 처리는 그대로 진행(알림은 보조, 목록 정확성이 핵심)
- 동시 실행은 가정하지 않음(cron 1회성 배치, lock 불필요)

## 라이브러리/API
`urllib.request`, `json`, `os`, `time`, `datetime` — 표준 라이브러리로 충분. `dotenv_loader.py` 재사용. SDK 불필요.

## 검증 기준
- [ ] 실제 `TELEGRAM_BOT_TOKEN`으로, 본인이 실제로 봇에 `/start`를 보낸 뒤 실행 → `subscribers.json`에 `chat_id` 추가되고 본인이 환영 메시지 실제 수신 확인
- [ ] 같은 사람이 `/start`를 또 보내도 중복 추가 안 되는지(멱등)
- [ ] `TELEGRAM_MAX_SUBSCRIBERS=1`처럼 작게 설정해 정원 초과 시 추가 안 되고 안내만 가는지 확인
- [ ] 본인이 봇을 차단한 뒤 실행 → `my_chat_member`(kicked)로 `subscribers.json`에서 실제로 제거되는지 확인(위 "확인 필요" 항목의 실증)
- [ ] `subscribers.json`이 없는 최초 실행에서 정상적으로 새로 생성되는지
- [ ] 연속 2회 실행(두 번째는 새 이벤트 없음) → `last_update_id`가 올바르게 갱신돼 같은 이벤트를 중복 처리하지 않는지
- [ ] 결과를 사용자에게 제시

## 운영 주기 (Task 6에서 확정, 지금은 가정만)
지금은 "매일 브리핑 직전 1회 실행"을 기본으로 가정(등록은 다음날 브리핑부터 반영). 더 즉각적인 반영이 필요하면 별도로 짧은 간격(예: 5~10분) cron을 추가할 수 있음 — 가벼운 폴링 1회 호출이라 1GB RAM 제약과는 무관.

## 구현 메모
- `subscriber_manage.py`(루트) — 구상대로 구현(getUpdates 폴링 + `/start` 등록/정원 체크 + `my_chat_member` kicked/left 제거).
- `test_subscriber_manage.py`(루트) — `_call`(텔레그램 API 호출부)을 가짜 응답으로 교체하는 순수 로직 self-check 4건(신규 등록/멱등/정원초과/차단제거), 네트워크 없이 통과.
- `.env.example`에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_MAX_SUBSCRIBERS=10` 추가.

## 실데이터 검증 기록 (2026-11-16)
실제 봇(`@Industrial_Safety_Briefing_bot`, `getMe`로 토큰 유효성 확인)과 사용자 실제 텔레그램 계정(chat_id=7498001795)으로 검증.

| 체크리스트 항목 | 결과 |
|---|---|
| 실제 `/start` → 등록 + 환영 메시지 실제 수신 | 통과 |
| `/start` 재전송 → 중복 추가 안 됨(멱등) | 통과 |
| `TELEGRAM_MAX_SUBSCRIBERS` 소진 시 거부 + 안내 메시지 실제 수신 | 통과 (`=0`으로 설정해 실증) |
| 본인이 봇 차단 → `my_chat_member`(kicked)로 자동 제거 | **통과 — "확인 필요" 플래그 해소: Telegram이 실제로 `status: kicked`를 보냄** |
| `subscribers.json` 없는 최초 실행 → 정상 생성 | 통과 |
| 연속 2회 실행(새 이벤트 없음) → `last_update_id` 중복 처리 없이 갱신 | 통과 |
| (체크리스트 외 추가 확인) `subscribers.json` 손상 시 덮어쓰지 않고 안전 중단(exit 1) | 통과 |

메모리: peak RSS 약 26MB, CPU 0.07s — 1GB RAM 제약과 비교해 여유 충분. 코드 수정 없이 설계 그대로 전부 통과. 사용자 승인 → `test/`에서 루트로 이동 완료. **Task 5a 완료.**

---
이 구상대로 구현해도 될지 확인 부탁한다. ~~(승인됨, 구현 완료)~~
