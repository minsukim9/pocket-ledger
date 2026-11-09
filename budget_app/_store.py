from __future__ import annotations

import csv
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ._config import default_data_dir, resolve_data_dir
from ._models import (
    Budget,
    Category,
    ModelError,
    Recurrence,
    Transaction,
    format_tags,
    parse_tags,
    transaction_from_row,
    validate_amount,
    validate_category,
    validate_date,
    validate_day,
    validate_month,
    validate_type,
)

TRANSACTIONS_FILE = "transactions.csv"
CATEGORIES_FILE = "categories.csv"
BUDGETS_FILE = "budgets.csv"
RECURRENCES_FILE = "recurrences.csv"

TXN_FIELDS = ("id", "type", "date", "amount", "category", "memo", "tags")
CATEGORY_FIELDS = ("name",)
BUDGET_FIELDS = ("month", "amount")
RECURRENCE_FIELDS = ("id", "type", "category", "amount", "day", "memo")

# 카테고리 파일이 없거나 비어 있으면 시드(미션 안 A).
DEFAULT_CATEGORIES = ("food", "transport", "rent", "salary")


class StoreError(RuntimeError):
    """파일 I/O 오류. 원인(message)과 선택적 확인 방법(hint)을 담는다."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


def ensure_data_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"{path} 폴더를 만들 수 없습니다: {exc}") from exc
    return path


def _atomic_write(path: Path, header: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    """임시 파일에 쓰고 os.replace로 교체 — 찢어진 쓰기/부분 기록 방지."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    except OSError as exc:
        raise StoreError(f"{path} 쓰기 준비 실패: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(header), extrasaction="ignore", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise StoreError(f"{path} 쓰기 실패: {exc}") from exc
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _iter_rows(
    path: Path, expected_fields: Sequence[str]
) -> Iterator[tuple[int, dict[str, Any]]]:
    """CSV 헤더/행 형태를 검증하며 (줄번호, dict)를 스트리밍으로 읽는다."""
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fields = reader.fieldnames or []
            if len(fields) != len(expected_fields) or set(fields) != set(expected_fields):
                raise StoreError(
                    f"{path.name} 헤더가 올바르지 않습니다: {fields!r}",
                    hint=f"필요한 컬럼: {', '.join(expected_fields)}. 백업을 확인하세요",
                )
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise StoreError(
                        f"{path.name}:{reader.line_num}행의 컬럼 개수가 헤더와 다릅니다",
                        hint="CSV의 쉼표와 따옴표를 확인하거나 백업에서 복구하세요",
                    )
                yield reader.line_num, row
    except UnicodeDecodeError as exc:
        raise StoreError(f"{path.name}을(를) UTF-8로 읽을 수 없습니다: {exc}") from exc
    except csv.Error as exc:
        raise StoreError(f"{path.name} CSV 형식 오류: {exc}") from exc
    except OSError as exc:
        raise StoreError(f"{path.name} 읽기 실패: {exc}") from exc


def _tx_row(tx: Transaction) -> dict[str, Any]:
    return {
        "id": tx.id,
        "type": tx.type,
        "date": tx.date,
        "amount": str(tx.amount),
        "category": tx.category,
        "memo": tx.memo,
        "tags": format_tags(tx.tags),
    }


def _id_value(tx_id: str) -> int:
    digits = tx_id[len("TX-"):] if tx_id.startswith("TX-") else ""
    return int(digits) if digits.isdigit() else -1


def _sort_key(tx: Transaction) -> tuple[str, int]:
    # (date desc, id desc) — 파일 순서 = 최신순 불변식
    return (tx.date, _id_value(tx.id))


class TransactionStore:
    """transactions.csv 담당.

    읽기 = 제너레이터 스트리밍(전체 로드 없음).
    쓰기 = (date, id) 내림차순 불변식을 유지하며 임시 파일 + os.replace 재작성.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_data_dir() / TRANSACTIONS_FILE

    def exists(self) -> bool:
        return self.path.is_file()

    def ensure(self) -> None:
        if not self.path.is_file():
            _atomic_write(self.path, TXN_FIELDS, [])

    def iter_transactions(self) -> Iterator[Transaction]:
        for line_no, row in _iter_rows(self.path, TXN_FIELDS):
            try:
                yield transaction_from_row(row)
            except ModelError as exc:
                raise ModelError(f"{self.path.name}:{line_no}행: {exc}") from exc

    def read_all(self) -> list[Transaction]:
        """쓰기(재작성) 경로 전용 — 전체 로드. 조회는 iter_transactions 사용."""
        return list(self.iter_transactions())

    def next_id(self) -> str:
        highest = max((_id_value(tx.id) for tx in self.iter_transactions()), default=0)
        return f"TX-{highest + 1:06d}"

    def add(self, tx: Transaction) -> Transaction:
        self.insert_many([tx])
        return tx

    def insert_many(self, txs: Iterable[Transaction]) -> int:
        """일괄 추가(import 경로): id 중복 검사 후 1회 재작성 — 원자적."""
        new = list(txs)
        if not new:
            return 0
        current = self.read_all()
        ids = {t.id for t in current}
        for tx in new:
            if tx.id in ids:
                raise StoreError(f"{tx.id} id가 이미 존재합니다")
            ids.add(tx.id)
        self._rewrite(current + new)
        return len(new)

    def update(
        self,
        tx_id: str,
        *,
        type: str | None = None,
        date: str | None = None,
        amount: int | None = None,
        category: str | None = None,
        memo: str | None = None,
        tags: str | tuple[str, ...] | None = None,
    ) -> Transaction | None:
        """변경 필드만 갱신해 반환. 없는 id면 None (호출자가 '없는 데이터' 안내)."""
        txs = self.read_all()
        found = False
        out: list[Transaction] = []
        for tx in txs:
            if tx.id != tx_id:
                out.append(tx)
                continue
            found = True
            new_tags = tx.tags
            if tags is not None:
                new_tags = parse_tags(tags) if isinstance(tags, str) else tuple(tags)
            out.append(
                Transaction(
                    id=tx.id,
                    type=validate_type(type) if type is not None else tx.type,
                    date=validate_date(date) if date is not None else tx.date,
                    amount=validate_amount(amount) if amount is not None else tx.amount,
                    category=validate_category(category) if category is not None else tx.category,
                    memo=memo if memo is not None else tx.memo,
                    tags=new_tags,
                )
            )
        if not found:
            return None
        self._rewrite(out)
        return next(t for t in out if t.id == tx_id)

    def delete(self, tx_id: str) -> bool:
        txs = self.read_all()
        remaining = [t for t in txs if t.id != tx_id]
        if len(remaining) == len(txs):
            return False
        self._rewrite(remaining)
        return True

    def _rewrite(self, txs: list[Transaction]) -> None:
        txs.sort(key=_sort_key, reverse=True)
        _atomic_write(self.path, TXN_FIELDS, (_tx_row(t) for t in txs))


class RecurrenceStore:
    """recurrences.csv 담당 — 반복 내역 규칙(등록 순서 유지)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path) if path is not None else default_data_dir() / RECURRENCES_FILE
        )

    def exists(self) -> bool:
        return self.path.is_file()

    def ensure(self) -> None:
        if not self.path.is_file():
            _atomic_write(self.path, RECURRENCE_FIELDS, [])

    def iter_recurrences(self) -> Iterator[Recurrence]:
        for line_no, row in _iter_rows(self.path, RECURRENCE_FIELDS):
            try:
                rec_id = row.get("id") or ""
                if not re.fullmatch(r"R-\d+", rec_id):
                    raise ModelError(f"반복 규칙 id 형식 오류: {rec_id!r} (예: R-000001)")
                yield Recurrence(
                    id=rec_id,
                    type=validate_type(row.get("type")),
                    category=validate_category(row.get("category")),
                    amount=validate_amount(row.get("amount")),
                    day=validate_day(row.get("day")),
                    memo=row.get("memo") or "",
                )
            except ModelError as exc:
                raise ModelError(f"{self.path.name}:{line_no}행: {exc}") from exc

    def add(
        self,
        *,
        type: str,
        category: str,
        amount: int,
        day: int,
        memo: str = "",
    ) -> Recurrence:
        rec = Recurrence(
            id=f"R-{self._next_number():06d}",
            type=validate_type(type),
            category=validate_category(category),
            amount=validate_amount(amount),
            day=validate_day(day),
            memo=memo,
        )
        existing = {r.id for r in self.iter_recurrences()}
        if rec.id in existing:
            raise StoreError(f"{rec.id} id가 이미 존재합니다")
        recs = list(self.iter_recurrences())
        recs.append(rec)
        _atomic_write(
            self.path, RECURRENCE_FIELDS,
            [
                {
                    "id": r.id, "type": r.type, "category": r.category,
                    "amount": str(r.amount), "day": str(r.day), "memo": r.memo,
                }
                for r in recs
            ],
        )
        return rec

    def _next_number(self) -> int:
        highest = max(
            (int(r.id[2:]) for r in self.iter_recurrences() if r.id.startswith("R-") and r.id[2:].isdigit()),
            default=0,
        )
        return highest + 1

    def remove(self, rec_id: str) -> bool:
        recs = list(self.iter_recurrences())
        remaining = [r for r in recs if r.id != rec_id]
        if len(remaining) == len(recs):
            return False
        _atomic_write(
            self.path, RECURRENCE_FIELDS,
            [
                {
                    "id": r.id, "type": r.type, "category": r.category,
                    "amount": str(r.amount), "day": str(r.day), "memo": r.memo,
                }
                for r in remaining
            ],
        )
        return True


