"""geo_to_grid.latlon_to_grid 순수 수학 변환 self-check (네트워크 불필요).

원점(기준점) 역산 검증 중 라운딩 상수 버그(+1.5 -> +0.5)를 실제로 잡아낸 테스트.
LCC 변환의 수학적 역함수를 여기서만 재구현해 순방향 결과를 되돌려 검증한다
(기상청이 공개한 변환식의 역변환이며, geo_to_grid.py 자체에는 역변환이 필요 없어 노출하지 않음).
"""
import math

from geo_to_grid import GRID, OLAT, OLON, RE, SLAT1, SLAT2, XO, YO, latlon_to_grid


def _grid_to_latlon(nx: float, ny: float) -> tuple[float, float]:
    degrad = math.pi / 180.0
    raddeg = 180.0 / math.pi
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

    xn = nx - XO
    yn = ro - ny + YO
    ra = math.sqrt(xn * xn + yn * yn)
    if sn < 0.0:
        ra = -ra
    alat = (re * sf / ra) ** (1.0 / sn)
    alat = 2.0 * math.atan(alat) - math.pi * 0.5
    if abs(xn) <= 0.0:
        theta = 0.0
    elif abs(yn) <= 0.0:
        theta = math.pi * 0.5
        if xn < 0.0:
            theta = -theta
    else:
        theta = math.atan2(xn, yn)
    alon = theta / sn + olon
    return alat * raddeg, alon * raddeg


def test_origin_point_maps_back_to_reference_cell():
    # 기준점(OLAT, OLON)은 정의상 (XO, YO)로 떨어져야 함
    nx, ny = latlon_to_grid(OLAT, OLON)
    assert (nx, ny) == (XO, YO), f"기준점 역산 결과가 (XO,YO)={(XO, YO)}와 다름: ({nx},{ny})"


def test_round_trip_consistency_across_grid():
    for nx, ny in [(60, 127), (61, 128), (90, 70), (43, 136), (30, 50)]:
        lat, lon = _grid_to_latlon(nx, ny)
        back = latlon_to_grid(lat, lon)
        assert back == (nx, ny), f"({nx},{ny}) 역변환 후 재변환 불일치: {back}"


def test_seoul_cityhall_matches_known_grid():
    nx, ny = latlon_to_grid(37.5665, 126.9780)
    assert (nx, ny) == (60, 127), (
        f"서울시청 좌표 변환 결과가 weather_fetch.py 실데이터 검증 기본값(60,127)과 다름: nx={nx}, ny={ny}"
    )


def main():
    test_origin_point_maps_back_to_reference_cell()
    test_round_trip_consistency_across_grid()
    test_seoul_cityhall_matches_known_grid()
    print("OK")


if __name__ == "__main__":
    main()
