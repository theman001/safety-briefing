#!/usr/bin/env python3
"""서울 날씨 수집: 단기예보 수치 + 공식 기상특보. Task 8a.

Python 3.9+, 표준 라이브러리만 사용.

사용법 (프로젝트 루트에서):
    python3 test/weather_fetch.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv_loader import load_dotenv

KST = timezone(timedelta(hours=9))

VILAGE_FCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
WTHR_WRN_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"

# 공식 활용가이드(기상청21_기상특보 조회서비스_오픈API활용가이드.docx, "# 첨부. 지점코드")로 확인된
# 고정값 — 바뀌지 않는 공식 코드라 .env로 빼지 않고 상수로 둔다.
WARN_STN_ID = "109"
WARN_REGION = "서울, 인천, 경기도"

ANNOUNCE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]

SKY_LABEL = {"1": "맑음", "3": "구름많음", "4": "흐림"}
PTY_LABEL = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기", "5": "빗방울", "6": "빗방울눈날림", "7": "눈날림"}

TITLE_RE = re.compile(r"/\s*(?P<body>.+?)\s*(?:\(\*\))?\s*$")
ACTION_WORDS = ("발표", "해제", "변경")


def _http_get_json(url: str, retries: int = 3, timeout: int = 25) -> dict:
    for attempt in range(retries):
        try:
            with urlopen(url, timeout=timeout) as res:
                body = res.read(8_000_000)
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status}")
                return json.loads(body.decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise RuntimeError(f"HTTP {exc.code}: {detail[:300]}") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"통신 오류: {type(exc).__name__}") from None
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"응답이 JSON이 아님: {exc}") from None
    raise RuntimeError("재시도 초과")


def _header_code(resp: dict) -> str:
    return resp.get("response", {}).get("header", {}).get("resultCode", "")


def _items(resp: dict) -> list[dict]:
    item = resp.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    if isinstance(item, dict):
        return [item]
    return item or []


def _num(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def base_time_candidates(now: datetime) -> list[tuple[str, str]]:
    """발표 후 20분 이상 지난 회차를 최신순으로 반환 (오늘+전날 8회씩 중에서)."""
    points = []
    for days_back in (0, 1):
        day = now - timedelta(days=days_back)
        for h in ANNOUNCE_HOURS:
            points.append(day.replace(hour=h, minute=0, second=0, microsecond=0))
    points.sort(reverse=True)
    valid = [p for p in points if p + timedelta(minutes=20) <= now]
    return [(p.strftime("%Y%m%d"), p.strftime("%H%M")) for p in valid]


def vilage_fcst_url(service_key: str, nx: str, ny: str, base_date: str, base_time: str) -> str:
    params = {
        "serviceKey": service_key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny,
    }
    return VILAGE_FCST_URL + "?" + urlencode(params)


def summarize_vilage(items: list[dict], today: str) -> tuple[dict, int]:
    today_items = [it for it in items if it.get("fcstDate") == today]

    def values(cat: str) -> list:
        out = []
        for it in today_items:
            if it.get("category") == cat:
                v = _num(it.get("fcstValue"))
                if v is not None:
                    out.append(v)
        return out

    sky_codes = sorted({it["fcstValue"] for it in today_items if it.get("category") == "SKY"})
    pty_codes = sorted({it["fcstValue"] for it in today_items if it.get("category") == "PTY"})

    temp = values("TMP")
    reh = values("REH")
    pop = values("POP")
    wsd = values("WSD")

    summary = {
        "temp_min": min(temp) if temp else None,
        "temp_max": max(temp) if temp else None,
        "humidity_max": max(reh) if reh else None,
        "precip_prob_max": max(pop) if pop else None,
        "wind_speed_max": max(wsd) if wsd else None,
        "sky": [SKY_LABEL.get(c, f"코드{c}") for c in sky_codes],
        "precip_type": [PTY_LABEL.get(c, f"코드{c}") for c in pty_codes],
    }
    return summary, len(today_items)


def wthr_wrn_url(service_key: str, stn_id: str, from_tm: str, to_tm: str) -> str:
    params = {
        "serviceKey": service_key, "pageNo": 1, "numOfRows": 100, "dataType": "JSON",
        "stnId": stn_id, "fromTmFc": from_tm, "toTmFc": to_tm,
    }
    return WTHR_WRN_URL + "?" + urlencode(params)


def _split_name_action_pairs(body: str) -> tuple[list[tuple[str, str]], list[str]]:
    """'강풍주의보·풍랑주의보 발표' -> [(강풍주의보,발표),(풍랑주의보,발표)].

    세그먼트가 자기 동작을 안 갖고 있으면(예: '강풍주의보') 뒤에 나오는, 동작이 붙은
    세그먼트의 동작을 같이 쓴다 — 반환값 2번째는 끝까지 동작을 못 찾은 잔여 세그먼트(비정상 형식).
    """
    pending: list[str] = []
    pairs: list[tuple[str, str]] = []
    for seg in (s.strip() for s in body.split("·")):
        if not seg:
            continue
        action = next((a for a in ACTION_WORDS if seg.endswith(a)), None)
        if action is None:
            pending.append(seg)
            continue
        name = seg[: -len(action)].strip()
        for n in pending + [name]:
            if n:
                pairs.append((n, action))
        pending = []
    return pairs, pending


def parse_warnings(items: list[dict]) -> tuple[list[str], list[str]]:
    """반환: (현재 발효 중인 특보명 목록, 파싱 불가/모호한 title 원문 목록).

    같은 title 안에서 같은 특보명이 서로 다른 동작으로 두 번 나오면(예: 해역별로 한쪽은
    해제·다른 쪽은 변경) 이 API 응답엔 구역 구분이 없어 어느 쪽이 우리 지역 얘기인지
    알 수 없다 — 추측하지 않고 통째로 unparsed로 남긴다.
    """
    items_sorted = sorted(items, key=lambda it: int(it.get("tmFc", 0) or 0), reverse=True)
    latest_action: dict[str, str] = {}
    unparsed = []
    for it in items_sorted:
        title = it.get("title", "")
        m = TITLE_RE.search(title)
        if not m:
            unparsed.append(title)
            continue
        pairs, leftover = _split_name_action_pairs(m.group("body"))
        names_seen = [n for n, _ in pairs]
        if leftover or len(set(names_seen)) != len(names_seen):
            unparsed.append(title)
            continue
        for name, action in pairs:
            if name not in latest_action:
                latest_action[name] = action
    active = sorted(name for name, action in latest_action.items() if action in ("발표", "변경"))
    return active, unparsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="서울 날씨(단기예보 수치 + 공식 특보) 수집")
    parser.add_argument("--out", default=None, help="저장 경로 (기본: output/weather_<날짜>.json)")
    args = parser.parse_args(argv)

    load_dotenv()
    service_key = os.environ.get("DATA_GO_KR_SERVICE_KEY")
    if not service_key:
        print("환경변수 DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.", file=sys.stderr)
        return 2
    nx = os.environ.get("WEATHER_NX", "60")
    ny = os.environ.get("WEATHER_NY", "127")

    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")

    candidates = base_time_candidates(now)
    if not candidates:
        print("발표회차를 계산할 수 없습니다.", file=sys.stderr)
        return 1

    summary = None
    used_base = None
    last_error = None
    for base_date, base_time in candidates[:2]:
        try:
            resp = _http_get_json(vilage_fcst_url(service_key, nx, ny, base_date, base_time))
        except RuntimeError as exc:
            last_error = exc
            continue
        code = _header_code(resp)
        if code != "00":
            last_error = RuntimeError(f"단기예보 resultCode={code}")
            continue
        s, n = summarize_vilage(_items(resp), today)
        if n == 0:
            last_error = RuntimeError("오늘 날짜 데이터 없음")
            continue
        summary, used_base = s, (base_date, base_time)
        break

    if summary is None:
        print(f"단기예보 수집 실패: {last_error}", file=sys.stderr)
        return 1

    warn_active: list[str] = []
    warn_unparsed: list[str] = []
    warn_error = None
    try:
        from_tm = (now - timedelta(days=6)).strftime("%Y%m%d")  # API 제약: 오늘 기준 6일 전까지만 조회 가능
        wresp = _http_get_json(wthr_wrn_url(service_key, WARN_STN_ID, from_tm, today))
        wcode = _header_code(wresp)
        if wcode == "00":
            warn_active, warn_unparsed = parse_warnings(_items(wresp))
        elif wcode != "03":  # 03=NODATA_ERROR는 "활성 특보 없음"의 정상 응답
            warn_error = f"resultCode={wcode}"
    except RuntimeError as exc:
        warn_error = str(exc)

    result = {
        "date": today,
        "location": {"nx": _num(nx), "ny": _num(ny), "name": "서울"},
        "base_date": used_base[0],
        "base_time": used_base[1],
        "summary": summary,
        "official_warnings": {
            "stn_id": WARN_STN_ID,
            "region": WARN_REGION,
            "active": warn_active,
            "unparsed": warn_unparsed,
            "error": warn_error,
        },
    }

    out_path = args.out or f"output/weather_{today}.json"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(
        f"수집 완료: {used_base[1]}회차, 기온 {summary['temp_min']}~{summary['temp_max']}도, "
        f"활성 특보 {len(warn_active)}건 -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
