from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import TypeVar

from ._config import resolve_data_dir
from ._decorators import handle_errors, logged, timed
from ._format import format_transaction_stream, format_transactions
from ._models import (
    ModelError,
    Transaction,
    format_tags,
    parse_tags,
    validate_amount,
    validate_category,
    validate_date,
    validate_day,
    validate_type,
)
from ._service import (
    budget_status,
    expand_recurrences,
    export_transactions,
    import_transactions,
    match_category,
    month_summary,
    resolve_category,
    search_transactions,
    used_category_counts,
)
from ._store import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    RECURRENCES_FILE,
    TRANSACTIONS_FILE,
    BudgetStore,
    CategoryStore,
    RecurrenceStore,
    TransactionStore,
    backup_files,
    ensure_storage,
)

class _Keep:
    """대화형 수정에서 입력을 유지한다는 표식."""


_KEEP = _Keep()
T = TypeVar("T")


class _ArgumentParser(argparse.ArgumentParser):
    """옵션 오류에도 다른 명령과 동일한 원인/해결 힌트를 제공한다."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(
            2,
            f"[오류] {message}\n[힌트] 사용법은 'python -m budget_app --help' "
            "또는 해당 명령의 --help로 확인하세요\n",
        )


def _print_error(exc: ModelError) -> None:
    print(f"[오류] {exc}")
    if exc.hint:
        print(f"[힌트] {exc.hint}")


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise ModelError(
            "입력이 종료되었습니다",
            hint="값이 필요합니다. 다시 실행해 입력하세요",
        )


def _ask_validated(prompt: str, validator: Callable[[str], T]) -> T:
    while True:
        raw = _ask(prompt)
        try:
            return validator(raw)
        except ModelError as exc:
            _print_error(exc)


def _show(value: str | int | tuple[str, ...]) -> str:
    return "없음" if value == "" or value == () else str(value)


def _open_stores(
    data_dir: str | None,
) -> tuple[TransactionStore, CategoryStore, BudgetStore, RecurrenceStore]:
    base = ensure_storage(resolve_data_dir(data_dir))
    return (
        TransactionStore(base / TRANSACTIONS_FILE),
        CategoryStore(base / CATEGORIES_FILE),
        BudgetStore(base / BUDGETS_FILE),
        RecurrenceStore(base / RECURRENCES_FILE),
    )


# --- add -----------------------------------------------------------------

def _cmd_add(args: argparse.Namespace) -> int:
    tx_store, cat_store, _, _ = _open_stores(args.data_dir)
    date = _ask_validated("날짜(YYYY-MM-DD): ", validate_date)
    type_ = _ask_validated("타입(income/expense): ", validate_type)
    category = _ask_validated("카테고리: ", lambda raw: resolve_category(raw, cat_store))
    amount = _ask_validated("금액(양수): ", validate_amount)
    memo = _ask("메모(선택): ")
    tags = parse_tags(_ask("태그(쉼표로 구분, 없으면 엔터): "))
    tx = Transaction(
        id=tx_store.next_id(),
        type=type_,
        date=date,
        amount=amount,
        category=category,
        memo=memo,
        tags=tags,
    )
    tx_store.add(tx)
    print(f"[저장 완료] id={tx.id}")
    return 0


# --- list / search -------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> int:
    tx_store, _, _, _ = _open_stores(args.data_dir)
    if args.limit < 1:
        raise ModelError(f"--limit 은 1 이상이어야 합니다: {args.limit}")
    txs = []
    for tx in tx_store.iter_transactions():
        if len(txs) >= args.limit:
            break
        txs.append(tx)
    lines = format_transactions(txs)
    if not lines:
        print("저장된 거래가 없습니다")
        return 0
    for line in lines:
        print(line)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    tx_store, _, _, _ = _open_stores(args.data_dir)
    txs = search_transactions(
        tx_store,
        from_date=args.from_date,
        to_date=args.to_date,
        category=args.category,
        type=args.type,
        q=args.q,
        tag=args.tag,
    )
    shown = 0
    for tx in txs:
        print(format_transaction_stream(tx))
        shown += 1
    if not shown:
        print("조건에 맞는 거래가 없습니다")
    return 0


# --- summary -------------------------------------------------------------

def _cmd_summary(args: argparse.Namespace) -> int:
    tx_store, _, budget_store, _ = _open_stores(args.data_dir)
    summary = month_summary(tx_store, budget_store, args.month, top=args.top)
    print(f"총 수입: {summary.total_income}원")
    print(f"총 지출: {summary.total_expense}원")
    print(f"잔액: {summary.balance}원")
    if summary.budget is not None:
        status = budget_status(summary.budget, summary.total_expense)
        line = f"예산: {summary.budget.amount}원 (사용률 {status.percent:.1f}%)"
        if status.over:
            line += f" [경고] 예산 초과 — {status.excess}원"
        print(line)
    if summary.count == 0:
        print(f"{summary.month} 데이터 없음")
        return 0
    if summary.by_category:
        label = "지출 TOP " + str(len(summary.by_category))
        print(label)
        for i, (name, amount) in enumerate(summary.by_category, start=1):
            print(f"{i}) {name} {amount}원")
    else:
        print("지출 없음")
    return 0


# --- budget --------------------------------------------------------------

def _cmd_budget_set(args: argparse.Namespace) -> int:
    _, _, budget_store, _ = _open_stores(args.data_dir)
    budget = budget_store.set(args.month, args.amount)
    print(f"[저장 완료] {budget.month} 예산 {budget.amount}원")
    return 0


def _cmd_budget_list(args: argparse.Namespace) -> int:
    _, _, budget_store, _ = _open_stores(args.data_dir)
    budgets = sorted(budget_store.iter_budgets(), key=lambda b: b.month)
    if not budgets:
        print("설정된 예산이 없습니다")
        return 0
    for budget in budgets:
        print(f"{budget.month}: {budget.amount}원")
    return 0


# --- category ------------------------------------------------------------

def _add_category(store: CategoryStore, raw: str) -> str:
    name = validate_category(raw)
    if match_category(name, store.names()) is not None:
        raise ModelError(f"이미 등록된 카테고리입니다: {name}")
    if not store.add(name):
        raise ModelError(f"이미 등록된 카테고리입니다: {name}")
    return name


def _cmd_category_add(args: argparse.Namespace) -> int:
    _, cat_store, _, _ = _open_stores(args.data_dir)
    name = _ask_validated("카테고리명: ", lambda raw: _add_category(cat_store, raw))
    print(f"[저장 완료] category={name}")
    return 0


def _cmd_category_list(args: argparse.Namespace) -> int:
    _, cat_store, _, _ = _open_stores(args.data_dir)
    names = cat_store.names()
    if not names:
        print("등록된 카테고리가 없습니다")
        return 0
    for name in names:
        print(f"- {name}")
    return 0


def _cmd_category_remove(args: argparse.Namespace) -> int:
    tx_store, cat_store, _, rec_store = _open_stores(args.data_dir)
    name = _ask_validated("삭제할 카테고리명: ", validate_category)
    canonical = match_category(name, cat_store.names())
    if canonical is None:
        raise ModelError(f"등록되지 않은 카테고리입니다: {name}")
    used = used_category_counts(tx_store)
    if canonical in used:
        raise ModelError(
            f"사용 중 카테고리는 삭제할 수 없습니다: {canonical} ({used[canonical]}건)",
            hint="'update'로 해당 거래를 다른 카테고리로 옮긴 뒤 다시 시도하세요",
        )
    if any(rec.category.casefold() == canonical.casefold() for rec in rec_store.iter_recurrences()):
        raise ModelError(
            f"반복 규칙에서 사용 중인 카테고리입니다: {canonical}",
            hint="'recur list'로 규칙 id를 확인하고 'recur remove --id ID'로 삭제하세요",
        )
    cat_store.remove(canonical)
    print(f"[삭제 완료] category={canonical}")
    return 0


# --- update (대화형 고정) ------------------------------------------------

def _edit_field(
    label: str,
    current: str | int,
    transform: Callable[[str], str | int] | None,
    clearable: bool,
) -> str | int | tuple[str, ...] | _Keep:
    hint = ", -=비움" if clearable else ""
    while True:
        raw = _ask(f"{label}(현재 {_show(current)}{hint}, 엔터=유지): ")
        if raw == "":
            return _KEEP
        try:
            if raw == "-" and clearable:
                return "" if label == "메모" else ()
            if transform is not None:
                return transform(raw)
            return raw
        except ModelError as exc:
            _print_error(exc)


def _cmd_update(args: argparse.Namespace) -> int:
    tx_store, cat_store, _, _ = _open_stores(args.data_dir)
    current = next((t for t in tx_store.iter_transactions() if t.id == args.id), None)
    if current is None:
        raise ModelError(
            f"거래를 찾을 수 없습니다: {args.id}",
            hint="'list'로 최근 거래의 id를 확인하세요",
        )
    fields = [
        ("날짜", current.date, validate_date, False),
        ("타입", current.type, validate_type, False),
        ("카테고리", current.category, lambda raw: resolve_category(raw, cat_store), False),
        ("금액", current.amount, validate_amount, False),
        ("메모", current.memo, None, True),
        ("태그", format_tags(current.tags), None, True),
    ]
    changes: dict[str, str | int | tuple[str, ...]] = {}
    for label, value, transform, clearable in fields:
        edited = _edit_field(label, value, transform, clearable)
        if not isinstance(edited, _Keep):
            changes[label] = edited
    if not changes:
        print(f"변경된 항목이 없습니다: {args.id}")
        return 0
    updated = tx_store.update(
        args.id,
        date=changes.get("날짜"),
        type=changes.get("타입"),
        category=changes.get("카테고리"),
        amount=changes.get("금액"),
        memo=changes.get("메모"),
        tags=changes.get("태그"),
    )
    print(
        f"[수정 완료] {updated.id} | {updated.date} | {updated.type} | "
        f"{updated.category} | {updated.amount}"
    )
    return 0


# --- delete / export / import --------------------------------------------

def _cmd_delete(args: argparse.Namespace) -> int:
    tx_store, _, _, _ = _open_stores(args.data_dir)
    if not tx_store.delete(args.id):
        raise ModelError(
            f"삭제할 거래가 없습니다: {args.id}",
            hint="'list'로 id를 확인하세요",
        )
    print(f"[삭제 완료] {args.id}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    tx_store, _, _, _ = _open_stores(args.data_dir)
    count = export_transactions(
        tx_store,
        args.out,
        month=args.month,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    print(f"[완료] {args.out} ({count} records)")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    tx_store, cat_store, _, _ = _open_stores(args.data_dir)
    imported, skipped = import_transactions(tx_store, cat_store, args.src)
    print(f"[완료] imported={imported}, skipped={skipped}")
    if skipped:
        print("건너뜀 건은 형식 오류 또는 미등록 카테고리입니다 ('category list' 확인)")
    return 0


# --- backup ---------------------------------------------------------------

def _cmd_backup(args: argparse.Namespace) -> int:
    folder, count = backup_files(args.data_dir)
    print(f"[백업 완료] {folder} ({count} files)")
    return 0


# --- recur ----------------------------------------------------------------

def _cmd_recur_add(args: argparse.Namespace) -> int:
    _, cat_store, _, rec_store = _open_stores(args.data_dir)
    type_ = _ask_validated("타입(income/expense): ", validate_type)
    category = _ask_validated("카테고리: ", lambda raw: resolve_category(raw, cat_store))
    amount = _ask_validated("금액(양수): ", validate_amount)
    day = _ask_validated("일자(1~31): ", validate_day)
    memo = _ask("메모(선택): ")
    rec = rec_store.add(type=type_, category=category, amount=amount, day=day, memo=memo)
    print(f"[저장 완료] id={rec.id} (매월 {rec.day}일 {rec.type} {rec.category} {rec.amount})")
    return 0


def _cmd_recur_list(args: argparse.Namespace) -> int:
    _, _, _, rec_store = _open_stores(args.data_dir)
    recs = list(rec_store.iter_recurrences())
    if not recs:
        print("등록된 반복 내역이 없습니다")
        return 0
    for rec in recs:
        print(f"{rec.id} | {rec.type} | {rec.category} | {rec.amount} | {rec.day}일 | {rec.memo}")
    return 0


def _cmd_recur_run(args: argparse.Namespace) -> int:
    tx_store, cat_store, _, rec_store = _open_stores(args.data_dir)
    result = expand_recurrences(rec_store, tx_store, cat_store, args.month, apply=args.apply)
    print(f"{args.month}: 생성 예정 {len(result.generated)}건")
    for rec, date in result.generated:
        print(f"[생성 예정] {date} | {rec.type} | {rec.category} | {rec.amount} | {rec.memo}".rstrip())
    skipped = result.skipped_missing_day + result.skipped_duplicate + result.skipped_unregistered
    if skipped:
        print(
            f"건너뜀 — 일자없음 {result.skipped_missing_day}, "
            f"중복 {result.skipped_duplicate}, 미등록 카테고리 {result.skipped_unregistered}"
        )
    if args.apply and result.created:
        print(f"[생성 완료] {result.created}건")
    return 0


def _cmd_recur_remove(args: argparse.Namespace) -> int:
    _, _, _, rec_store = _open_stores(args.data_dir)
    if not rec_store.remove(args.id):
        raise ModelError(
            f"반복 내역이 없습니다: {args.id}",
            hint="'recur list'로 목록을 확인하세요",
        )
    print(f"[삭제 완료] {args.id}")
    return 0


# --- parser -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = _ArgumentParser(add_help=False)
    common.add_argument(
        "--data-dir", metavar="DIR", default=None, help="저장 폴더 (기본: ./data)"
    )
    parser = _ArgumentParser(
        prog="budget_app",
        description="파일 기반 개인 가계부 (예: python -m budget_app list --limit 3)",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<명령>")

    p = sub.add_parser("add", parents=[common], help="대화형으로 거래 추가")
    p.set_defaults(func=_cmd_add)

    p = sub.add_parser("list", parents=[common], help="최신순 거래 목록 (스트리밍)")
    p.add_argument("--limit", type=int, default=20, metavar="N", help="표시 개수 (기본 20)")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("search", parents=[common], help="조건 검색 (최신순, 스트리밍)")
    p.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", help="시작일 (포함)")
    p.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="종료일 (포함)")
    p.add_argument("--category", metavar="이름")
    p.add_argument("--type", metavar="income|expense")
    p.add_argument("--q", metavar="키워드", help="메모 부분검색 (대소문자 무시)")
    p.add_argument("--tag", metavar="태그")
    p.set_defaults(func=_cmd_search)

    p = sub.add_parser("summary", parents=[common], help="월별 요약 + 카테고리 지출 TOP N")
    p.add_argument("--month", required=True, metavar="YYYY-MM", help="대상 월")
    p.add_argument("--top", type=int, default=5, metavar="N", help="지출 TOP 개수 (기본 5)")
    p.set_defaults(func=_cmd_summary)

    p = sub.add_parser("budget", parents=[common], help="월 예산 설정/조회")
    b_sub = p.add_subparsers(dest="budget_command", required=True, metavar="<set|list>")
    b_set = b_sub.add_parser("set", parents=[common], help="예산 설정")
    b_set.add_argument("--month", required=True, metavar="YYYY-MM")
    b_set.add_argument("--amount", required=True, metavar="금액")
    b_set.set_defaults(func=_cmd_budget_set)
    b_list = b_sub.add_parser("list", parents=[common], help="예산 목록")
    b_list.set_defaults(func=_cmd_budget_list)

    p = sub.add_parser("category", parents=[common], help="카테고리 관리 (대화형)")
    c_sub = p.add_subparsers(dest="category_command", required=True, metavar="<add|list|remove>")
    c_add = c_sub.add_parser("add", parents=[common], help="카테고리 추가")
    c_add.set_defaults(func=_cmd_category_add)
    c_list = c_sub.add_parser("list", parents=[common], help="카테고리 목록")
    c_list.set_defaults(func=_cmd_category_list)
    c_remove = c_sub.add_parser("remove", parents=[common], help="카테고리 삭제 (사용 중이면 거부)")
    c_remove.set_defaults(func=_cmd_category_remove)

    p = sub.add_parser("backup", parents=[common], help="현재 저장 파일을 타임스탬프 폴더로 복사")
    p.set_defaults(func=_cmd_backup)

    p = sub.add_parser("recur", parents=[common], help="반복 내역 관리 (월 단위 규칙)")
    r_sub = p.add_subparsers(
        dest="recur_command", required=True, metavar="<add|list|run|remove>"
    )
    r_add = r_sub.add_parser("add", parents=[common], help="반복 규칙 추가 (대화형)")
    r_add.set_defaults(func=_cmd_recur_add)
    r_list = r_sub.add_parser("list", parents=[common], help="반복 규칙 목록")
    r_list.set_defaults(func=_cmd_recur_list)
    r_run = r_sub.add_parser("run", parents=[common], help="특정 월 전개 (기본 미리보기)")
    r_run.add_argument("--month", required=True, metavar="YYYY-MM")
    r_run.add_argument("--apply", action="store_true", help="실제로 거래 생성")
    r_run.set_defaults(func=_cmd_recur_run)
    r_remove = r_sub.add_parser("remove", parents=[common], help="규칙 삭제")
    r_remove.add_argument("--id", required=True, metavar="ID")
    r_remove.set_defaults(func=_cmd_recur_remove)

    p = sub.add_parser("update", parents=[common], help="대화형으로 필드 수정 (--id 필요)")
    p.add_argument("--id", required=True, metavar="ID", help="수정할 거래 id")
    p.set_defaults(func=_cmd_update)

    p = sub.add_parser("delete", parents=[common], help="거래 삭제")
    p.add_argument("--id", required=True, metavar="ID")
    p.set_defaults(func=_cmd_delete)

    p = sub.add_parser("export", parents=[common], help="조건에 맞는 거래를 CSV로 내보내기")
    p.add_argument("--out", required=True, metavar="CSV", help="출력 파일")
    p.add_argument("--month", metavar="YYYY-MM")
    p.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("import", parents=[common], help="CSV에서 거래 일괄 등록")
    p.add_argument("--from", dest="src", required=True, metavar="CSV", help="가져올 CSV 파일")
    p.set_defaults(func=_cmd_import)

    return parser


# 로깅·시간 측정은 관측만 한다(기본 무출력). 오류 계약(handle_errors)을 가장 바깥에 둬
# 어떤 내부 예외도 기존 [오류]/[힌트] + 종료 코드 계약으로 수렴시킨다.
@handle_errors
@timed
@logged
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
