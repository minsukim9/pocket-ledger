from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from typing import ParamSpec

from ._models import ModelError
from ._store import StoreError

P = ParamSpec("P")


def error_lines(exc: BaseException) -> tuple[str, ...]:
    """예외 → 콘솔 출력 줄(들). 스택트레이스 대신 원인(+힌트)만."""
    if isinstance(exc, (ModelError, StoreError)):
        lines = [f"[오류] {exc}"]
        hint = getattr(exc, "hint", None)
        if hint is None:
            hint = (
                "입력값과 해당 명령의 --help를 확인하세요"
                if isinstance(exc, ModelError)
                else "저장 파일 및 --data-dir 경로와 접근 권한을 확인하세요"
            )
        lines.append(f"[힌트] {hint}")
        return tuple(lines)
    if isinstance(exc, EOFError):
        return (
            "[오류] 입력이 종료되었습니다",
            "[힌트] 값이 필요합니다. 다시 실행해 입력하세요",
        )
    return (
        f"[오류] 예상치 못한 오류: {exc}",
        "[힌트] 입력값·파일 경로·CSV 형식을 확인하고 다시 시도하세요",
    )


def handle_errors(func: Callable[P, int]) -> Callable[P, int]:
    """예외 → '[오류] 원인 / [힌트] ...' + 비-0 종료 코드. 스택트레이스 미출력."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> int:
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            print("[오류] 사용자 중단 (Ctrl+C)", file=sys.stderr)
            print("[힌트] 다시 실행해 입력하세요", file=sys.stderr)
            return 130
        except (ModelError, StoreError, EOFError) as exc:
            for line in error_lines(exc):
                print(line, file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 — 미션: 스택트레이스 금지
            for line in error_lines(exc):
                print(line, file=sys.stderr)
            return 1

    return wrapper
