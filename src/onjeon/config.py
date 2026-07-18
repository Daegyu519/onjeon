"""환경 설정 로더 — .env 파일의 API 키를 프로세스 환경변수로 올린다.

키 우선순위: 이미 설정된 환경변수 > .env 파일 (override 금지).
Streamlit Cloud에서는 st.secrets → 환경변수 브리지를 app.py가 수행한다.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: str | Path | None = None) -> bool:
    """.env를 로드한다. 파일이 없으면 False (크래시 금지 — 키 없이도 데모 가능)."""
    env_path = Path(path) if path else _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return False
    return load_dotenv(env_path, override=False)
