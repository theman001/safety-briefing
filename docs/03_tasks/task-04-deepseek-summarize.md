# Task 4. DeepSeek 요약 연동

상태: **완료 — 4차 변경(AI 맥락 기반 재분류) 실데이터 검증 통과, 승인됨 (2026-11-18)**. `classification` 필드를 AI 교정값으로 쓰도록 변경 후 루트로 이동 완료. 알려진 한계 1건(통계 인용 기사 병합 시 부속 사고정보 손실 가능성, 3차 때 발견)은 사용자가 인지하고 수용 — 아래 "검증 기록(3차)" 참고.

## 입력 스키마 관련 메모
Task 3(`output/daily_briefing_<date>.json`)는 아직 "구상 — 컨펌 대기" 상태(다른 세션에서 진행 중, 손대지 않음)이지만, 실제로 `output/daily_briefing_2026-11-12.json`(63건: incidents 25 + safety_and_maintenance 38, `stat_context` 포함)이 이미 실데이터로 존재해서 이걸 입력 스키마의 근거로 썼다. Task 3가 최종 컨펌되며 스키마가 바뀌면, 이 문서의 "입력" 절과 파싱 부분만 조정하면 된다(DeepSeek 호출 로직 자체는 영향 없음).

## 목표
`daily_briefing_<date>.json`의 각 기사(최대 63건 규모)를 DeepSeek API 1회 호출로 구조화 요약(업종/사고유형/핵심사실/추정원인(확인된 경우만)/정비·설비 교훈)해 `summarized_briefing_<date>.json`을 만든다.

## 입력
- `output/daily_briefing_<date>.json` — Task 3 실제 출력. 필요 필드: `title`, `description`, `link`, `classification`, `matched_industry_terms`, `stat_context`(있으면)
- API: `POST https://api.deepseek.com/chat/completions` (OpenAI 호환 포맷, 공식 문서 `api-docs.deepseek.com` 2026-11-16 확인)
  - 모델: `deepseek-flash` (저가 모델 — CLAUDE.md "저가 모델 위주 사용" 원칙. `deepseek-v4-pro`는 입력 4배/출력 3.3배 비쌈, 이 작업엔 과함)
  - 인증: 헤더 `Authorization: Bearer ${DEEPSEEK_API_KEY}`
  - **`"thinking": {"type": "disabled"}`로 명시 설정** — 기본값은 thinking 활성화인데, 이건 추론이 필요한 작업이 아니라 이미 분류된 기사의 구조화 추출이라 thinking 끄면 토큰(비용)과 지연이 줄어듦(의도적 설계 결정, 문서에 남김)
  - `response_format: {"type": "json_object"}`로 JSON 강제
- 환경변수: `DEEPSEEK_API_KEY` (`.env`, `dotenv_loader.py`로 로드 — 기존 패턴과 동일)

## 처리 로직 개요
1. `load_dotenv()` → `DEEPSEEK_API_KEY` 확인.
2. `daily_briefing_<date>.json` 로드. 입력 0건이면 **API 호출 자체를 스킵**하고 빈 요약으로 정상 종료(비용 절약, 에러 아님).
3. 전체 기사를 **1회 호출**로 처리(63건 전체 텍스트 ≪ 1M 컨텍스트, 분할 불필요 — 나중에 건수가 크게 늘면 그때 청크 분할 추가, 지금은 YAGNI).
4. 프롬프트 설계:
   - system: "사실 확인 전 사고 원인/발생일을 단정하지 않는다. 원문에 명시되지 않은 원인은 `probable_cause: null`로 두고 `needs_review: true`로 표시하라" 등 프로젝트 원칙을 명시적으로 지시.
   - system: **"입력 기사에 `stat_context`가 있으면, `maintenance_lesson`에 그 `top_event_types` 중 최소 1개 용어를 구체적으로 언급해 업종 통계와 연결하라"**를 명시적으로 지시 (2026-11-16 1차 실데이터 검증에서 발견한 문제의 수정 — 아래 "검증 기록" 참고. 데이터를 모델에게 주는 것과 "그걸 쓰라고 지시하는 것"은 별개라는 걸 실데이터로 확인).
   - user: 기사 배열을 `index`(0부터, 원본 순서 보존용) + title/description/classification/matched_industry_terms/stat_context만 추려 JSON으로 전달. (원문 전체 재크롤링 없음 — 이미 가진 title/description만 사용, 아키텍처 원칙과 일치)
   - 응답 형식 지시: `{"summaries": [{"index": int, "industry": str, "incident_type": str|null, "key_facts": str, "probable_cause": str|null, "maintenance_lesson": str|null, "needs_review": bool}, ...]}` — 반드시 입력과 같은 건수.
