# Task 1. 뉴스 수집 · 1차 분류 (네이버 뉴스 API) — 참고 자료

상태: **참고용 — 정식 채택 안 함.** 사용자 결정(2026-11-13): 처음부터 재설계. 이 문서는 `naver.py`가 이미 어떻게 구현돼 있었는지 기록용으로만 남긴다. 실제 재설계 구상은 `/plan-task`로 새 문서(`task-01-*.md` 갱신 또는 신규)에 작성한다.

## 기존 구현체 (참고, 재사용하지 않음)
`naver.py` (프로젝트 루트, 639줄, Python 3.9+ 표준 라이브러리만 사용)

## 입력
- 네이버 API HUB 뉴스 검색 엔드포인트 (`https://naverapihub.apigw.ntruss.com/search/v1/news`)
- 인증: `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` 환경변수 (파일에 기록 안 함)
- 산업별 검색어 16개(정유·철강·비철금속·발전소·방산·반도체·자동차/설비보전 등), 쿼리당 최대 페이지만큼 페이징
- `--date` (기본: 어제, KST), `--offline-zip`(재분석용), `--quick`(8개 대표 쿼리만)

## 처리
1. pubDate 기준 "대상일"만 필터링 (API에 날짜 파라미터가 없어 페이징 후 필터)
2. canonical URL 기준 중복 제거 + 제목 유사도(≥0.9) 기반 "유사 의심" 표시(삭제하지 않음)
3. 규칙 기반 분류: `INCIDENT_REPORT` / `INCIDENT_FOLLOWUP` / `SAFETY_TREND` / `MAINTENANCE_TECH` / `REVIEW` / `EXCLUDED`
   - 제목의 산업/설비 키워드 + 사고 강도 키워드 + 경제/행정 오탐 키워드로 점수화
   - 애매하면 `REVIEW`로 보류 (사실 확인 전 단정하지 않는다는 원칙)

## 출력 (ZIP)
- `metadata.json`, `raw_*.json`(온라인 실행 시 원본), `articles_all.csv`, `articles_incidents.csv`, `articles_insights.csv`, `articles_review.csv`, `articles_excluded.csv`, `briefing_candidates.json`, `dedup_report.json`

## 예외 처리 (기존 구현)
- HTTP 429/5xx 지수 백오프 재시도(최대 3회)
- JSON 파싱 실패/응답 이상 시 명시적 예외로 중단, 종료코드 2
- 대상일 기사 0건이면 경고 출력(날짜 범위/페이지 커버리지 재확인 유도)

## 재설계 시 참고할 점 (버리지 말 것)
- 네이버 API는 날짜 파라미터가 없어 페이징 후 pubDate로 직접 필터해야 함
- "사실 확인 전 사고 원인/발생일 단정 금지, 애매하면 REVIEW" 원칙은 재설계에도 그대로 적용
- 산업별 키워드 세트, 경제/행정 기사 오탐 필터링 아이디어는 새 분류 로직 설계 시 출발점으로 검토 가능

## 다음 행동
`/plan-task 1` 실행 → 재설계 구상 문서 작성 → 사용자 컨펌 → 구현.
