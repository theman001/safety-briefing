# Task 2b. 산업중분류별 발생형태별 사고재해자수 통계

상태: **실데이터 검증 통과, 승인됨(2026-11-13) → `accident_stats.py` 프로젝트 루트로 이동 완료.** 작성일 2026-11-13.

## 조사 결과 요약 (업데이트 — 당초 CSV 다운로드 가정을 대체)
최초 조사에서는 `data.go.kr/data/15084677/openapi.do` → 404로 "OpenAPI 없음, CSV 파일데이터뿐"으로 판단했으나, **실제 웹페이지가 쓰는 다운로드 흐름을 `curl`로 그대로 재현해 추적한 결과 더 나은 경로를 찾았다**:
1. 사람이 쓰는 "다운로드" 버튼은 `/tcs/dss/selectFileDataDownload.do` → `/cmm/cmm/check-limit.json`(CAPTCHA 게이트 존재 가능) → `/cmm/cmm/fileDownload.do` 3단계 흐름이며, 지금은 `needCaptcha:false`였지만 **캡차 게이트가 있다는 것 자체가 cron 배치에는 부적합**(브라우저 없이 캡차를 못 풂).
2. 그런데 이 흐름의 1단계 응답(JSON)에 `"swaggerUrl":"https://infuser.odcloud.kr/oas/docs?namespace=15084677/v1"`가 들어있었다. 이걸 따라가보니 **이 파일데이터셋에는 실제로 odcloud 기반 REST OpenAPI가 있다** (data.go.kr의 `openapi.do` 탭에는 안 뜨지만 별도로 존재).
3. **결론: CSV 다운로드/캡차 경로를 버리고 odcloud REST API를 쓴다.** 더 간단하고(표준 JSON), 캡차 리스크가 없고, 브라우저 없이 `urllib`만으로 완전히 동작 확인됨(serviceKey 없이 호출해 `401 {"code":-401,"msg":"인증키는 필수 항목 입니다."}` 까지 실제로 받아 엔드포인트/파라미터 실존을 확인).

### 확정된 API 스펙 (실호출로 검증됨, 2026-11-13)
- Swagger 메타데이터(인증 불필요, 공개): `GET https://infuser.odcloud.kr/oas/docs?namespace=15084677/v1`
  - 연도별로 **별도 uddi 경로**가 생긴다(예: `/15084677/v1/uddi:4411c1c2-...` = 2025-12-31 기준 최신). **매년 새 uddi가 추가되므로 하드코딩하지 않고 이 swagger를 매번 조회해 가장 최신 연도를 자동 선택한다.**
- 데이터 호출: `GET https://api.odcloud.kr/api/15084677/v1/{최신 uddi 경로}?page=1&perPage=&serviceKey=`
  - 파라미터: `page`(기본 1), `perPage`(기본 10, 전체를 받으려면 크게), `serviceKey`(필수 — 쿼리 또는 `Authorization` 헤더), `returnType`(옵션, 기본 JSON)
  - 응답 필드(swagger로 100% 확정): `page`, `perPage`, `totalCount`, `currentCount`, `matchCount`, `data`(배열). 각 `data` 원소: `대업종`, `중업종`, `규모`(문자열) + 발생형태 23종(정수): 떨어짐/넘어짐/부딪힘/맞음/무너짐/끼임/절단베임찔림/감전/폭발파열/화재/깔림뒤집힘/이상온도물체접촉/빠짐익사/불균형및무리한동작/화학물질누출접촉/산소결핍/사업장내교통사고/사업장외교통사고/체육행사/폭력행위/동물상해/기타/분류불능, 그리고 `총계`(정수)
  - 실제 행 수는 약 300건(연 1회 갱신 스냅샷, 연도 컬럼 없음 — 연도는 uddi 자체가 구분)

## 목표
업종별·발생형태별 사고재해자수(odcloud REST API, 최신 연도 자동 선택)를 가져와, 브리핑 본문이 아닌 "최근 트렌드 보조 지표"(예: 특정 업종 사고 증가 여부)로 가공한다.

## 입력
- Swagger 메타데이터: `GET https://infuser.odcloud.kr/oas/docs?namespace=15084677/v1` (인증 불필요)
- 데이터 API: `GET https://api.odcloud.kr/api/15084677/v1/{최신 uddi 경로}` (파라미터: `page`, `perPage`, `serviceKey`)
- 환경변수: `DATA_GO_KR_SERVICE_KEY` (2a와 동일 — 단, 2b는 별도 API 상품이라 활용신청 승인이 따로 필요할 수 있음. 실제로는 사용자가 신청해봐야 확인됨)