5. 응답 JSON 파싱 → `index`로 원본 기사와 매칭해 `title`/`link` 등을 다시 붙인다(모델이 지어낼 수 있는 필드는 모델 출력에서 가져오지 않고 전부 원본에서 가져옴 — 사실 왜곡 방지).
6. **입력 건수 == 출력 건수** 검증(Task 3와 동일한 유실 방지 원칙). 불일치 시 에러로 처리.

## 출력
- `output/summarized_briefing_<date>.json`:
  ```json
  {
    "target_date_kst": "...",
    "generated_at_kst": "...",
    "model": "deepseek-flash",
    "input_count": 63,
    "token_usage": {"prompt_tokens": 0, "completion_tokens": 0},
    "summaries": [
      {
        "title": "...", "link": "...", "classification": "...",
        "industry": "...", "incident_type": "..." ,
        "key_facts": "...", "probable_cause": null,
        "maintenance_lesson": "...", "needs_review": false
      }
    ]
  }
  ```

## 예외 처리
- `DEEPSEEK_API_KEY` 없음 → 즉시 종료(코드 2), 명시적 메시지
- HTTP 401(인증 실패) → 즉시 실패, 재시도 안 함
- HTTP 429/5xx/타임아웃 → 지수 백오프 재시도 최대 3회(`naver.py` 패턴)
- 응답이 JSON이 아니거나 `summaries` 키 없음 → 명시적 에러로 중단(부분 결과로 얼버무리지 않음)
- 입력 건수 ≠ 출력 건수 → 에러로 처리, 실패 보고(1차 구현에서는 개별 재시도 없음 — 전체 재실행 유도, YAGNI)
- `daily_briefing_<date>.json` 없음 → 에러 종료(Task 3 먼저 실행 필요)
- 입력 0건 → API 호출 스킵, 빈 결과로 정상 종료

## 사용할 라이브러리
- `urllib.request`, `json`, `os` — 표준 라이브러리로 충분. DeepSeek는 OpenAI 호환 API라 `openai` SDK를 쓰는 예제가 공식 문서에 있지만, **SDK 추가 대신 `urllib`로 직접 POST**(CLAUDE.md 원칙, `naver.py` 패턴 유지).

## 검증 기준 (실데이터)
- [ ] 실제 `DEEPSEEK_API_KEY`로 `output/daily_briefing_2026-11-12.json`(63건) 전체 요약 성공
- [ ] 입력 63건 = 출력 63건 (유실 없음)
- [ ] 샘플 5~10건 수동 대조: `key_facts`가 원문 title/description과 실제로 일치하는지, `probable_cause`가 원문에 근거 없이 지어낸 게 아닌지(가장 중요한 품질 게이트 — 날조 여부)
- [ ] `stat_context`가 있는 기사의 `maintenance_lesson`에 그 통계(Top3 발생형태)가 실제로 반영되는지
- [ ] 응답의 토큰 사용량 확인 + 메모리/실행시간 측정 (Oracle 1GB 환경 기준)

