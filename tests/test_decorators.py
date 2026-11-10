"""데코레이터 회귀 테스트: 로깅(`logged`)·시간 측정(`timed`)·오류 계약(`handle_errors`).

- `logged`/`timed`은 표준 `logging`을 쓰므로 기본 설정은 무출력이고, `assertLogs`로 검증한다.
- `timed`은 주입한 clock으로 측정값을 고정한다.
- `handle_errors`는 기존 CLI 오류 계약(비-0 종료 코드·`[오류]`/`[힌트]`·스택트레이스 없음)을 유지한다.
- `BUDGET_APP_LOG` 경로는 로거 상태(핸들러·레벨·propagate)를 저장/복원해 다른 테스트를 오염시키지 않는다.
"""

import io
import logging
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from budget_app import _decorators as dec
from budget_app._models import ModelError


class TimedTests(unittest.TestCase):
    def test_timed_preserves_result_and_uses_injected_clock(self) -> None:
        ticks = iter([10.0, 10.5])

        @dec.timed(clock=lambda: next(ticks))
        def work() -> int:
            return 42

        with self.assertLogs(dec.LOGGER, level="DEBUG") as captured:
            self.assertEqual(work(), 42)
        text = "\n".join(r.getMessage() for r in captured.records)
        self.assertIn("work: 0.500초", text)

    def test_timed_logs_duration_even_when_function_raises(self) -> None:
        ticks = iter([0.0, 0.25])

        @dec.timed(clock=lambda: next(ticks))
        def boom() -> None:
            raise ValueError("bad")

        with self.assertLogs(dec.LOGGER, level="DEBUG") as captured:
            with self.assertRaises(ValueError):
                boom()
        self.assertIn("0.250초", "\n".join(r.getMessage() for r in captured.records))

    def test_timed_accepts_a_function_directly(self) -> None:
        def work() -> str:
            return "ok"

        self.assertEqual(dec.timed(work)(), "ok")


class LoggedTests(unittest.TestCase):
    def test_logged_records_call_and_return(self) -> None:
        @dec.logged
        def add(a: int, b: int) -> int:
            return a + b

        with self.assertLogs(dec.LOGGER, level="DEBUG") as captured:
            self.assertEqual(add(1, 2), 3)
        text = "\n".join(r.getMessage() for r in captured.records)
        self.assertIn("add 호출", text)
        self.assertIn("add 반환", text)

    def test_logged_records_exception_and_reraises(self) -> None:
        @dec.logged
        def boom() -> None:
            raise KeyError("missing")

        with self.assertLogs(dec.LOGGER, level="DEBUG") as captured:
            with self.assertRaises(KeyError):
                boom()
        self.assertIn("예외", "\n".join(r.getMessage() for r in captured.records))

    def test_logged_accepts_a_function_directly(self) -> None:
        def work() -> str:
            return "ok"

        self.assertEqual(dec.logged(work)(), "ok")


class HandleErrorsTests(unittest.TestCase):
    def test_success_value_passes_through(self) -> None:
        @dec.handle_errors
        def ok() -> int:
            return 0

        self.assertEqual(ok(), 0)

    def test_model_error_prints_hint_and_returns_one(self) -> None:
        @dec.handle_errors
        def bad() -> int:
            raise ModelError("등록되지 않은 카테고리입니다: 'x'", hint="'category add'로 등록하세요")

        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(bad(), 1)
        self.assertIn("[오류] 등록되지 않은 카테고리입니다: 'x'", err.getvalue())
        self.assertIn("[힌트] 'category add'로 등록하세요", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_keyboard_interrupt_returns_130_and_unexpected_returns_one(self) -> None:
        @dec.handle_errors
        def interrupted() -> int:
            raise KeyboardInterrupt

        @dec.handle_errors
        def unexpected() -> int:
            raise RuntimeError("x")

        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(interrupted(), 130)
            self.assertEqual(unexpected(), 1)
        self.assertIn("[오류] 사용자 중단", err.getvalue())
        self.assertIn("[오류] 예상치 못한 오류", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_wraps_preserves_metadata(self) -> None:
        @dec.handle_errors
        def documented() -> int:
            """docstring stays."""

            return 0

        self.assertEqual(documented.__name__, "documented")
        self.assertEqual(documented.__doc__, "docstring stays.")


class EnvLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._handlers = list(dec.LOGGER.handlers)
        self._level = dec.LOGGER.level
        self._propagate = dec.LOGGER.propagate
        dec.LOGGER.handlers[:] = []
        dec.LOGGER.setLevel(logging.NOTSET)
        dec.LOGGER.propagate = True

    def tearDown(self) -> None:
        dec.LOGGER.handlers[:] = self._handlers
        dec.LOGGER.setLevel(self._level)
        dec.LOGGER.propagate = self._propagate

    def test_env_var_enables_stderr_logging(self) -> None:
        @dec.logged
        def work() -> int:
            return 1

        err = io.StringIO()
        with patch.dict(os.environ, {"BUDGET_APP_LOG": "DEBUG"}), redirect_stderr(err):
            self.assertEqual(work(), 1)
        self.assertIn("work 호출", err.getvalue())

    def test_invalid_or_empty_env_value_is_ignored(self) -> None:
        @dec.logged
        def work() -> int:
            return 1

        for value in ("not-a-level", "  "):
            with self.subTest(value=value):
                err = io.StringIO()
                with patch.dict(os.environ, {"BUDGET_APP_LOG": value}), redirect_stderr(err):
                    self.assertEqual(work(), 1)
                self.assertEqual(err.getvalue(), "")
                self.assertEqual(dec.LOGGER.handlers, [])


if __name__ == "__main__":
    unittest.main()