class CategoryStore:
    """categories.csv 담당."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_data_dir() / CATEGORIES_FILE

    def iter_categories(self) -> Iterator[Category]:
        for line_no, row in _iter_rows(self.path, CATEGORY_FIELDS):
            try:
                yield Category(validate_category(row.get("name")))
            except ModelError as exc:
                raise ModelError(f"{self.path.name}:{line_no}행: {exc}") from exc

    def names(self) -> list[str]:
        return [c.name for c in self.iter_categories()]

    def ensure_seeded(self) -> bool:
        """파일 없음/데이터 없음 → 기본 카테고리 생성(옵션 A). 시드 여부 반환."""
        if not self.path.is_file() or self.path.stat().st_size == 0:
            _atomic_write(self.path, CATEGORY_FIELDS, [{"name": n} for n in DEFAULT_CATEGORIES])
            return True
        if self.names():
            return False
        _atomic_write(self.path, CATEGORY_FIELDS, [{"name": n} for n in DEFAULT_CATEGORIES])
        return True

    def add(self, name: str) -> bool:
        name = validate_category(name)
        names = self.names()
        if name in names:
            return False
        names.append(name)
        names.sort(key=str.casefold)
        _atomic_write(self.path, CATEGORY_FIELDS, [{"name": n} for n in names])
        return True

    def remove(self, name: str) -> bool:
        name = validate_category(name)
        names = self.names()
        if name not in names:
            return False
        _atomic_write(
            self.path, CATEGORY_FIELDS, [{"name": n} for n in names if n != name]
        )
        return True


class BudgetStore:
    """budgets.csv 담당."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_data_dir() / BUDGETS_FILE

    def exists(self) -> bool:
        return self.path.is_file()

    def ensure(self) -> None:
        if not self.path.is_file():
            _atomic_write(self.path, BUDGET_FIELDS, [])

    def iter_budgets(self) -> Iterator[Budget]:
        for line_no, row in _iter_rows(self.path, BUDGET_FIELDS):
            try:
                budget = Budget(
                    month=validate_month(row.get("month")),
                    amount=validate_amount(row.get("amount")),
                )
            except ModelError as exc:
                raise ModelError(f"{self.path.name}:{line_no}행: {exc}") from exc
            yield budget

    def get(self, month: str) -> Budget | None:
        month = validate_month(month)
        for budget in self.iter_budgets():
            if budget.month == month:
                return budget
        return None

    def set(self, month: str, amount: int) -> Budget:
        month = validate_month(month)
        amount = validate_amount(amount)
        budgets = list(self.iter_budgets())
        rest = [b for b in budgets if b.month != month]
        rest.append(Budget(month=month, amount=amount))
        rest.sort(key=lambda b: b.month)
        _atomic_write(self.path, BUDGET_FIELDS, [{"month": b.month, "amount": str(b.amount)} for b in rest])
        return Budget(month=month, amount=amount)


