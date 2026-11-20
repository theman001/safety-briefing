# Task 3b. 기사 원문 전체 수집 (Task 3 ↔ Task 4 사이)

상태: **완료 — HTMLParser 기반 재작성 실데이터 검증 통과, 승인됨 (2026-11-20)**. `fulltext_fetch.py`는 `test/`에서 프로젝트 루트로 이동됨. 1차 구현(정규식 기반)은 실데이터 검증에서 버그 2건 발견 → 아래 "검증 기록" 참고.

## 배경
사용자 피드백: "Output(텔레그램 최종 메시지) 퀄리티에 대해서 개선이 필요해. 기사 원문 전체를 못가져오니까 원인 파악이나 그런게 전혀 안되지." `news_fetch.py`는 Naver 뉴스검색 API의 title+description(100~200자 스니펫)만 쓰고 있어, Task 4(DeepSeek)가 `probable_cause`/`key_facts`를 채울 근거 자체가 애초에 부족했다.

사용자가 제시한 두 방안 중 **방안1(1차 필터링된 기사 전체의 원문을 가져와 AI에 전달)**을 선택함(방안2: AI 2차 필터링 후 생존 기사만 원문 취득 — 실제 건수 차이가 크지 않고(15~25건 vs 10~16건), 방안1은 중복판정·저관련성판정·분류교정 등 Task 4의 다른 판단에도 원문을 활용할 수 있어 선택).

## 사전 조사 (실데이터, 추측 아님)
`output/news_raw_2026-11-17.json`(108건)의 실제 `link` 필드로 직접 `urllib.request` GET 테스트:
- **Naver 뉴스 링크**(`n.news.naver.com`, 108건 중 24건 = 22%): `id="dic_area"` 컨테이너를 정규식으로 뽑으면 원문 전체가 안정적으로 추출됨. 실제 테스트 기사("필리핀 이주노동자 사망")에서 스니펫엔 없던 구체적 원인("그라인더로 연마작업 중 깨진 연삭숫돌 파편에 몸이 맞아 숨졌다")이 원문에만 있었음을 확인.
- **언론사 자체 링크**(나머지 78%, 수십 개 도메인): 샘플 7개 중 4개(울산프레스/유제일/에이빙/한국농어민신문)가 `id="article-view-content-div"`라는 동일 CMS 템플릿을 공유해 같은 패턴으로 추출 성공. 나머지 3개(베타뉴스/아주경제/아시아투데이)는 구조가 달라 매칭 안 됨.
- 종합: 전체 기사의 대략 50~70%는 이 두 패턴으로 원문 전체 추출 가능, 나머지는 매칭 실패 시 description(스니펫)으로 자연 폴백. 억지로 범용(generic readability-style) 추출기를 만드는 건 광고·관련기사 텍스트 혼입 위험이 더 크다고 보고 **이번엔 배제**(YAGNI — 패턴이 안 맞으면 그냥 포기, 커버리지 늘리는 작업은 나중에 필요성이 보이면 추가).
- Task 4 입력(Task 3 출력: `incidents`+`safety_and_maintenance`) 실제 건수는 하루 15~25건 수준(2026-11-17: 24건, 2026-11-19: 19건) — fetch 대상이 많지 않아 순차 처리로 충분.

## 인프라 제약 해석에 대한 확인 요청
CLAUDE.md는 "헤드리스 브라우저(Selenium/Playwright 등) 금지. HTTP API/RSS만 사용"이라고 규정한다. 이 작업은 공식 API가 아니라 **제3자 언론사 웹페이지의 HTML을 직접 GET해서 긁어오는 것**이다. JS 렌더링이 필요한 헤드리스 브라우저는 전혀 쓰지 않으므로(순수 `urllib.request` GET + 정규식, 메모리 부담 없음) 제약의 문구·취지(1GB RAM에서 브라우저 엔진 금지)에는 위배되지 않는다고 해석했다. 다만 이건 "API 호출"과는 성격이 다른 신규 동작(불특정 다수 언론사 사이트에 매일 자동 GET)이라는 점을 명시적으로 남긴다 — 문제 시 언제든 이 Task를 비활성화(Task 4가 description만 쓰는 기존 동작으로 폴백)하면 된다.

