# 02. 로드맵 (초안)

각 작업은 `CLAUDE.md`의 5단계 사이클(구상→구현→실데이터 검증→피드백/구상수정→재작업)을 거친다.
완료 기준: 실제 외부 데이터로 검증 + 사용자 승인.

- [x] **Task 0. 프로젝트 세팅** — CLAUDE.md, docs/, .claude/commands/ 구성
- [x] **Task 1. 뉴스 수집·1차 분류 (재설계)** — `naver.py`는 참고 자료일 뿐 베이스로 쓰지 않음(사용자 결정, 2026-11-13). 범위가 넓어 아래 두 개로 분리, 둘 다 완료:
  - [x] **1a. 원시 수집** — 수집+날짜필터+중복제거+느슨한 산업맥락 필터. **실데이터 검증 통과(2026-11-13), 승인됨 → `news_fetch.py`/`dotenv_loader.py` 루트로 이동 완료.** 16쿼리 전부 성공, 149건 유일 기사 중 147건 필터 통과, peak RSS 31MB. 상세: [docs/03_tasks/task-01a-news-fetch.md](03_tasks/task-01a-news-fetch.md)
  - [x] **1b. 1차 분류** — 1a 출력(`output/news_raw_*.json`)을 규칙 기반 분류. **실데이터 검증 통과(2026-11-13), 승인됨 → `news_classify.py` 루트로 이동 완료.** 147건 전부 레이블, 3개 분류 버그(비산업 근로자 오분류/"공시" 부분일치/"수사" 과매칭) 발견·수정·재검증. **추가 수정(2026-11-16, Task4 검증 중 발견): `LAW_POLICY`/`OTHER` 레이블 추가**(입법 기사 오분류·모아보기 기사 오매칭 수정) — 7건 변경, 재검증 통과, 승인됨. 상세: [docs/03_tasks/task-01b-news-classify.md](03_tasks/task-01b-news-classify.md)
  - (참고용 기존 구현 기록: [docs/03_tasks/task-01-naver-news-collection.md](03_tasks/task-01-naver-news-collection.md))
- [ ] **Task 2. 공공데이터 수집기** — 조사 결과 두 데이터셋 모두 당초 가정(일일 신규 사고 피드)과 다름(아래 상세). 아래 두 개로 분리(구상 완료, 컨펌 대기):
  - [ ] **2a. SIF 아카이브 키워드 검색** — **보류 (사용자 결정, 2026-11-16).** 실제 발급받은 키로 2026-11-13/11-16 두 번 재확인해도 `NO_OPENAPI_SERVICE_ERROR`(코드12, "서비스 없음/폐기") 동일 — 2b는 같은 키로 성공했으므로 키 문제 아니고 KOSHA/data.go.kr 게이트웨이 쪽 장애로 추정(포털 문서는 정상 게시 중이라 이상함). 이 작업은 당장 고칠 수 없어 보류, Task 4로 진행. 상세: [docs/03_tasks/task-02a-sif-archive-lookup.md](03_tasks/task-02a-sif-archive-lookup.md)
  - [x] **2b. 사고재해자수 통계** — **실데이터 검증 통과(2026-11-13), 승인됨 → `accident_stats.py` 루트로 이동 완료.** odcloud REST API로 2025년 데이터(`한국산업안전보건공단_산업중분류별 발생형태별 사고재해자수_20251231`) 300행 수신, 발생형태 23종 합계 vs 총계 불일치 0건, peak RSS 28MB/0.43초. 상세: [docs/03_tasks/task-02b-accident-stats-file.md](03_tasks/task-02b-accident-stats-file.md)
  - **선행조건(공통): data.go.kr 인증키 발급(사용자) — 2a/2b가 같은 포털 계정이지만 활용신청은 API 상품별로 별도일 수 있음(미확인)**