def ensure_storage(data_dir: str | Path | None = None) -> Path:
    """저장 폴더 보장 + 파일 준비(없으면 헤더만/기본 카테고리). 부팅 시 1회 호출용."""
    base = ensure_data_dir(resolve_data_dir(data_dir))
    TransactionStore(base / TRANSACTIONS_FILE).ensure()
    BudgetStore(base / BUDGETS_FILE).ensure()
    CategoryStore(base / CATEGORIES_FILE).ensure_seeded()
    RecurrenceStore(base / RECURRENCES_FILE).ensure()
    return base


def backup_files(data_dir: str | Path, stamp: str | None = None) -> tuple[Path, int]:
    """현재 저장 파일을 `backups/backup-<타임스탬프>/`로 복사해 스냅샷 생성. (폴더, 복사 파일 수)

    stamp 미지정 시 현재 시각 YYYYmmdd-HHMMSS. 같은 이름 폴더가 있으면 `-1`, `-2` … 접미사.
    원본은 그대로 두고 복사만 하며, 존재하는 저장 파일만 대상으로 한다.
    """
    base = ensure_data_dir(resolve_data_dir(data_dir))
    if stamp is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = base / "backups"
    folder = backup_dir / f"backup-{stamp}"
    counter = 1
    while folder.exists():
        folder = base / "backups" / f"backup-{stamp}-{counter}"
        counter += 1
    sources = [
        base / name
        for name in (TRANSACTIONS_FILE, CATEGORIES_FILE, BUDGETS_FILE, RECURRENCES_FILE)
    ]
    sources = [src for src in sources if src.is_file()]
    if not sources:
        raise StoreError(
            "백업할 저장 파일이 없습니다",
            hint="거래·카테고리 등을 먼저 저장한 뒤 다시 시도하세요",
        )
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".backup-", dir=backup_dir))
    except OSError as exc:
        raise StoreError(f"{folder} 백업 준비 실패: {exc}") from exc
    try:
        for src in sources:
            shutil.copy2(src, staging / src.name)
        os.replace(staging, folder)
    except OSError as exc:
        raise StoreError(f"{folder} 백업 실패: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return folder, len(sources)
