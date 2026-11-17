"""주소 -> 기상청 격자(nx, ny) 변환.

1. 카카오 로컬 API로 주소 -> 위경도(WGS84) 조회 (표준 라이브러리만 사용, urllib).
2. 기상청이 공개한 Lambert Conformal Conic 변환식으로 위경도 -> nx/ny (순수 수학, 외부 API 불필요).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv_loader import load_dotenv

KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

# 기상청 공개 격자 변환 상수 (LCC 투영, 단위: km)
RE = 6371.00877
GRID = 5.0
SLAT1 = 30.0
SLAT2 = 60.0
OLON = 126.0
OLAT = 38.0
XO = 43
YO = 136


def geocode_address(address: str, api_key: str, retries: int = 3, timeout: int = 10) -> dict:
    query = urllib.parse.urlencode({"query": address})
    url = f"{KAKAO_ADDRESS_URL}?{query}"
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {api_key}"})

    data = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"카카오 지오코딩 API 호출 실패 (HTTP {e.code}): {body}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"카카오 지오코딩 API 연결 실패: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"카카오 지오코딩 API 응답 파싱 실패: {e}")

    documents = data.get("documents", [])
    if not documents:
        raise RuntimeError(f"주소를 찾을 수 없음(검색결과 0건): {address!r} — 더 구체적인 주소로 다시 시도하세요.")

    best = documents[0]
    return {
        "lat": float(best["y"]),
        "lon": float(best["x"]),
        "matched_address": best.get("address_name"),
        "match_count": len(documents),
    }


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    degrad = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * degrad
    slat2 = SLAT2 * degrad
    olon = OLON * degrad
    olat = OLAT * degrad

    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * degrad * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * degrad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    x = ra * math.sin(theta) + XO
    y = ro - ra * math.cos(theta) + YO

    return int(x + 0.5), int(y + 0.5)


def main() -> int:
    load_dotenv()
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        print("ERROR: KAKAO_REST_API_KEY가 .env에 없습니다.", file=sys.stderr)
        return 2

    address = input("주소: ").strip()
    if not address:
        print("ERROR: 주소가 비어 있습니다.", file=sys.stderr)
        return 2

    try:
        geo = geocode_address(address, api_key)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    nx, ny = latlon_to_grid(geo["lat"], geo["lon"])

    note = ""
    if geo["match_count"] > 1:
        note = f" (검색결과 {geo['match_count']}건 중 1번째 — 다른 매칭도 있으니 주소를 더 구체화하면 안전함)"
    print(f"매칭된 주소: {geo['matched_address']}{note}", file=sys.stderr)
    print(f"위도/경도: {geo['lat']}, {geo['lon']}", file=sys.stderr)

    print(f"nx : {nx}")
    print(f"ny : {ny}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
