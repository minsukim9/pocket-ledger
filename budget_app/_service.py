from __future__ import annotations

import calendar
import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ._models import (
    Budget,
    ModelError,
    Recurrence,
    Transaction,
    format_tags,
    parse_tags,
    validate_amount,
    validate_date,
    validate_month,
    validate_type,
)
from ._store import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    RECURRENCES_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    RecurrenceStore,
    StoreError,
    TransactionStore,
    _atomic_write,
)

EXPORT_FIELDS = ("date", "type", "category", "amount", "memo", "tags")


@dataclass(frozen=True, slots=True)
class MonthSummary:
    month: str
    count: int  # 해당 월 거래 수
    total_income: int
    total_expense: int
    balance: int
    by_category: tuple[tuple[str, int], ...]  # 지출 내림차순, 동률이면 이름 오름차순
    budget: Budget | None


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    percent: float  # 소수 1자리 반올림
    over: bool
    excess: int


def match_category(name: str, names: Iterable[str]) -> str | None:
    """이름을 등록 목록과 대조해 표준 표기 반환(없으면 None). 대소문자 무시."""
    needle = name.strip()
    if not needle:
        return None
    for candidate in names:
        if candidate == needle:
            return candidate
    fold = needle.casefold()
    for candidate in names:
        if candidate.casefold() == fold:
            return candidate
    return None


def resolve_category(name: str, store: CategoryStore) -> str:
    """대화형 입력 공용 검증: 등록 목록 대조, 없으면 원인+힌트."""
    canonical = match_category(name, store.names())
    if canonical is None:
        raise ModelError(
            f"등록되지 않은 카테고리입니다: {name.strip()!r}",
            hint="'category add'로 등록하거나 'category list'로 목록을 확인하세요",
        )
    return canonical


def used_category_counts(store: TransactionStore) -> dict[str, int]:
    """카테고리별 사용 내역 수 — 삭제 가드용."""
    counts: dict[str, int] = {}
    for tx in store.iter_transactions():
        counts[tx.category] = counts.get(tx.category, 0) + 1
    return counts


def _normalize_filters(
    *, from_date: str | None, to_date: str | None, category: str | None,
    type: str | None, q: str | None, tag: str | None,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    if from_date is not None:
        from_date = validate_date(from_date)
    if to_date is not None:
        to_date = validate_date(to_date)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ModelError(
            f"기간 시작({from_date})이 끝({to_date})보다 늦습니다",
            hint="--from 은 --to 보다 앞선 날짜여야 합니다",
        )
    if type is not None:
        type = validate_type(type)
    category = category.strip().casefold() if category is not None else None
    if category == "":
        category = None
    q = q.strip().lower() if q is not None else None
    if q == "":
        q = None
    tag = tag.strip() if tag is not None else None
    if tag == "":
        tag = None
    return from_date, to_date, category, type, q, tag


def search_transactions(
    store: TransactionStore,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    category: str | None = None,
    type: str | None = None,
    q: str | None = None,
    tag: str | None = None,
) -> Iterator[Transaction]:
    """조건 필터 제너레이터 — 파일 순서(최신순) 그대로 스트리밍, 전체 로드 없음."""
    from_date, to_date, category, type, q, tag = _normalize_filters(
        from_date=from_date, to_date=to_date, category=category, type=type, q=q, tag=tag
    )
    for tx in store.iter_transactions():
        if from_date is not None and tx.date < from_date:
            continue
        if to_date is not None and tx.date > to_date:
            continue
        if category is not None and tx.category.casefold() != category:
            continue
        if type is not None and tx.type != type:
            continue
        if q is not None and q not in tx.memo.casefold():
            continue
        if tag is not None and tag not in tx.tags:
            continue
        yield tx


def month_summary(
    tx_store: TransactionStore,
    budget_store: BudgetStore,
    month: str,
    top: int = 5,
) -> MonthSummary:
    month = validate_month(month)
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ModelError(f"TOP 개수는 1 이상 정수여야 합니다: {top!r}")
    income = 0
    expense = 0
    count = 0
    by_category: dict[str, int] = {}
    for tx in tx_store.iter_transactions():
        if tx.date[:7] != month:
            continue
        count += 1
        if tx.type == "income":
            income += tx.amount
        else:
            expense += tx.amount
            by_category[tx.category] = by_category.get(tx.category, 0) + tx.amount
    ranked = tuple(
        sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:top]
    )
    return MonthSummary(
        month=month,
        count=count,
        total_income=income,
        total_expense=expense,
        balance=income - expense,
        by_category=ranked,
        budget=budget_store.get(month),
    )


