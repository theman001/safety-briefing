"""`.env` 파일에서 KEY=VALUE를 읽어 os.environ에 채우는 최소 로더. 표준 라이브러리만 사용.

이미 설정된 환경변수는 덮어쓰지 않음 (실제 export가 .env보다 우선).
"""
from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
