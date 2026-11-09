# 설계와 코드 읽기

[← 프로젝트 소개](../README.md) · [명령어](commands.md) · [저장 형식](storage.md) · [개발·테스트](development.md)

## 계층과 의존 관계

```text
python -m budget_app
      │
      ▼
__main__.py ──► cli.py ──────► _service.py ──────► _store.py
                    │                 │                 │
                    ├── _format.py    └── _models.py ◄──┘
                    ├── _decorators.py
                    └── _config.py
```

| 파일 | 담당 역할 | 대표 코드 |
| --- | --- | --- |
| `budget_app/__main__.py` | `python -m budget_app` 시작점, 정상/오류 종료 코드 전달 | `raise SystemExit(main())` |
| `budget_app/cli.py` | `argparse`, 대화형 `input()`, 명령별 메시지, 각 계층 호출 | `build_parser()`, `_cmd_add()`, `_cmd_update()` |
| `budget_app/_models.py` | 불변 데이터 구조·입력 형식 검증 | `Transaction`, `Budget`, `Recurrence`, `validate_date()` |
| `budget_app/_store.py` | 내부 CSV I/O, 기본 카테고리 시드, 임시 파일 교체, 백업 | `TransactionStore.iter_transactions()`, `_atomic_write()` |
| `budget_app/_service.py` | 검색 조건·요약·예산 사용률·CSV 교환·반복 규칙 적용 | `search_transactions()`, `month_summary()`, `expand_recurrences()` |
| `budget_app/_format.py` | 콘솔 거래 목록/검색 출력 포맷 | `format_transactions()`, `format_transaction_stream()` |
| `budget_app/_decorators.py` | 명령 공통 오류 출력·종료 코드 처리 | `@handle_errors` |
| `budget_app/_config.py` | 기본 `./data` 및 `--data-dir` 경로 해석 | `resolve_data_dir()` |

CLI는 입력 방식과 출력 메시지에 집중하고, 서비스는 **정책/집계**, 저장소는 **파일을 읽고 쓰는 방법**에 집중합니다. CSV 포맷이나 파일 경로가 바뀌어도 데이터 정책과 CLI가 동시에 크게 바뀌지 않도록 경계를 나눴습니다.

## 제너레이터 스트리밍의 실제 범위

```python
def iter_transactions(self) -> Iterator[Transaction]:
    for line_no, row in _iter_rows(self.path, TXN_FIELDS):
        yield transaction_from_row(row)
```

`_iter_rows()`는 `csv.DictReader`로 CSV 행을 순서대로 읽습니다. `yield`로 한 건을 반환한 뒤 다음 행은 **소비자가 요청할 때** 읽습니다. 파일을 열어 둔 `with` 블록은 제너레이터가 순회되는 동안 유지됩니다.

| 경로 | 메모리 사용 방식 |
| --- | --- |
| `list --limit N` | 저장소는 스트리밍; 정렬된 출력 열 폭을 계산하려고 화면에 보여줄 최대 N건만 보관 |
| `search` | 조건 필터 제너레이터 → 행별 출력; 검색 결과를 모으지 않음 |
| `summary` | 모든 거래를 순회하지만 수입/지출 합계·카테고리별 합계만 보관 |
| `export` | 거래를 순회하면서 조건에 맞는 CSV 행을 생성해 파일에 씀 |
| `add` / `update` / `delete` / `import` | 원자적 재작성을 위해 기존 거래 및 새 거래를 메모리에 모음 |
| `recur run` | 중복 검사에 그 달의 기존 거래 키와 규칙 목록을 보관 |

즉 **"모든 명령이 상수 메모리"는 아닙니다.** 조회·검색·내보내기의 파일 읽기 경로에 스트리밍을 적용했고, 재작성은 안전한 단일 파일 교체와 단순성을 우선한 설계입니다. 거래량이 많거나 잦은 수정이 필요한 환경이면 [DB 이전](format-choice.md#sqlite로-이전한다면)이 적합합니다.

거래는 저장할 때 `(date, 숫자형 id)` 내림차순으로 정렬합니다. 이 불변식 덕분에 최신순 조회에서 **파일 전체를 메모리로 불러와 정렬하지 않아도** 됩니다. 파일을 수동으로 수정해 순서를 망가뜨리면 최신순 출력도 보장되지 않습니다.

## 데코레이터와 오류 계약

`cli.main()`에 `@handle_errors`를 적용합니다. 처리 중 발생한 `ModelError`, `StoreError`, EOF 등을 CLI 공통 형식으로 바꿉니다.

```text
[오류] 등록되지 않은 카테고리입니다: 'other'
[힌트] 'category add'로 등록하거나 'category list'로 목록을 확인하세요
```

명령별 함수가 같은 `try/except`와 출력 코드를 반복하지 않아도 되고, 호출자에게는 정상 종료 `0`, 처리 오류 `1`, 잘못된 명령/옵션 `2`, Ctrl+C `130`이라는 계약을 제공합니다. 대화형 재입력은 명령을 종료하지 않고 **현재 질문만 반복**하므로 `_ask_validated()`에서 처리합니다. 오류 메시지에는 스택트레이스를 출력하지 않습니다.

## 타입 힌트와 데이터 계약

```python
@dataclass(frozen=True, slots=True)
class Transaction:
    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: tuple[str, ...] = ()

def search_transactions(store: TransactionStore, *, tag: str | None = None) -> Iterator[Transaction]:
    ...
```

두 번째 함수 선언은 여러 검색 옵션 중 `tag`만 남긴 **시그니처 발췌 예시**입니다. `Transaction`의 필드 타입과 `search_transactions()`의 제너레이터 반환 타입은 **호출자가 전달할 것/받을 것**을 명확히 합니다. `frozen=True`는 생성된 모델의 필드 재할당을 막습니다. 다만 **타입 힌트 자체는 런타임 입력 검증이 아닙니다.** 날짜·금액·종류·월·카테고리 값은 검증 함수와 서비스에서 따로 확인합니다. `cli._ask_validated()`의 제네릭 `Callable[[str], T] -> T`는 검증기의 출력 타입을 그대로 프롬프트의 반환 타입으로 연결합니다.

## 원자적 교체의 보호 범위

파일 하나를 다시 쓸 때 `_atomic_write()`는 기존 파일과 같은 디렉터리에 임시 파일을 만들고, 헤더/행 기록·`flush`/`fsync` 이후 `os.replace()`합니다. 기록 도중 실패하면 임시 파일을 정리하므로 기존 파일의 중간 상태를 사용자에게 노출하지 않습니다. 백업도 완성 전에는 임시 폴더에 복사합니다.

이는 **단일 파일 단위 원자성**이지, 여러 파일을 함께 변경하는 DB 트랜잭션이나 여러 프로세스의 동시 수정 잠금이 아닙니다. 운영 제약은 [저장 파일과 CSV 계약](storage.md#쓰기-안정성과-한계)에 설명합니다.
