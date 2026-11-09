from __future__ import annotations

from collections.abc import Iterable

from ._models import Transaction

# 열 순서: id, date, type, category, amount, memo, tags
_AMOUNT_COLUMN = 4  # 금액은 오른쪽 정렬


def _widths(columns: list[list[str]]) -> list[int]:
    return [max(len(cell) for cell in column) for column in columns]


def format_transactions(txs: Iterable[Transaction]) -> list[str]:
    """표시용 테이블(정렬된 열). 열 폭은 표시 대상 기준 자동 계산, 금액만 오른쪽 정렬.

    파일 읽기는 호출자의 스트리밍 제너레이터 그대로이고, 폭 계산을 위해 '표시 대상'만 목록화한다.
    마지막 tags 열은 패딩하지 않고(빈 값이면 다른 행에 데이터가 있을 때만 빈 칸), 전부 비면 열 자체를 생략한다.
    """
    rows = list(txs)
    if not rows:
        return []
    columns = [
        [tx.id for tx in rows],
        [tx.date for tx in rows],
        [tx.type for tx in rows],
        [tx.category for tx in rows],
        [str(tx.amount) for tx in rows],
        [tx.memo for tx in rows],
        [",".join(tx.tags) for tx in rows],
    ]
    widths = _widths(columns[:6])
    has_tags = any(columns[6])
    lines: list[str] = []
    for index in range(len(rows)):
        cells = [
            f"{columns[column][index]:<{widths[column]}}"
            if column != _AMOUNT_COLUMN
            else f"{columns[column][index]:>{widths[column]}}"
            for column in range(6)
        ]
        if has_tags:
            cells.append(columns[6][index])
        lines.append(" | ".join(cells))
    return lines


def format_transaction_stream(tx: Transaction) -> str:
    """검색용 한 행 포맷: 열 너비를 미리 고정해 전체 결과를 모으지 않는다."""
    line = (
        f"{tx.id:<9} | {tx.date} | {tx.type:<7} | "
        f"{tx.category:<18} | {tx.amount:>12} | {tx.memo}"
    )
    if tx.tags:
        line += f" | {','.join(tx.tags)}"
    return line
