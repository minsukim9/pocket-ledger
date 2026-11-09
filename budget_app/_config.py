from __future__ import annotations

from pathlib import Path

DEFAULT_DATA_DIR = "data"


def default_data_dir() -> Path:
    """기본 저장 폴더 (현재 작업 디렉터리 기준 상대경로)."""
    return Path(DEFAULT_DATA_DIR)


def resolve_data_dir(raw: str | Path | None) -> Path:
    """--data-dir 옵션값 해석: None/빈 값이면 기본값, '~' 확장."""
    if raw is None or str(raw).strip() == "":
        return default_data_dir()
    return Path(raw).expanduser()
