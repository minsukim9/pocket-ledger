"""필수 기능, 입력 검증, CSV 안전성의 회귀 테스트."""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from budget_app._models import Transaction
from budget_app._store import CategoryStore, TransactionStore, ensure_storage
from budget_app.cli import main


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        ensure_storage(self.data)
        self.transactions = TransactionStore(self.data / "transactions.csv")

    def cli(self, *args: str, input_text: str = "") -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(input_text)), redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([*args, "--data-dir", str(self.data)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_summary_empty_month_still_shows_budget(self) -> None:
        self.assertEqual(self.cli("budget", "set", "--month", "2024-02", "--amount", "500")[0], 0)
        code, out, err = self.cli("summary", "--month", "2024-02")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("총 수입: 0원", out)
        self.assertIn("총 지출: 0원", out)
        self.assertIn("잔액: 0원", out)
        self.assertIn("예산: 500원 (사용률 0.0%)", out)
        self.assertIn("2024-02 데이터 없음", out)

    def test_input_retry_error_hints_and_nonzero_exit(self) -> None:
        code, out, err = self.cli(
            "add",
            input_text="2024-13-01\n2024-01-15\nwrong\nexpense\nunknown\nfood\n0\n15000\n점심\nmeal\n",
        )
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.count("[오류]"), 4)
        self.assertIn("id=TX-000001", out)
        code, _, err = self.cli("delete", "--id", "TX-999999")
        self.assertEqual(code, 1)
        self.assertIn("[오류]", err)
        self.assertIn("[힌트]", err)
        self.assertNotIn("Traceback", err)
        code, _, err = self.cli("list", "--limit", "0")
        self.assertEqual(code, 1)
        self.assertIn("[힌트]", err)
        code, _, err = self.cli("add", input_text="")
        self.assertEqual(code, 1)
        self.assertIn("[힌트]", err)

    def test_missing_update_id_and_interactive_update(self) -> None:
        code, _, err = self.cli("update", "--id", "TX-999999")
        self.assertEqual(code, 1)
        self.assertIn("[힌트]", err)
        self.transactions.add(Transaction("TX-000001", "expense", "2024-01-15", 100, "food"))
        code, out, _ = self.cli("update", "--id", "TX-000001", input_text="\n\n\n0\n200\n새 메모\nmeal\n")
        self.assertEqual(code, 0)
        self.assertIn("금액은 1 이상", out)
        tx = next(self.transactions.iter_transactions())
        self.assertEqual((tx.amount, tx.memo, tx.tags), (200, "새 메모", ("meal",)))

    def test_cli_parser_errors_have_hint_and_exit_two(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                main(["search", "--unknown"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("[오류]", stderr.getvalue())
        self.assertIn("[힌트]", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_every_command_has_help(self) -> None:
        for command in (
            ("add",), ("list",), ("search",), ("summary",),
            ("budget",), ("budget", "set"), ("budget", "list"),
            ("category",), ("category", "add"), ("category", "list"),
            ("category", "remove"), ("update",), ("delete",),
            ("import",), ("export",), ("backup",), ("recur",),
            ("recur", "add"), ("recur", "list"), ("recur", "run"),
            ("recur", "remove"),
        ):
            with self.subTest(command=command):
                out = io.StringIO()
                with redirect_stdout(out), self.assertRaises(SystemExit) as result:
                    main([*command, "--help"])
                self.assertEqual(result.exception.code, 0)
                self.assertIn("usage:", out.getvalue())

    def test_empty_categories_file_is_reseeded(self) -> None:
        path = self.data / "categories.csv"
        path.write_text("", encoding="utf-8")
        code, out, _ = self.cli("category", "list")
        self.assertEqual(code, 0)
        self.assertIn("- food", out)
        self.assertEqual(len(CategoryStore(path).names()), 4)

    def test_internal_csv_corruption_does_not_overwrite_transactions(self) -> None:
        path = self.transactions.path
        for content in (
            "id,type,date,amount,category,memo,tags\nTX-000001,expense,2024-01-01,1,food,,,extra\n",
            "id,type,date,amount,category,memo,tags\nTX-000001,expense,2024-01-01,1,food\n",
            "id,id,type,date,amount,category,memo\nTX-000001,TX-000001,expense,2024-01-01,1,food,\n",
            'id,type,date,amount,category,memo,tags\n"TX-000001,expense,2024-01-01,1,food,,\n',
        ):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                before = path.read_bytes()
                code, _, err = self.cli("delete", "--id", "TX-000001")
                self.assertEqual(code, 1)
                self.assertIn("[오류]", err)
                self.assertIn("[힌트]", err)
                self.assertEqual(path.read_bytes(), before)

    def test_export_cannot_replace_a_storage_file(self) -> None:
        self.transactions.add(Transaction("TX-000001", "expense", "2024-01-01", 100, "food"))
        for name in ("transactions.csv", "categories.csv", "budgets.csv", "recurrences.csv"):
            with self.subTest(name=name):
                path = self.data / name
                before = path.read_bytes()
                code, _, err = self.cli("export", "--out", str(path), "--month", "2024-01")
                self.assertEqual(code, 1)
                self.assertIn("[힌트]", err)
                self.assertEqual(path.read_bytes(), before)

    def test_import_skips_bad_row_and_exports_expected_header(self) -> None:
        source = self.data / "incoming.csv"
        source.write_text(
            "date,type,category,amount,memo,tags\n"
            "2024-01-15,expense,food,15000,점심,meal\n"
            "2024-01-16,expense,food,100,,oops,extra\n"
            "2024-01-17,expense,unknown,100,,\n"
            "2024-01-18,income,salary,3000000,월급,\n",
            encoding="utf-8",
        )
        code, out, _ = self.cli("import", "--from", str(source))
        self.assertEqual(code, 0)
        self.assertIn("imported=2, skipped=2", out)
        ids = [tx.id for tx in self.transactions.iter_transactions()]
        self.assertEqual(ids, ["TX-000002", "TX-000001"])
        output = self.data / "export.csv"
        self.assertEqual(self.cli("export", "--out", str(output), "--month", "2024-01")[0], 0)
        with output.open(encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle)
            self.assertEqual(rows.fieldnames, ["date", "type", "category", "amount", "memo", "tags"])
            self.assertEqual(len(list(rows)), 2)


if __name__ == "__main__":
    unittest.main()
