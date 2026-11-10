"""공통 관심사 분리 데코레이터.

- :func:`handle_errors` — CLI 오류 계약: 예외 → `[오류]`/`[힌트]` + 비-0 종료 코드.
- :func:`logged`       — 표준 ``logging`` 기반 호출 기록(기본 무출력, 관측만).
- :func:`timed`        — ``time.perf_counter`` 경과 측정(기본 무출력, 관측만).

`logged`/`timed`는 함수 동작을 바꾸지 않는다: 반환값과 예외 전파를 그대로 두고
``functools.wraps``로 이름·독스트링 등 메타데이터를 보존한다. 서로 독립적이며
쌓아 쓸 수 있다(위쪽 데코레이터가 먼저 실행된다). `handle_errors`는 CLI 전용 오류
계약이라 그대로 통과시키려는 예외(`SystemExit` 등)는 건드리지 않는다.
"""

import functools
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar, overload

from ._models import ModelError
from ._store import StoreError

P = ParamSpec("P")
T = TypeVar("T")

LOGGER = logging.getLogger("budget_app")
_ENV_LOG = "BUDGET_APP_LOG"
_ENV_LEVELS = {
    "1": logging.INFO,
    "true": logging.INFO,
    "yes": logging.INFO,
    "on": logging.INFO,
}


def _enable_logging_from_env() -> None:
    """`BUDGET_APP_LOG`가 설정돼 있으면 `budget_app` 로거를 stderr 출력으로 준비.

    미설정·빈 값·해석 불가 → 아무 것도 안 함(기본 무출력). 로그 레벨 이름
    (DEBUG/INFO/...) 또는 1/true/yes/on(→INFO)을 받아들인다. 핸들러가 이미 있으면
    추가하지 않고 레벨만 조정한다(사용자가 구성한 로깅을 존중).
    """
    raw = os.environ.get(_ENV_LOG, "").strip()
    if not raw:
        return
    level = _ENV_LEVELS.get(raw.lower())
    if level is None:
        level = getattr(logging, raw.upper(), None)
        if not isinstance(level, int):
            return
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(level)


@overload
def logged(
    func: Callable[P, T], *,
    logger: logging.Logger = ...,
    level: int = ...,
) -> Callable[P, T]: ...


@overload
def logged(
    *, logger: logging.Logger = ..., level: int = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def logged(
    func: Callable[P, T] | None = None,
    *,
    logger: logging.Logger = LOGGER,
    level: int = logging.DEBUG,
) -> Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]:
    """함수 호출/반환/예외를 표준 ``logging``으로 남기는 데코레이터. 기본 무출력.

    관찰만 한다: 반환값·예외 전파는 그대로다. `BUDGET_APP_LOG=DEBUG`(또는 1/true/yes/on)
    로 켜면 stderr에 `DEBUG budget_app: <이름> 호출/반환` 등이 찍힌다.
    """

    def decorate(fn: Callable[P, T]) -> Callable[P, T]:
        name = fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            _enable_logging_from_env()
            logger.log(level, "%s 호출", name)
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                logger.log(level, "%s 예외: %s", name, exc)
                raise
            logger.log(level, "%s 반환", name)
            return result

        return wrapper

    return decorate(func) if func is not None else decorate


@overload
def timed(
    func: Callable[P, T], *,
    logger: logging.Logger = ...,
    level: int = ...,
    clock: Callable[[], float] = ...,
) -> Callable[P, T]: ...


@overload
def timed(
    *, logger: logging.Logger = ..., level: int = ..., clock: Callable[[], float] = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def timed(
    func: Callable[P, T] | None = None,
    *,
    logger: logging.Logger = LOGGER,
    level: int = logging.DEBUG,
    clock: Callable[[], float] = time.perf_counter,
) -> Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]:
    """함수 경과 시간을 재서 표준 ``logging``(기본 DEBUG)으로 남기는 데코레이터.

    측정은 `finally`에서 하므로 실패해도 원 함수의 예외·반환값이 그대로다.
    `BUDGET_APP_LOG`로 수집하며, 테스트 등에서 `clock`을 주입해 측정값을 고정할 수 있다.
    """

    def decorate(fn: Callable[P, T]) -> Callable[P, T]:
        name = fn.__qualname__

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            _enable_logging_from_env()
            start = clock()
            try:
                return fn(*args, **kwargs)
            finally:
                logger.log(level, "%s: %.3f초", name, clock() - start)

        return wrapper

    return decorate(func) if func is not None else decorate


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