## 처리 로직 개요
1. swagger를 조회해 `paths`의 summary 끝 날짜가 가장 최신인 경로(uddi)를 고른다(연도 하드코딩 금지 — 매년 새 uddi가 추가됨).
2. 해당 경로로 `page`를 늘려가며 `totalCount`에 도달할 때까지 전체 행을 가져온다(perPage를 크게 잡으면 보통 1페이지로 끝남, 약 300행).
3. 각 행의 발생형태 23종 합계를 `총계`와 대조(불일치 시 REVIEW 경고 — 스키마가 바뀐 것일 수 있음).
4. 로컬에 저장해둔 이전 실행 결과(연도 다름)와 비교해 "전년 대비 변화"를 계산. 비교 기준이 없으면(최초 실행) "기준 데이터 없음"으로 표시(단정 금지 원칙).

## 출력
- `accident_stats_<연도>.json`: API 원본 행 전체 + 합계 불일치 목록 (로컬 캐시, 다음 실행 때 전년 대비용 기준 데이터)
- 표준 출력에 수집 건수/불일치 건수 요약

## 예외 처리
- `serviceKey` 미승인/만료 → 즉시 실패(재시도 무의미), 에러 메시지 그대로 기록
- swagger에서 연도별 경로를 못 찾음(포털 구조 변경) → 명시적 에러로 중단, REVIEW
- HTTP 5xx/타임아웃 → 지수 백오프 재시도 최대 3회(`naver.py` 패턴)
- 총계 불일치 → 배치를 막지 않고 불일치 목록만 기록(트렌드 보조 지표라 완벽할 필요 없음, 단 보고는 함)

## 사용할 라이브러리
- `urllib.request`, `json` — 표준 라이브러리로 충분. pandas 등 무거운 라이브러리 사용 안 함(CLAUDE.md 원칙). (CSV 파싱은 더 이상 필요 없음 — API가 JSON을 직접 반환)

## 검증 기준 (실데이터) — 전부 통과 (2026-11-13)
- [x] 발급받은 실제 `DATA_GO_KR_SERVICE_KEY`로 최신 연도 데이터 실제 수신 확인 — `한국산업안전보건공단_산업중분류별 발생형태별 사고재해자수_20251231`, 300행
- [x] swagger 최신연도 자동 선택 로직이 실제 응답에서 맞게 동작 — 2020~2025 중 2025(최신)를 정확히 선택
- [x] 발생형태 23종 합계 vs `총계` 컬럼 대조 — **불일치 0건** (300행 전부 일치)
- [x] 메모리 사용량/실행시간 측정 — peak RSS 28,184KB(약 28MB), 실행시간 0.43초 (Oracle 1GB 환경 기준 충분히 여유)

## 다음 행동
`accident_stats.py`/`test_accident_stats.py` 프로젝트 루트로 이동 완료. Task 2a(SIF 아카이브)는 별도 블로커(data.go.kr 서비스 자체 오류, `NO_OPENAPI_SERVICE_ERROR`)로 계속 REVIEW 중 — `task-02a-sif-archive-lookup.md` 참고.

## 버그 발견·수정 (2026-11-16) — 출력 경로 불일치
Task 1~5 전체 실행(실데이터) 중 발견: `--out` 기본값이 **프로젝트 루트**(`accident_stats_<연도>.json`)였는데, `merge_briefing.py`(Task 3)는 `output/`에서 찾도록 돼 있어 기본 실행 시 서로 못 찾음(Task 3가 "통계 없음" 경고를 내고 `stat_context` 전부 null로 진행해버림 — 조용히 품질이 떨어지는 실패). 원인: Task 2b 구현 당시 다른 모든 스크립트가 `output/`을 기본값으로 쓰는 관례를 따르지 않았던 누락.
수정: 기본 출력 경로를 `output/accident_stats_<연도>.json`으로 변경, 디렉터리 없으면 자동 생성(`os.makedirs`). `test/`에서 재검증(실제 API 재수신, self-check 통과, `output/` 아래 정상 생성 확인) 후 루트로 재이동.