def budget_status(budget: Budget, spent: int) -> BudgetStatus:
    percent = round(spent / budget.amount * 100, 1)
    return BudgetStatus(percent=percent, over=spent > budget.amount, excess=max(0, spent - budget.amount))


def export_transactions(
    store: TransactionStore,
    out_path: str | Path,
    *,
    month: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> int:
    """조건에 맞는 거래를 CSV로. 내보내기 조건 1개 이상 필수. 건수 반환(스트리밍 기록)."""
    month = validate_month(month) if month is not None else None
    from_date, to_date, _, _, _, _ = _normalize_filters(
        from_date=from_date, to_date=to_date, category=None, type=None, q=None, tag=None
    )
    if month is None and from_date is None and to_date is None:
        raise ModelError(
            "내보내기 조건이 필요합니다",
            hint="--month 또는 --from/--to 중 하나 이상을 지정하세요",
        )
    target = Path(out_path).expanduser()
    protected = {
        (store.path.parent / name).resolve()
        for name in (TRANSACTIONS_FILE, CATEGORIES_FILE, BUDGETS_FILE, RECURRENCES_FILE)
    }
    if target.resolve() in protected:
        raise ModelError(
            f"저장 파일에 내보낼 수 없습니다: {target}",
            hint="--out에 ./data 외부의 별도 CSV 경로를 지정하세요",
        )
    written = 0

    def _rows() -> Iterator[dict[str, str]]:
        nonlocal written
        for tx in store.iter_transactions():
            if month is not None and tx.date[:7] != month:
                continue
            if from_date is not None and tx.date < from_date:
                continue
            if to_date is not None and tx.date > to_date:
                continue
            written += 1
            yield {
                "type": tx.type,
                "date": tx.date,
                "amount": str(tx.amount),
                "category": tx.category,
                "memo": tx.memo,
                "tags": format_tags(tx.tags),
            }

    _atomic_write(target, EXPORT_FIELDS, _rows())
    return written


def import_transactions(
    store: TransactionStore,
    cat_store: CategoryStore,
    src_path: str | Path,
) -> tuple[int, int]:
    """CSV → 거래 일괄 등록. (등록 건수, 건너뛴 건수).

    스킵 기준: 행 형식 오류, 미등록 카테고리. 필수 컬럼 누락은 파일 단위 오류.
    id는 내장 시퀀스(최대값+1)로 부여.
    """
    required = ("date", "type", "category", "amount")
    path = Path(src_path).expanduser()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fieldnames = reader.fieldnames or []
            if len(fieldnames) != len(set(fieldnames)):
                raise StoreError(
                    f"CSV 헤더에 중복된 컬럼이 있습니다: {fieldnames!r}",
                    hint="컬럼명 중복을 제거하고 다시 가져오세요",
                )
            missing = [c for c in required if c not in fieldnames]
            if missing:
                raise StoreError(
                    f"CSV 스키마가 맞지 않습니다: 필수 컬럼 누락 — {', '.join(missing)}",
                    hint="필수: date, type, category, amount / 선택: memo, tags (UTF-8, 헤더 포함)",
                )
            names = set(cat_store.names())
            known = {n.casefold(): n for n in names}
            txs: list[Transaction] = []
            skipped = 0
            prev_id = store.next_id()
            for row in reader:
                if None in row:
                    skipped += 1
                    continue
                try:
                    raw_category = (row.get("category") or "").strip()
                    category = known.get(raw_category.casefold())
                    if category is None:
                        skipped += 1
                        continue
                    txs.append(
                        Transaction(
                            id=prev_id,
                            type=validate_type(row.get("type")),
                            date=validate_date(row.get("date")),
                            amount=validate_amount(row.get("amount")),
                            category=category,
                            memo=row.get("memo") or "",
                            tags=parse_tags(row.get("tags")),
                        )
                    )
                    prev_id = _bump(prev_id)
                except ModelError:
                    skipped += 1
            imported = store.insert_many(txs) if txs else 0
    except StoreError:
        raise
    except UnicodeDecodeError as exc:
        raise StoreError(
            f"{path} 을(를) UTF-8로 읽을 수 없습니다: {exc}",
            hint="엑셀 저장 시 'CSV UTF-8(쉼표로 분리)'로 내보내세요",
        ) from exc
    except csv.Error as exc:
        raise StoreError(f"{path} CSV 형식 오류: {exc}") from exc
    except OSError as exc:
        raise StoreError(f"{path} 읽기 실패: {exc}") from exc
    return imported, skipped


def _bump(tx_id: str) -> str:
    return f"TX-{int(tx_id[3:]) + 1:06d}"


@dataclass(frozen=True, slots=True)
class Expansion:
    """`recur run` 결과: 생성/건너뜀 집계 + 미리보기용 (규칙, 날짜) 목록."""

    generated: tuple[tuple[Recurrence, str], ...]
    created: int
    skipped_missing_day: int
    skipped_duplicate: int
    skipped_unregistered: int


def expand_recurrences(
    rec_store: RecurrenceStore,
    tx_store: TransactionStore,
    cat_store: CategoryStore,
    month: str,
    *,
    apply: bool = False,
) -> Expansion:
    """특정 월에 반복 내역을 전개. apply=False(기본)=미리보기, 파일 변경 없음.

    건너뜀: 그 달에 일자 없음(예: 2/31), 같은 (type,category,amount,day) 이미 존재,
    카테고리 미등록. apply=True면 생성분을 1회 재작성으로 저장.
    """
    month = validate_month(month)
    last_day = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
    seen: set[tuple[str, str, int, int]] = set()
    for tx in tx_store.iter_transactions():
        if tx.date[:7] != month:
            continue
        seen.add((tx.type, tx.category, tx.amount, int(tx.date[8:10])))
    registered = {name.casefold() for name in cat_store.names()}
    generated: list[tuple[Recurrence, str]] = []
    skipped_missing_day = skipped_duplicate = skipped_unregistered = 0
    for rec in rec_store.iter_recurrences():
        if rec.day > last_day:
            skipped_missing_day += 1
            continue
        if rec.category.casefold() not in registered:
            skipped_unregistered += 1
            continue
        if (rec.type, rec.category, rec.amount, rec.day) in seen:
            skipped_duplicate += 1
            continue
        generated.append((rec, f"{month}-{rec.day:02d}"))
        seen.add((rec.type, rec.category, rec.amount, rec.day))
    created = 0
    if apply and generated:
        base_id = int(tx_store.next_id()[3:])
        txs = [
            Transaction(
                id=f"TX-{base_id + i:06d}",
                type=rec.type,
                date=date,
                amount=rec.amount,
                category=rec.category,
                memo=rec.memo,
            )
            for i, (rec, date) in enumerate(generated)
        ]
        created = tx_store.insert_many(txs)
    return Expansion(
        generated=tuple(generated),
        created=created,
        skipped_missing_day=skipped_missing_day,
        skipped_duplicate=skipped_duplicate,
        skipped_unregistered=skipped_unregistered,
    )