## 목표
Task 3 출력(`daily_briefing_<date>.json`)의 각 기사에 대해, 가능한 경우 원문 본문 전체를 수집해 `full_text` 필드로 덧붙인 `daily_briefing_enriched_<date>.json`을 만든다. 실패하면 해당 기사만 조용히 description으로 폴백한다(전체 파이프라인은 항상 성공).

## 입력
- `output/daily_briefing_<date>.json` — Task 3 실제 출력. 기사별 `title`/`description`/`link`/`originallink` 필요(이미 1a에서 수집해 그대로 흘러들어온 필드).
- 환경변수/API 키 불필요 (공식 API 호출이 아니라 일반 HTTP GET).

## 처리 로직 개요
1. `daily_briefing_<date>.json` 로드. `incidents`+`safety_and_maintenance` 전체를 대상으로 순회.
2. 각 기사: `link`(없으면 `originallink`)로 GET 요청(`User-Agent` 지정, 타임아웃 15초, 실패 시 최대 2회 재시도 — `news_fetch.py` 패턴 재사용하되 재시도 횟수는 적게. 상대가 내 API가 아니므로 과도한 재시도로 부담 주지 않음).
3. 응답 HTML에 아래 패턴을 **순서대로** 시도(먼저 매칭되는 것을 채택):
   - `id="dic_area"` ... `</article>` (Naver 뉴스)
   - `id="article-view-content-div"` ... 닫는 `</div></div>` (공통 CMS 템플릿)
4. 매칭되면: 태그 제거(`re.sub(r"<[^>]+>", " ", ...)`) → `html.unescape()` → 공백 정규화 → `full_text`, `full_text_source`(`"naver_dic_area"` / `"common_cms"`)에 저장.
5. 매�칭 실패/HTTP 에러/타임아웃: `full_text = None`, `full_text_source = "fallback_description"`(또는 실패 원인 구분용 `"fetch_failed"`) — **에러로 처리하지 않고 그 기사만 스킵**, 파이프라인은 계속 진행.
6. 모든 기사 처리 후 원본 스키마에 `full_text`/`full_text_source` 필드만 추가해 저장(기존 필드는 그대로 보존 — 하류 호환).

## 출력
- `output/daily_briefing_enriched_<date>.json` — 입력과 동일 구조 + 기사별 `full_text`(string|null), `full_text_source`(string) 필드 추가.
- 메타: 처리 건수, `full_text_source`별 건수 집계(커버리지 추적용, stdout 출력 또는 `_meta.json`).
- Task 4는 이후 이 파일을 입력으로 쓰도록 바뀐다(이번 Task 범위 밖 — 별도 `/reflect`로 Task 4 쪽 프롬프트/파싱 변경을 다룬다. 이번 Task 3b는 enriched 파일 생성까지만).

## 예외 처리
- 입력 파일 없음 → Task 3 먼저 실행 필요, 에러 종료(코드 2)
- 입력 0건 → fetch 스킵, 빈 결과로 정상 종료
- 개별 기사 fetch 실패(네트워크 오류/타임아웃/4xx/5xx/패턴 불일치) → 그 기사만 `fallback_description`/`fetch_failed`로 처리, 파이프라인 중단 안 함(위 5번)
- `link`/`originallink` 둘 다 없음 → fetch 스킵, `fallback_description`
- 응답이 비정상적으로 큼(예: 8MB 초과) → 그만큼만 읽고 패턴 매칭 시도(기존 `news_fetch.py`의 `res.read(8_000_000)` 상한 패턴 재사용)

## 사용할 라이브러리
전부 표준 라이브러리: `urllib.request`, `re`, `html`, `json`, `time`. 새 의존성 없음(`beautifulsoup4` 등 HTML 파서 라이브러리는 이번 범위(2개 고정 패턴)에선 불필요 — 패턴이 늘어나 정규식이 감당 안 되면 그때 재검토, 지금은 YAGNI).

