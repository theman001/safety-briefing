#!/usr/bin/env python3
"""sif_archive.py 요청 URL 구성 self-check. 네트워크 호출 없음."""
from sif_archive import API_URL, _build_url


def test_build_url_contains_required_params():
    url = _build_url("KEY", "끼임", "1", 1, 10)
    assert url.startswith(API_URL + "?")
    assert "callApiId=1170" in url
    assert "cateSeCd=1" in url
    assert "pageNo=1" in url
    assert "numOfRows=10" in url
    assert "serviceKey=KEY" in url


if __name__ == "__main__":
    test_build_url_contains_required_params()
    print("OK")