## 검증 기록
### 2026-11-16 1차 검증 — 63건 처리, 날조 방지는 통과, stat_context 반영 실패
- 실제 `DEEPSEEK_API_KEY`로 `output/daily_briefing_2026-11-12.json`(63건) 처리: 입력 63건 = 출력 63건, prompt 12,675 / completion 7,216 토큰(1센트 미만), peak RSS 28MB, 31초(대부분 API 대기).
- **날조 방지 게이트 통과**: `probable_cause`가 채워진 2건 모두 원문에 직접 근거(한국지엠 부평공장 "금속 피로 누적 절단 추정", 인천 방제훈련 "취급 부주의 — 훈련 가정 상황"임을 정확히 구분). 샘플 `key_facts`도 원문과 일치.
- **문제 발견**: `stat_context` 있는 기사 27건 중 샘플 4건 전부 `top_event_types`가 `maintenance_lesson`에 한 번도 언급 안 됨 — 데이터를 모델에 전달하기만 하고 "쓰라"고 지시하지 않았던 프롬프트 설계 누락. (참고: 그중 2건은 Task 3 쪽 업종 매칭이 과하게 느슨해 관련 없는 기사에도 stat_context가 붙어있었음 — Task 4 범위 밖, 여기서는 안 건드림.)
- 수정: system 프롬프트에 "`stat_context` 있으면 `maintenance_lesson`에 `top_event_types` 용어를 구체적으로 언급하라" 지시 추가 → 재검증.

### 2026-11-16 2차 검증 — max_tokens 버그, 관련성 오남용, 최종 해결
- 프롬프트 수정 후 재실행하니 `모델 응답 content가 JSON이 아님: Unterminated string` 에러. 원인: `max_tokens` 미지정 시 DeepSeek 기본값이 비-thinking 모드에서 8K인데(공식 문서 확인), 길어진 지시 때문에 completion이 8K를 넘어가며 중간에 잘림. `max_tokens: 16000` 명시 추가로 해결(재실행 시 completion 9,266 토큰, 정상 완료).
- stat_context 27건 전부 반영 성공했지만, 샘플 점검 중 **업종 매칭이 아예 잘못된 기사(선관위 서버 기사, 소방시설법 개정안 기사)에도 억지로 업종별 설비점검 조언이 붙는** 새 문제 발견 — "관련 있으면"이라는 조건부 지시를 모델이 일관되게 못 지킴. 프롬프트에 "먼저 기사가 실제로 그 업종 사고/설비와 관련 있는지 판단하라" 지시를 추가했지만 이 역시 부분적으로만 효과 있었음(일부 애매한 정책기사는 여전히 억지 연결).
- **최종 해결은 Task4가 아니라 상류(Task1b)에서**: `LAW_POLICY`/`OTHER` 레이블 추가로 애초에 잘못 태깅된 기사 자체가 `incidents`/`safety_and_maintenance`에 안 들어가게 됨 (상세: `task-01b-news-classify.md` 참고). Task3/Task4는 코드 변경 없이 더 정확해진 입력을 받아 1b+3+4 전체 재실행.
- **최종 결과**: 입력 59건(이전 63건에서 선관위 등 5건 OTHER로 빠짐) = 출력 59건. `stat_context` 25건 중 23건 반영, 나머지 2건(한솔제지/현대건설 기사)은 모델이 "선택된 통계는 이 사고와 직접 부합하지 않아 연결이 부적절하다"며 **스스로 판단해 생략** — 이것도 업종 매칭 자체가 상류에서 틀린 잔여 사례인데, 모델이 억지로 끼워맞추지 않고 올바르게 걸러낸 바람직한 동작. `needs_review` 8/59(14%, 1차 검증의 12/63과 비슷한 수준 — 중간에 1/63으로 떨어졌던 건 일시적 변동으로 판단). prompt 11,983/completion 8,105 토큰, peak RSS 28MB, 37초. **검증 통과, 사용자 승인 → 루트로 이동 완료.**

## 피드백 반영 (3차, 2026-11-16) — "유실 방지" 불변조건 재검토, 필터링 추가