## 검증 기준 (실데이터)
- [ ] `output/daily_briefing_2026-11-19.json`(실제 19건, 로컬에 없으면 서버에서 가져와 사용)으로 실행 — 전체 건수 유실 없이 `full_text`/`full_text_source` 필드 추가되는지 확인
- [ ] `full_text_source`별 분포 확인 — `naver_dic_area`+`common_cms` 합산 비율이 사전조사 추정치(50~70%)와 비슷한 범위인지
- [ ] 추출된 `full_text` 샘플 5~10건 수동 대조 — 원문과 실제로 일치하는지(광고/관련기사 텍스트 혼입 없는지), description보다 실질적으로 더 많은 정보(특히 원인 관련 서술)를 담고 있는지
- [ ] 의도적으로 깨진/존재하지 않는 링크로 폴백 동작 확인(에러로 안 죽고 `fetch_failed`로 처리되는지)
- [ ] 실행시간/메모리 측정 — 15~25건 순차 GET이 1GB RAM·배치 러닝타임 제약에 무리 없는지(news_fetch.py의 108건 fetch 선례와 비교)
- [ ] 과도한 재시도로 상대 서버에 부담을 주지 않는지(재시도 횟수·백오프 설계가 적절한지) 코드 리뷰 수준에서 확인

---
이 구상대로 구현해도 될지 확인 부탁한다. 특히 "헤드리스 브라우저 금지" 제약 해석(위 "인프라 제약 해석에 대한 확인 요청" 참고)에 이견이 없는지 확인 바란다. ~~(승인됨 — "진행해. (언론사 웹페이지를 직접 GET해서 긁어오는 행위 승인)")~~

## 검증 기록 (1차, 2026-11-20) — 정규식 방식, 버그 2건 발견

로컬 실데이터 `output/daily_briefing_2026-11-17.json`(실제 24건)으로 `test/fulltext_fetch.py` 실행:
- 유실 없음(24건 전부 처리), `full_text_source` 분포: `naver_dic_area` 4 / `common_cms` 16 / `fallback_description` 4 — 매칭률 20/24(83%), 사전조사 추정(50~70%)보다 좋음.
- peak RSS 30.5MB, 24건 순차 처리 5.68초 — 1GB 제약에 여유.
- 깨진 링크(`fetch_failed`)·링크 없음(`fallback_description`) 폴백 동작 둘 다 정상.
- **샘플 수동 대조(핵심 품질 게이트)에서 버그 2건 발견** — 매칭됐다고 표시된 20건 중 4건(20%)이 실제로는 `description`보다도 짧은 쓰레기 추출이었음. 실제 HTML을 직접 열어 원인 확정(추측 아님):
  1. **조기 종료**: `common_cms` 패턴의 종료조건 `</div>\s*</div>`가, 기사가 사진/캡션(`<figure><div class="IMGFLOATING">...`)으로 시작할 때 그 사진 블록 내부의 중첩 div에서 먼저 멈춤. "농업도 일터다... NH농협생명..." 기사 원본 HTML 확인: 진짜 본문은 사진 캡션 뒤에 이어지는데, `full_text`엔 "사진=리버티코리아포스트" 12자만 남음.
  2. **HTML 주석 누수**: 본문 앞에 `<!-- <div class="...">일부 텍스트</div> -->` 형태의 주석이 있는 페이지에서, 태그 제거 정규식(`<[^>]+>`)이 `<!--`와 그 안의 여는 태그를 하나로 묶어 지우면서 주석 "안쪽 텍스트"만 살아남고 주석을 닫는 `-->`는 글자로 남음. "강진군, 하반기 근로자 정기 안전보건교육 마무리" 기사 원본 HTML 확인: `full_text`가 `"지역공동체·공공근로... 호응 --> [CBC뉴스]"`로 나옴(주석 내용 + 깨진 `-->` + 그 뒤 진짜 본문 첫 줄에서 또 조기종료).
- 두 버그 다 **정규식으로 중첩 HTML을 다루는 근본적 한계**(패턴 추가로는 해결 안 됨, 다른 사이트에서 다른 형태로 재발 예상).