- [x] **Task 3. 소스 통합** — 범위 재정의됨(2a 블로커 상태라 사건 단위 교차 소스가 없음): 뉴스 브리핑 후보에 2b 통계 트렌드를 참고 컨텍스트로 첨부. **실데이터 검증 통과(2026-11-16), 승인됨 → `merge_briefing.py` 루트로 이동 완료.** 63건 전부 유실 없이 통합, 27건 업종 매핑 성공(Top3 발생형태 상식과 일치), 36건(업종없음 35+방산 1) null로 정상 통과. 상세: [docs/03_tasks/task-03-daily-briefing-merge.md](03_tasks/task-03-daily-briefing-merge.md)
- [x] **Task 4. DeepSeek 요약 연동** — 후보 목록 → 구조화 요약 (업종/사고유형/사실/교훈) + 필터링(`dropped`/`drop_reason`). 1·2차 완료 후 **Task 5b 검증 중 사용자 피드백("내용이 너무 방대함")으로 재오픈(2026-11-16)** — "입력=출력 건수 고정" 불변조건이 필터링을 구조적으로 막고 있었음이 드러나 재설계. 4회 반복 검증(76%→41%→42%(needs_review 버그)→54% 제외) 끝에 **실데이터 검증 통과, 승인됨 → `deepseek_summarize.py` 루트 재이동 완료.** 중복 제거(GS칼텍스 7건, 인천 남동구 7건 등 정확히 클러스터링) 양호, 알려진 한계 1건(통계 인용 기사 병합 시 부속 사고정보 손실 가능성)은 사용자가 인지 후 수용. 상세: [docs/03_tasks/task-04-deepseek-summarize.md](03_tasks/task-04-deepseek-summarize.md)
- [ ] **Task 5. Telegram 전송** — 사용자 결정(2026-11-16)으로 구독자 자동 관리 추가, 아래 두 개로 분리:
  - [x] **5a. 구독자 관리** — `/start` 자동 등록, 봇 차단/구독해제 자동 삭제(유령 구독자 방지), 최대 인원수는 `.env`의 `TELEGRAM_MAX_SUBSCRIBERS`(하드코딩 안 함). **실데이터 검증 통과(2026-11-16), 승인됨 → `subscriber_manage.py` 루트로 이동 완료.** 실제 봇(`@Industrial_Safety_Briefing_bot`)·실제 계정으로 등록/멱등/정원초과/차단감지/최초생성/연속실행/손상파일 7개 케이스 전부 통과 — 특히 설계 당시 "확인 필요"로 남겼던 차단 시 `my_chat_member`(kicked) 감지가 실제로 동작함을 실증. peak RSS 26MB. 상세: [docs/03_tasks/task-05a-subscriber-management.md](03_tasks/task-05a-subscriber-management.md)
  - [x] **5b. 전송 (섹션별)** — `subscribers.json` 기준으로 섹션별 메시지 전송. 피드백 2건(이모지 포맷, Task4 필터링 연계) 반영 후 **실데이터 검증 통과, 승인됨 → `telegram_send.py` 루트로 이동 완료.** 검증 중 추가 버그 발견·수정: 텔레그램 4096자 한도가 UTF-16 코드유닛 기준이라 이모지(서로게이트 페어) 추가 후 Python `len()` 기준 분할이 실제로는 초과돼 `HTTP 400` 발생 — `tg_len()`(UTF-16 계산) + 제목 오버헤드 여유분 추가로 해결. 최종 실전송 4/4건 성공, peak RSS 28MB. 상세: [docs/03_tasks/task-05b-telegram-send.md](03_tasks/task-05b-telegram-send.md)
  - **선행조건: 텔레그램 봇 토큰 확보(사용자) — 완료**
- [x] **Task 6. 스케줄링/운영** — `setup.sh`/`run_daily.sh` 작성, 서버(144.24.73.238) 패키지 설치·타임존(Asia/Seoul) 설정·cron 2개 등록(08:00 파이프라인/09:00 output 30일 정리) 전부 완료. `~/safety-briefing`에 `git clone`으로 실배포 후 `run_daily.sh` 2회 실데이터 검증 — 1차 실행에서 "환영 메시지 재발송" 현상 발견했으나 `subscribers.json`이 gitignore 대상이라 최초 배포 시에만 발생하는 정상 동작임을 2차 실행(신규 이벤트 없음, 환영 메시지 없음)으로 확인. cron2 로직도 가짜 날짜 파일로 검증. 상세: [docs/03_tasks/task-06-scheduling.md](03_tasks/task-06-scheduling.md)
- [ ] **Task 7. 엔드투엔드 1주일 시범 운영** — 매일 실제 브리핑 수신 후 분류/요약 품질 피드백 반영

## 다음 실행할 작업
**Task 1~6 전체 완료.** 다음은 **Task 7(엔드투엔드 1주일 시범 운영)** — 실제 cron이 매일 08:00 KST에 자동으로 돌면서 분류/요약 품질을 며칠 지켜보는 단계. git 원격 저장소: https://github.com/theman001/safety-briefing. Task 2a는 여전히 블로커 상태로 보류 중(2b 통계로 대체 운영, Task 7 진행에 영향 없음).
