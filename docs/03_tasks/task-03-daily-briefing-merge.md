# Task 3. 소스 통합 (뉴스 브리핑 후보 + 공공데이터 통계 컨텍스트)

상태: **완료 — 실데이터 검증 통과, 승인됨 (2026-11-16)**. `merge_briefing.py`는 `test/`에서 프로젝트 루트로 이동됨.

## 검증 결과 (2026-11-16, 대상일 2026-11-12)
- `briefing_candidates_2026-11-12.json`(63건) + `accident_stats_2025.json`(300행)으로 실행 — 63건 전부 유실 없이 출력
- 업종 매핑 27건에 Top3 발생형태 통계 정상 첨부: 제조업 계열(철강/반도체/자동차·설비보전) → 끼임/넘어짐/부딪힘 순, 전기·가스·증기·수도사업(발전소) → 넘어짐/떨어짐/감전 순 — 상식과 일치
- 미매핑 36건(업종 없음 35 + 방산 1) 전부 `stat_context: null`로 에러 없이 통과
- `accident_stats_*.json` 없는 상태로 실행 → 경고만 출력, 전부 null로 정상 종료(exit 0) 확인
- `briefing_candidates_<date>.json` 없는 날짜로 실행 → 에러 종료(exit 2) 확인

## 범위 재정의 (중요)
로드맵 원안은 "뉴스 + 공공데이터 후보를 하나의 전날 브리핑 후보 목록으로 병합, 중복 제거"였다. 그런데 Task 2 조사 결과:
- **2a(SIF 아카이브, 사건 단위 사례 조회)는 아직 블로커 상태**(`NO_OPENAPI_SERVICE_ERROR`, REVIEW) — 지금 쓸 수 있는 "사건 단위" 공공데이터가 없음.
- **2b(사고재해자수 통계)는 사건 단위가 아니라 연 1회 갱신되는 업종×규모×발생형태 집계** — "오늘 사고 후보"가 아니라 "참고 트렌드 숫자"임.

즉 지금은 **사건 단위 소스가 뉴스(1b) 하나뿐**이라 "중복 제거"할 두 번째 사건 소스가 없다. 그래서 Task 3을 "뉴스 브리핑 후보에 관련 업종의 통계 트렌드를 참고 컨텍스트로 붙여 Task 4용 단일 payload로 조립"으로 좁힌다. 교차 소스 중복 제거는 2a가 준비되면 별도로 추가한다(지금 구현하지 않음 — YAGNI).

## 목표
`briefing_candidates_<date>.json`(1b)의 각 기사에, 업종이 매칭되면 `accident_stats_<연도>.json`(2b)의 해당 업종 발생형태 통계를 참고 컨텍스트로 붙여 `daily_briefing_<date>.json`(Task 4 입력)을 만든다.

## 입력
- `output/briefing_candidates_<date>.json` — Task 1b 실제 출력 (`2026-11-12`: incidents 25건, safety_and_maintenance 38건 보유 중)
- `output/accident_stats_<연도>.json` — Task 2b 실제 출력 (`2025`: 300행 보유 중)
- 환경변수 불필요 (로컬 파일만 읦음, 네트워크 호출 없음)
- **업종 매핑 테이블 (신규, 코드 상수)** — 우리 7개 버킷(`INDUSTRY_TERMS`) ↔ KSIC 중업종. 실제 2025 데이터의 중업종 30개를 대조해 작성:
  - 정유·석유화학 → 화학및고무제품제조업, 의약품·화장품·연탄·석유제품제조업
  - 철강 → 금속제련업, 기계기구·금속·비금속광물제품제조업
  - 비철금속 → 금속제련업
  - 발전소 → 전기·가스·증기·수도사업
  - 반도체 → 전기기계기구·정밀기구·전자제품제조업
  - 자동차·설비보전 → 기계기구·금속·비금속광물제품제조업 (완성차 전용 중업종이 따로 없어 근사치 — 문서/출력에 "근사 매핑"이라고 표시)
  - 방산 → **매핑 없음** (KSIC에 무기제조 전용 중업종이 없음, 추측해서 끼워 맞추지 않음)