## 설계 변경 — HTMLParser 기반 재작성 (사용자 승인, 2026-11-20)
정규식 경계 매칭을 버리고 표준 라이브러리 `html.parser.HTMLParser`로 교체한다(신규 의존성 없음 — `beautifulsoup4` 등은 불필요, YAGNI):
- `HTMLParser` 서브클래스가 태그 depth를 추적하다가, 목표 id(`dic_area` 또는 `article-view-content-div`)를 가진 시작 태그를 만나면 그 depth를 기록하고 수집 모드 진입.
- 수집 모드 동안: `handle_starttag`로 depth+1, `handle_endtag`로 depth-1 — depth가 시작 depth 밑으로 내려가는 **진짜 짝 맞는 닫는 태그**를 만날 때만 수집 종료(중첩된 `<div>`가 몇 겹이든 정확히 추적되므로 사진 캡션 블록의 조기 종료 문제가 구조적으로 사라짐).
- `handle_data`로 텍스트만 수집(태그 제거 정규식 불필요 — 애초에 태그가 섞여 들어오지 않음).
- `handle_comment`는 아예 구현하지 않거나 `pass`로 둬서 주석 내용을 수집 대상에서 완전히 배제(정규식의 "주석을 태그로 오인" 문제가 구조적으로 사라짐).
- `<script>`/`<style>` 내부 텍스트는 `handle_starttag`에서 해당 태그를 만나면 일시적으로 데이터 수집을 멈추는 플래그로 제외(기존 `SCRIPT_STYLE_RE` 사후 제거 방식 대신 수집 시점에 원천 배제).
- `extract_full_text(html_doc) -> tuple[str|None, str]` 함수 시그니처는 그대로 유지(호출부 변경 없음) — 내부 구현만 교체.

## 검증 기준 (추가, 실데이터)
- [ ] 2026-11-17 데이터(24건) 재실행 — 이전에 쓰레기였던 4건(NH농협생명/강진군/원자력안전기술원/[오늘] 중대재해)이 이번엔 `description`보다 긴, 실제 본문으로 제대로 뽑히는지 확인
- [ ] 기존에 정상이었던 16건(태영건설/한솔제지/원전입법 등)이 회귀 없이 그대로 정상 추출되는지 확인
- [ ] `full_text` 어디에도 `-->`, `<script`, `function(` 같은 마크업/코드 잔재가 안 남는지 전수 grep
- [ ] 메모리/시간이 기존(30.5MB/5.68초)과 비슷한 수준인지(HTMLParser가 정규식보다 약간 느릴 수 있으나 24건 규모에선 무의미한 차이로 예상)

## 검증 기록 (2차, 2026-11-20) — HTMLParser 방식, 통과
같은 로컬 실데이터(`daily_briefing_2026-11-17.json`, 24건)로 재실행:
- 유실 없음(24건 전부 처리), `full_text_source` 분포 동일: `naver_dic_area` 4 / `common_cms` 16 / `fallback_description` 4(패턴 매칭률 83%, 변화 없음 — 당연함, 대상 사이트 구조는 그대로이므로 매칭 자체는 동일하고 "무엇을 올바르게 뽑아내는가"만 개선됨).
- **쓰레기 추출 4건 전부 해결 확인**: NH농협생명(12자→3,491자), 원자력안전기술원(37자→1,060자), "[오늘] 중대재해"(11자→889자), 강진군(40자→887자). `full_text`가 `description`보다 짧은 경우(`ft_len < desc_len`) **0건**(1차 검증 때는 4건) — 이 지표로 자동 검증 가능함을 확인.
- 기존 정상 16건 회귀 없음(태영건설/한솔제지/원전입법 등 전수 재확인, 내용 동일하거나 더 풍부해짐).
- `-->`, `<!--`, `function(`, `var `, `getElementById` 등 마크업/코드 잔재 전수 grep — **0건** 검출.
- 악성/깨진 HTML(안 닫힌 태그, 빈 문자열, HTML 아닌 텍스트)로 크래시 안 나는지 별도 확인 — 전부 정상 처리(크래시 없음, 안 닫힌 태그는 best-effort로 그 시점까지 수집된 텍스트 반환).
- peak RSS 30.4MB, 24건 5.15초 — 1차 검증(30.5MB/5.68초)과 동일 수준, HTMLParser 전환에 따른 성능 저하 없음.
- **검증 기준 전부 통과.**
