"""보너스 기능과 기존 스트리밍/저장 계약의 회귀 테스트 (표준 라이브러리)."""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from budget_app._models import Transaction
from budget_app._store import (
    CategoryStore,
    RecurrenceStore,
    TransactionStore,
    backup_files,
    ensure_storage,
)
from budget_app.cli import main


class BonusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        ensure_storage(self.data)
        self.transactions = TransactionStore(self.data / "transactions.csv")
        self.categories = CategoryStore(self.data / "categories.csv")
        self.recurrences = RecurrenceStore(self.data / "recurrences.csv")

    def cli(self, *args: str, input_text: str = "") -> tuple[int, str]:
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(input_text)), redirect_stdout(output), redirect_stderr(output):
            code = main([*args, "--data-dir", str(self.data)])
        return code, output.getvalue()

    def test_backup_preserves_data_and_keeps_distinct_snapshots(self) -> None:
        self.transactions.add(Transaction("TX-000001", "expense", "2024-01-01", 100, "food"))
        before = {p.name: p.read_bytes() for p in self.data.glob("*.csv")}
        first, count = backup_files(self.data, "20240101-120000")
        second, count2 = backup_files(self.data, "20240101-120000")
        self.assertEqual((count, count2), (4, 4))
        self.assertEqual(first.name, "backup-20240101-120000")
        self.assertEqual(second.name, "backup-20240101-120000-1")
        for name, content in before.items():
            self.assertEqual((first / name).read_bytes(), content)
            self.assertEqual((second / name).read_bytes(), content)
            self.assertEqual((self.data / name).read_bytes(), content)
        code, output = self.cli("backup")
        self.assertEqual(code, 0)
        self.assertRegex(output, r"backup-\d{8}-\d{6}.*\(4 files\)")

    def test_failed_backup_leaves_no_partial_snapshot(self) -> None:
        with patch("budget_app._store.shutil.copy2", side_effect=OSError("디스크 오류")):
            with self.assertRaisesRegex(Exception, "백업 실패"):
                backup_files(self.data, "20240101-120000")
        self.assertFalse(list((self.data / "backups").iterdir()))
        self.assertEqual(len(list(self.data.glob("*.csv"))), 4)

    def test_recurring_preview_apply_idempotent_and_invalid_day(self) -> None:
        code, output = self.cli("recur", "add", input_text="expense\nrent\n500000\n31\n월세\n")
        self.assertEqual(code, 0)
        self.assertIn("R-000001", output)
        code, output = self.cli("recur", "run", "--month", "2024-02")
        self.assertEqual(code, 0)
        self.assertIn("일자없음 1", output)
        self.assertEqual(list(self.transactions.iter_transactions()), [])
        code, output = self.cli("recur", "run", "--month", "2024-01")
        self.assertEqual(code, 0)
        self.assertIn("생성 예정 1건", output)
        self.assertEqual(list(self.transactions.iter_transactions()), [])
        code, output = self.cli("recur", "run", "--month", "2024-01", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("[생성 완료] 1건", output)
        self.assertEqual([t.id for t in self.transactions.iter_transactions()], ["TX-000001"])
        code, output = self.cli("recur", "run", "--month", "2024-01", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("생성 예정 0건", output)
        self.assertIn("중복 1", output)
        self.assertEqual([t.id for t in self.transactions.iter_transactions()], ["TX-000001"])
        code, output = self.cli("category", "remove", input_text="rent\n")
        self.assertEqual(code, 1)
        self.assertTrue(self.categories.names())

    def test_recurring_rule_blocks_category_removal_without_transaction(self) -> None:
        self.recurrences.add(type="expense", category="food", amount=10, day=1)
        code, output = self.cli("category", "remove", input_text="food\n")
        self.assertEqual(code, 1)
        self.assertIn("반복 규칙에서 사용 중", output)
        self.assertIn("food", self.categories.names())
        self.cli("recur", "remove", "--id", "R-000001")
        self.assertEqual(self.cli("category", "remove", input_text="food\n")[0], 0)

    def test_list_alignment_search_streaming_and_export_schema(self) -> None:
        for tx in (
            Transaction("TX-000001", "expense", "2024-01-01", 15, "food", tags=("a", "b")),
            Transaction("TX-000002", "income", "2024-01-02", 10000, "salary"),
        ):
            self.transactions.add(tx)
        code, listing = self.cli("list", "--limit", "2")
        self.assertEqual(code, 0)
        cells = [line.split(" | ") for line in listing.strip().splitlines()]
        self.assertEqual(len(cells), 2)
        self.assertEqual([row[0] for row in cells], ["TX-000002", "TX-000001"])
        self.assertEqual(len({len(row[4]) for row in cells}), 1)
        code, searched = self.cli("search", "--category", "food")
        self.assertEqual(code, 0)
        self.assertIn("TX-000001", searched)
        self.assertNotIn("TX-000002", searched)
        output_file = self.data / "export.csv"
        code, _ = self.cli("export", "--month", "2024-01", "--out", str(output_file))
        self.assertEqual(code, 0)
        with output_file.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, ["date", "type", "category", "amount", "memo", "tags"])
            self.assertEqual(len(list(reader)), 2)


if __name__ == "__main__":
    unittest.main()