### 배경
Task 5b 실데이터 검증(2026-11-12, 59건 전송)에서 사용자 피드백: "내용이 너무 방대함. AI한테 전달하는 시스템 프롬프트에 **중요도 낮은 것 제거 / 중복 기사 제거 / 연관성 없는 내용 제거**가 포함돼 있는지, 있다면 제대로 하고 있는지 확인 필요." 확인 결과 **그런 지시는 프롬프트에 전혀 없었고**, 그 이유는 우연이 아니라 `parse_summaries()`의 "입력 건수 == 출력 건수" 검증(114~115행)이 **필터링 자체를 구조적으로 금지**하고 있었기 때문(Task 3에서 이어받은 "유실 방지" 원칙을 너무 엄격하게 적용). 사용자 결정: **이 불변조건을 없애고 AI가 직접 중복/저중요도/무관 기사를 걸러내게 한다.**

### 설계 — 단, "유실 방지"의 원래 목적(무단 소실 방지)은 다른 방식으로 유지
단순히 응답 배열에서 기사를 빼버리는 방식은 채택하지 않는다 — 그러면 "몇 건이 왜 빠졌는지" 추적이 안 되고, 모델이 조용히 진짜 사고를 날려버려도 알 수 없다(원래 "유실 방지"가 막으려던 바로 그 상황). 대신:
- API 응답은 **여전히 입력과 같은 건수**를 요구한다(모든 `index`가 응답에 있어야 함 — 이건 "응답 파싱 무결성" 검증으로 의미가 바뀌는 것뿐, 그대로 유지).
- 각 `summaries` 원소에 새 필드 `dropped`(bool)와 `drop_reason`(string|null)을 추가한다. `dropped: true`인 원소는 다른 필드(industry 등)를 null로 둬도 된다.
- 후처리 단계에서 `dropped: false`인 것만 최종 `summaries`에 담고, `dropped: true`인 것은 `title`/`link`/`drop_reason`만 추려 별도 `dropped` 배열에 담아 **감사(audit) 기록으로 남긴다** — 완전히 사라지는 기사는 없음, 다만 Task 5b가 보는 최종 목록에서는 빠짐.

### system 프롬프트 추가 지시 (기존 지시에 추가)
- "입력 기사들 중 사실상 동일한 사건(같은 사고/같은 발표)을 다른 매체가 보도한 중복 기사를 찾아내라 — 가장 정보가 많은 1건만 `dropped: false`로 두고, 나머지 중복 기사는 `dropped: true`, `drop_reason`에 '중복 (index N과 동일 사건)' 형태로 적어라."
- "사고·설비와 직접 관련성이 낮아 교훈을 얻기 어려운 기사(단순 통계 발표, 행사·캠페인 소개, 일반 정책 기사 등)도 `dropped: true`로, `drop_reason`에 간단한 이유를 적어라."
- "그 외 기사는 `dropped: false`로 두고 기존 필드를 작성하라."

### 출력 스키마 변경
```json
{
  "target_date_kst": "...", "generated_at_kst": "...", "model": "deepseek-flash",
  "input_count": 59, "kept_count": 0, "dropped_count": 0,
  "token_usage": {...},
  "summaries": [ "...dropped:false 항목만, 기존 필드 그대로..." ],
  "dropped": [ {"title": "...", "link": "...", "classification": "...", "drop_reason": "..."} ]
}
```
Task 5b(`telegram_send.py`)는 `summaries` 필드만 그대로 읽으므로 **코드 변경이 전혀 필요 없음** — 이미 최종 목록만 받는 구조라 자연히 호환.

### 검증 기준 (추가, 실데이터)
- [ ] `output/daily_briefing_2026-11-12.json`(59건)로 재실행 — `kept_count` + `dropped_count` == 59 확인(건수 불일치 없음, 응답 파싱 무결성 유지)
- [ ] 실제 중복으로 알고 있는 사례(예: "노동부 화재·폭발 집중점검"/"산업재해 사망자 19.9% 감소... 화재·폭발 증가" — 같은 고용노동부 발표 기반 두 기사)가 실제로 중복으로 잡혀 하나만 남는지 수동 확인
- [ ] `dropped` 배열을 전부 수동으로 훑어, 진짜 유의미한 사고가 잘못 제거된 사례(오탐)가 있는지 확인 — **가장 중요한 품질 게이트**(날조 방지만큼 중요: "과잉 제거"도 이 프로젝트 목적("조기 발견")을 해침)
- [ ] 필터링 전후 건수 비교(59건 → 몇 건?)가 과도하지 않은지(예: 절반 이상 날아가면 의심)
- [ ] `needs_review`(사실확인 필요)와 `dropped`(최종 제외)가 서로 다른 의미로 올바르게 쓰이는지(둘 다 true인 경우가 있어도 되는지 등)