## 처리 로직 개요
1. `accident_stats_<연도>.json` 로드 → 중업종별로 같은 업종의 모든 "규모" 행을 합산해 발생형태 23종 벡터를 만든다(사업장 규모 구분은 여기서는 불필요).
2. 위 매핑 테이블로 우리 업종 → KSIC 중업종(들) → 합산된 발생형태 벡터를 가져온다. 여러 중업종에 매핑되면 합산.
3. `briefing_candidates`의 incidents/safety_and_maintenance 각 기사를 순회:
   - `industry_matches`가 비어있지 않고 매핑 테이블에 있으면 → 해당 통계에서 **발생형태 Top 3**(건수 기준)를 `stat_context`로 첨부 (예: `{"source_year": 2025, "top_event_types": [["끼임", 1234], ["부딪힘", 980], ["넘어짐", 711]]}`)
   - `industry_matches`가 비어있거나 매핑 없음(예: 방산, 혹은 일반 맥락만 매칭된 기사) → `stat_context: null`로 그대로 통과 (에러 아님)
4. 전년 대비 비교는 하지 않음 — 2b가 아직 1개 연도만 보유(기준 데이터 없음). 비교 로직은 2b가 2개 연도 이상 쌓이면 추가.
5. 기사 건수는 입력과 출력이 항상 같아야 한다(병합 과정에서 유실 없음 보장).

## 출력
- `output/daily_briefing_<date>.json`:
  ```
  {
    "target_date_kst": "...",
    "generated_at_kst": "...",
    "stats_year_used": 2025,
    "incidents": [ {...1b 필드, "stat_context": {...} | null} ],
    "safety_and_maintenance": [ {...} ],
    "unmapped_industry_count": N
  }
  ```

## 예외 처리
- `briefing_candidates_<date>.json` 없음 → 에러 종료(코드 2) — Task 1b를 먼저 돌려야 함
- `accident_stats_<연도>.json` 없음 → **경고만 출력하고 `stat_context` 전부 `null`로 진행**(통계 컨텍스트는 보조 정보라 필수 아님 — 뉴스 브리핑 자체는 통계 없이도 가치 있음)
- `accident_stats` 로드했는데 매핑된 업종이 하나도 없음 → 경고만(버그 아닐 수 있음, 그날 그 업종 기사가 없었을 수도)
- 연도 자동 선택: `output/` 안의 `accident_stats_*.json` 중 가장 최신 연도 파일을 고른다(여러 해가 쌓이면)

## 라이브러리/API
전부 표준 라이브러리: `json`, `argparse`, `pathlib`, `collections.Counter`(발생형태 합산/Top3용). 네트워크 호출 없음. 새 의존성 없음.

## 검증 기준
- [ ] 실제 `output/briefing_candidates_2026-11-12.json`(63건: incidents 25 + safety/maintenance 38) + `output/accident_stats_2025.json`(300행)로 실행
- [ ] 출력 건수 63건 그대로 유지(유실 없음)
- [ ] 업종 매핑된 기사(예: `matched_industry_terms`에 "정유·석유화학"/"자동차·설비보전" 포함)에 실제로 `stat_context`가 붙는지, Top3 발생형태가 상식과 맞는지(끼임/부딪힘/넘어짐류가 상위일 것으로 예상)
- [ ] 매핑 안 되는 기사(업종 없음 또는 방산)는 `stat_context: null`로 에러 없이 통과하는지
- [ ] `accident_stats` 파일을 일부러 지우고 실행 → 경고만 뜨고 전부 `null`로 정상 종료하는지(의존성 약화 확인)
- [ ] 결과를 사용자에게 제시 → Top3 발생형태가 실제로 유의미한지 피드백 수렴

---
이 구상대로(특히 범위 재정의와 업종 매핑 테이블) 진행해도 될지 확인 부탁한다.
