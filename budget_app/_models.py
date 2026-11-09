from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

TRANSACTION_TYPES = ("income", "expense")
ID_PREFIX = "TX-"
ID_PATTERN = re.compile(r"TX-\d+")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTH_PATTERN = re.compile(r"\d{4}-\d{2}")


class ModelError(ValueError):
    """입력/데이터 검증 실패. 원인(message)과 선택적 해결 힌트(hint)를 담는다."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True, slots=True)
class Transaction:
    id: str
    type: str
    date: str  # YYYY-MM-DD
    amount: int  # 양수
    category: str
    memo: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Category:
    name: str


@dataclass(frozen=True, slots=True)
class Budget:
    month: str  # YYYY-MM
    amount: int


@dataclass(frozen=True, slots=True)
class Recurrence:
    """반복 내역 규칙: 매월 `day`일에 같은 type/category/amount 로 생성."""

    id: str
    type: str
    category: str
    amount: int
    day: int  # 1~31
    memo: str = ""


def validate_date(value: Any) -> str:
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise ModelError(f"날짜 형식이 올바르지 않습니다: {value!r} (YYYY-MM-DD, 예: 2024-01-15)")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ModelError(f"존재하지 않는 날짜입니다: {value!r}") from exc
    return value


def validate_type(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in TRANSACTION_TYPES:
        raise ModelError(f"허용되지 않은 타입입니다: {value!r} (income 또는 expense)")
    return value.strip().lower()


def validate_day(value: Any) -> int:
    if isinstance(value, bool):
        raise ModelError(f"일자는 1~31 사이 정수여야 합니다: {value!r}")
    if isinstance(value, int):
        day = value
    elif isinstance(value, str) and value.strip().isdigit():
        day = int(value.strip())
    else:
        raise ModelError(f"일자는 1~31 사이 정수여야 합니다: {value!r}")
    if not 1 <= day <= 31:
        raise ModelError(f"일자는 1~31 사이여야 합니다: {day}")
    return day


def validate_amount(value: Any) -> int:
    if isinstance(value, bool):
        raise ModelError(f"금액은 1 이상의 정수여야 합니다: {value!r}")
    if isinstance(value, int):
        amount = value
    elif isinstance(value, str) and value.strip().isdigit():
        amount = int(value.strip())
    else:
        raise ModelError(f"금액은 1 이상의 정수여야 합니다: {value!r}")
    if amount <= 0:
        raise ModelError(f"금액은 1 이상이어야 합니다: {amount}")
    return amount


def validate_category(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelError("카테고리명이 비어 있습니다")
    return value.strip()


def validate_month(value: Any) -> str:
    if not isinstance(value, str) or not MONTH_PATTERN.fullmatch(value):
        raise ModelError(f"월 형식이 올바르지 않습니다: {value!r} (YYYY-MM, 예: 2024-01)")
    try:
        date(int(value[:4]), int(value[5:7]), 1)
    except ValueError as exc:
        raise ModelError(f"존재하지 않는 월입니다: {value!r}") from exc
    return value


def parse_tags(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, str):
        raise ModelError(f"태그는 문자열이어야 합니다: {raw!r}")
    seen: dict[str, None] = {}
    for part in raw.split(","):
        tag = part.strip()
        if tag and tag not in seen:
            seen[tag] = None
    return tuple(seen)


def format_tags(tags: Iterable[str]) -> str:
    return ",".join(tags)


def transaction_from_row(row: dict[str, Any]) -> Transaction:
    """CSV 행(dict) → Transaction. 형식 검증은 여기서 수행."""
    tx_id = row.get("id")
    if not isinstance(tx_id, str) or not ID_PATTERN.fullmatch(tx_id):
        raise ModelError(f"거래 id 형식 오류: {tx_id!r} (예: TX-000001)")
    return Transaction(
        id=tx_id,
        type=validate_type(row.get("type")),
        date=validate_date(row.get("date")),
        amount=validate_amount(row.get("amount")),
        category=validate_category(row.get("category")),
        memo=row.get("memo") or "",
        tags=parse_tags(row.get("tags")),
    )