## 검증 기록 (3차, 2026-11-16) — 4회 반복, 최종 승인
실제 `DEEPSEEK_API_KEY`로 `output/daily_briefing_2026-11-12.json`(59건) 4회 반복 실행. 매번 peak RSS ~28MB, 23~38초.

1. **1차**: 14건 유지/45건 제외(76%) — **과도함.** 중복 제거(GS칼텍스 7→1, 인천 남동구 7→1, 가스안전공사 3→1)는 정확했으나, "저관련성" 기준이 넓어서 SAFETY_TREND(안전동향) 버킷이 38건→2건으로 거의 전멸 — 정책/기술동향 기사(AI 위험성평가, 작업중지권 확대, 피지컬 AI 등)까지 "저관련성"으로 같이 날아감. 사용자 피드백으로 기준 재정의.
2. **2차**: 프롬프트에 "저관련성은 순수 행정 반복 공지(지자체 정기 교육 안내 등)에만 좁게 적용, 정책변화·기술도입·점검결과는 유지, 애매하면 유지" 추가 → 35건 유지/24건 제외(41%). 1차에서 잘못 빠졌던 정책/기술 기사 전부 복구됨. 다만 "노동부/에스원 통계" 기사 3건(같은 보도자료, 다른 숫자 강조)이 이번엔 중복으로 안 잡히고 전부 남음 — 사용자가 "중복 판정 → 중요도 판정 순서를 명시하면 안 되는지" 제안.
3. **3차**: 프롬프트를 "1단계(중복 판정, 전체 대상) → 2단계(중요도 판정, 1단계에서 안 걸린 것만 대상)"로 명시적 순서화 + "같은 발표를 다른 통계치/제목으로 강조해도 동일 사건으로 본다" 추가 → 34건 유지/25건 제외(42%), 에스원 3건 중복도 정확히 1건으로 묶임. **그런데 부작용 발견**: `needs_review`가 34/34(100%) true로 찍힘 — "dropped가 애매하면 needs_review를 true로" 문구가 원래 의미(원인 불확실)와 충돌해 전체 오염. 즉시 수정(해당 문구에서 needs_review 연결 제거, "dropped가 애매하면 dropped를 false로"만 남기고 needs_review는 probable_cause 불확실성 전용으로 명확화).
4. **4차(최종)**: 27건 유지/32건 제외(54%), `needs_review` 9/27(33%)로 정상 복귀. 전체 dropped 32건 수동 전수 확인 — 거의 전부 타당(중복 클러스터 정확, 순수 행정공지 정확). **알게 된 잔여 한계 1건**: "대통령은 칭찬했지만... 10월 산재 사망 다시 늘었다" 기사가 "에스원 통계" 기사와 "동일 보도자료 인용"으로 중복 처리돼 제거됐는데, 원문 대조 결과 이 기사에는 **다른 어디에도 없는 구체적 사고(현대제철 제철소 설비 끼임 사망, DL이앤씨 관련)**가 추가로 담겨 있었음 — "같은 통계를 인용"했다는 이유만으로 그 안의 고유 사고 정보까지 묻힌 사례. 한 단계 더 조건을 추가하면 고칠 여지는 있으나, 그만큼 프롬프트가 길어지고 실행마다 판단이 미세하게 달라지는 run-to-run 변동도 커짐. **사용자 결정: 이 한계를 알고 받아들이고 현재 수준에서 승인, 추가 조정 중단.**
- **최종 승인**: `kept_count`(27)+`dropped_count`(32)=59 일치, 중복 제거·저중요도 분리 명확, `needs_review`/`dropped` 의미 분리 정상. 위 1건의 알려진 한계(통계 인용 기사 병합 시 부속 사고정보 손실 가능성)를 문서화한 채 **승인 → 루트 이동**.

---
이 구상대로(특히 1회 호출·thinking 비활성화·index 매칭 방식) 진행해도 될지 확인 부탁한다. ~~(승인됨, 완료)~~

3차 변경(`dropped`/`drop_reason` 필터링)을 이 구상대로 진행해도 될지 확인 부탁한다. ~~(승인됨, 완료)~~

## 피드백 반영 (4차, 2026-11-18) — AI의 "맥락 기반 재분류" 역할 추가

### 배경
`task-01b-news-classify.md`의 "피드백 반영 (4차)" 참고 — Task 7 실운영 중 키워드 기반 1차 분류(`classification`)가 보험상품 기사/입법추진 기사를 `INCIDENT_FOLLOWUP`(사고)으로 잘못 분류하는 사례가 재발. 키워드만으로는 "법적·보상 어휘 포함"과 "실제 특정 사고의 후속보도"를 구분하기 어렵다는 게 2026-11-13/11-16/11-18 세 차례 반복 확인됨.

### 사용자 결정 — 역할 분리
**Task 1b(키워드)는 재현율 중심의 거친 1차 필터로 유지하고, Task 4(AI)가 title/description 본문을 직접 읽어 최종 `classification`을 판단하는 "맥락 기반 재분류"를 새로 맡는다.** 근거: 1b가 걸려 넘어진 두 사례 모두, 같은 title/description 텍스트를 AI가 읽으면(이미 Task 4 입력에 포함되어 있음) "보험상품 소개"/"법안 추진"이라는 성격을 키워드 없이도 구분할 수 있다 — 특히 원전 입법 기사는 Naver 제목 절단으로 "발의"라는 단어 자체가 날아갔어도, AI는 "처벌 추진"+"교사·공모자까지"+역사적 사례 언급이라는 문맥으로 입법 기사임을 알 수 있어, 키워드 매칭의 구조적 약점(절단·범용어)에 안 걸린다.

### 처리 로직 변경
- `build_request_payload()`가 이미 각 기사에 1b의 `classification`을 포함해 전달하고 있음(62~73행) — 이걸 "참고용 1차 추정치"로 명시하고, system 프롬프트에 교정 지시를 추가한다.
- **system 프롬프트 추가 지시**: "입력 각 기사의 `classification`은 키워드 기반 1차 분류로, 참고용 추정치일 뿐 그대로 믿지 않는다. title/description 본문을 직접 읽고 그 분류가 실제로 맞는지 판단해 최종 `classification`을 결정하라. 예: 1차 분류가 INCIDENT_REPORT/INCIDENT_FOLLOWUP(사고 보도)으로 왔어도 실제 내용이 보험상품 소개, 법안/제도 추진, 통계 발표처럼 특정 사고 1건을 보도하는 게 아니면 SAFETY_TREND 또는 LAW_POLICY로 교정하라. 반대로 1차 분류가 안전동향 등으로 왔어도 실제로 특정 사고를 보도하는 기사면 INCIDENT_REPORT/INCIDENT_FOLLOWUP으로 교정하라. 최종 `classification`은 INCIDENT_REPORT/INCIDENT_FOLLOWUP/SAFETY_TREND/MAINTENANCE_TECH/LAW_POLICY 중 하나여야 한다(Task 4 입력에 들어오는 기사는 이미 이 5개 중 하나로 1차 분류된 것들만이므로, 교정값도 이 범위 안에서 고른다)."
- **출력 스키마 변경**: `summaries` 각 원소에 `classification`(string) 필드 추가(AI가 반환하는 최종 교정값). `dropped: true`인 원소도 `classification`은 채운다(감사 기록에 남기기 위해).
- **`parse_summaries()` 변경**: 149행 `"classification": article.get("classification")`(1b 값 그대로 복사)을 AI가 반환한 값으로 교체. 단, AI가 허용된 5개 라벨 밖의 값을 반환하거나 비워두면 **조용히 버리지 않고** stderr 경고 로그를 남긴 뒤 원본 1b `classification`으로 폴백한다(사실 확인 안 된 값을 침묵 수용하지 않는다는 프로젝트 원칙과 동일 맥락).
- `split_dropped()`/`build_sections()`(telegram_send.py) 등 하류는 **코드 변경 없음** — 이미 `summaries[].classification` 필드를 그대로 읽는 구조라 자연히 호환.

### 출력 스키마 (갱신)
```json
{
  "...": "...",
  "summaries": [
    {
      "title": "...", "link": "...",
      "classification": "...",   // AI가 교정한 최종값 (신규 — 기존엔 1b 값 그대로 복사)
      "industry": "...", "incident_type": "...",
      "key_facts": "...", "probable_cause": null,
      "maintenance_lesson": "...", "needs_review": false
    }
  ]
}
```

### 검증 기준 (추가, 실데이터)
- [ ] 2026-11-17 데이터(서버 `daily_briefing_2026-11-17.json`)로 재실행 — "NH농협생명..." 기사의 최종 `classification`이 `INCIDENT_FOLLOWUP`에서 `SAFETY_TREND`(또는 적절한 값)로 교정되는지 확인
- [ ] "원전 사고 은폐..." 기사도 1b 단계 수정(LAW_TITLE description 확장)으로 이미 `LAW_POLICY`가 됐을 수 있음 — 만약 1b에서 안 고쳐진 채로 들어와도 Task 4가 `LAW_POLICY`로 교정하는지 이중 확인(1b 수정이 빠지거나 제목이 또 다르게 잘려도 Task 4가 최종 방어선 역할을 하는지가 핵심 목적)
- [ ] 기존에 올바르게 분류되던 사고 기사들(한솔제지 끼임, 여수산단, 태영건설 등)의 `classification`이 AI 교정 과정에서 실수로 바뀌지 않는지(회귀 없음) 전수 확인
- [ ] AI가 허용 범위 밖 값을 반환하는 경우를 의도적으로 재현하기 어려우므로, 폴백 로직은 코드 레벨 단위 테스트(`test_deepseek_summarize.py`)로 검증
- [ ] 텔레그램 최종 메시지에서 두 기사가 "오늘의 사고"가 아니라 "안전동향·정비기술" 섹션(또는 적절한 섹션)으로 옮겨졌는지 실제 섹션 분배 확인

### 검증 (2026-11-18) — 통과, 승인됨
서버 실제 운영 데이터(`daily_briefing_2026-11-17.json`, 24건: incidents 12 + safety_and_maintenance 12)로 실제 `DEEPSEEK_API_KEY` 호출 검증. 일부러 **1b 수정 전**(두 기사 모두 여전히 `INCIDENT_FOLLOWUP`인) 원본으로 돌려 Task 4 단독 방어선 역할까지 확인:
- "원전 사고 은폐…" → AI가 `LAW_POLICY`로 교정, `key_facts`/`maintenance_lesson`도 입법 기사에 맞게 재작성됨.
- "NH농협생명…" → AI가 `SAFETY_TREND`로 교정하면서 "보험상품 홍보성 기사"로 자체 drop까지 — 설계보다 한 걸음 더 적절한 결과.
- 기존 정상 사고 8건(여수산단/청주 환경미화원/태영건설/HD현대삼호/한솔제지/영월 시멘트/현대엔지니어링 등) 전부 `INCIDENT_REPORT`/`FOLLOWUP`로 유지 — 회귀 없음. 16건 유지/8건 제외, prompt 5,218 / completion 3,528 토큰.
- 폴백 로직(AI가 허용 범위 밖 값 반환 시 원본값 유지)은 실데이터로 재현이 어려워 `test/test_deepseek_summarize.py` 단위테스트로 검증, 통과.
- 실행시간 15.3초(대부분 API 대기), peak RSS 28.7MB — 기존 벤치마크(28MB)와 동일 수준.
- 텔레그램 섹션 분배는 `build_sections()`가 `classification` 필드만 보는 구조라 코드상 자명(변경 없음) — 불필요한 중복 텔레그램 전송은 생략.
- **승인 → `deepseek_summarize.py` 루트로 이동 완료.**
