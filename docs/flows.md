# 실행 흐름과 시퀀스 다이어그램

[← 프로젝트 소개](../README.md) · [아키텍처](architecture.md) · [저장 계약](storage.md) · [명령어](commands.md)

이 문서는 실제 코드의 호출 순서를 시각화합니다. 다이어그램은 GitHub Markdown에서 렌더링되는 **Mermaid** 문법을 사용합니다. 렌더링을 지원하지 않는 뷰어에서는 코드 블록으로 보이지만, 흐름 자체는 그대로 읽을 수 있습니다.

## 공통 시작: 명령 해석과 저장소 준비

모든 명령은 `python -m budget_app`으로 시작합니다. `__main__.py`가 `cli.main()`의 반환값을 프로세스 종료 코드로 전달하고, `main()`은 세 데코레이터로 감싸져 있습니다. 아래 저장소 준비 단계는 `list`처럼 내부 CSV를 사용하는 명령의 흐름입니다. `backup`은 `_open_stores()` 대신 `backup_files()`에서 대상 파일을 직접 확인합니다.

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자 / 셸
    participant Main as __main__.py
    participant CLI as cli.main()
    participant Parser as argparse
    participant Decorators as handle_errors · timed · logged
    participant Store as ensure_storage()
    participant FS as 파일 시스템

    User->>Main: python -m budget_app list
    Main->>Decorators: 장식된 main(argv) 호출
    Decorators->>CLI: @handle_errors → @timed → @logged → 실제 main()
    CLI->>Parser: 명령/옵션 해석
    Parser-->>CLI: Namespace(command, data_dir, ...)
    CLI->>Store: _open_stores(data_dir)
    Store->>FS: data/ 및 CSV 4개 확인·생성
    Note over Store,FS: categories.csv가 없거나 비어 있으면<br/>기본 카테고리 4개를 시드
    Store-->>CLI: Transaction/Category/Budget/RecurrenceStore
    CLI-->>Decorators: 명령 함수의 종료 코드
    Decorators-->>Main: 성공=0 / 처리 오류=1 / Ctrl+C=130
    Main-->>User: 프로세스 종료 코드
```

`argparse`의 잘못된 명령이나 옵션은 종료 코드 `2`를 냅니다. `handle_errors`는 `ModelError`, `StoreError`, EOF와 일반 예외를 `[오류]`·`[힌트]` 형식으로 stderr에 출력합니다. `logged`와 `timed`는 기본적으로 조용하며, `BUDGET_APP_LOG=DEBUG`일 때만 표준 logging으로 관측 정보를 남깁니다.

## 거래 추가: 대화형 검증 → 원자적 재작성

`add`는 한 줄을 단순히 파일 끝에 붙이지 않습니다. 새 ID를 계산하고 기존 거래와 함께 정렬한 뒤, 완성된 새 파일을 기존 파일과 교체합니다. 이 선택은 최신순 파일 순서와 실패 시 기존 파일 보존을 위한 것입니다.

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as _cmd_add()
    participant Model as validate_* / Transaction
    participant Category as CategoryStore
    participant TransactionStore as TransactionStore
    participant Atomic as _atomic_write()
    participant FS as transactions.csv

    User->>CLI: add 실행
    loop 날짜·타입·카테고리·금액
        CLI->>User: input() 질문
        User-->>CLI: 입력값
        CLI->>Model: 형식 검증
        alt 유효하지 않음
            Model-->>CLI: ModelError
            CLI-->>User: [오류] / 재입력 안내
        else 카테고리 입력
            CLI->>Category: names() / 등록 여부 확인
            Category-->>CLI: 표준 카테고리명 또는 없음
        end
    end
    CLI->>TransactionStore: next_id()
    TransactionStore->>FS: 거래 CSV를 스트리밍 순회
    FS-->>TransactionStore: 현재 최대 ID
    TransactionStore-->>CLI: TX-000001 형태의 새 ID
    CLI->>Model: Transaction(...) 생성
    CLI->>TransactionStore: add(transaction)
    TransactionStore->>TransactionStore: read_all() + 새 거래 추가 + 최신순 정렬
    TransactionStore->>Atomic: _atomic_write(path, header, rows)
    Atomic->>FS: 같은 폴더에 .transactions.csv.*.tmp 생성
    Atomic->>FS: CSV 작성 → flush → fsync
    Atomic->>FS: os.replace(tmp, transactions.csv)
    Atomic-->>TransactionStore: 성공
    TransactionStore-->>CLI: 저장 완료
    CLI-->>User: [저장 완료] id=TX-000001
```

> `add`, `update`, `delete`, `import`, `recur run --apply`는 거래 파일을 재작성합니다. 따라서 읽기 전용 명령처럼 완전한 상수 메모리 경로가 아닙니다. 소규모 파일 저장 프로그램에서는 단순성과 단일 파일 원자성을 우선한 선택입니다.

## `yield`와 스트리밍: list / search가 행을 읽는 방법

### `yield`는 무엇인가

일반 함수는 `return`으로 결과를 한 번에 넘기고 끝납니다. `yield`가 있는 함수는 **제너레이터(generator)** 를 반환합니다. 제너레이터는 호출만 했을 때 파일 전체를 읽지 않고, 소비자가 다음 값을 요청할 때마다 이전 위치부터 실행을 재개해 한 값씩 넘깁니다.

```python
def iter_transactions(self) -> Iterator[Transaction]:
    for line_no, row in _iter_rows(self.path, TXN_FIELDS):
        yield transaction_from_row(row)
```

| 방식 | 예 | 메모리 특성 |
| --- | --- | --- |
| 전체 로드 | `rows = list(iter_transactions())` | 거래 수 `N`개에 비례하는 메모리 `O(N)` |
| 스트리밍 | `for tx in iter_transactions(): ...` | 현재 행과 집계값 중심, 보통 `O(1)` 또는 제한된 크기 |

`yield`는 큰 파일을 **자동으로 빠르게 만드는 기능이 아닙니다.** 메모리 사용량을 제한하고, 필요한 만큼만 읽을 수 있게 만드는 제어 흐름입니다. 디스크에서 모든 행을 읽어야 하는 검색/요약의 전체 I/O 시간까지 사라지지는 않습니다.

### 검색: 생성 → 다음 행 요청 → 필터 → 출력

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as _cmd_search()
    participant Service as search_transactions()
    participant Repo as iter_transactions()
    participant CSV as csv.DictReader
    participant Formatter as format_transaction_stream()

    User->>CLI: search --category food --tag meal
    CLI->>Service: 필터 인자 전달
    Service-->>CLI: 제너레이터 객체 반환<br/>(아직 전체 결과 없음)
    loop CLI가 다음 거래를 요청하는 동안
        CLI->>Service: next / for 루프 진행
        Service->>Repo: 다음 Transaction 요청
        Repo->>CSV: 다음 CSV 행 읽기
        CSV-->>Repo: row
        Repo-->>Service: yield Transaction
        alt 필터 불일치
            Service->>Service: continue (출력하지 않음)
        else 모든 필터 일치
            Service-->>CLI: yield Transaction
            CLI->>Formatter: 한 줄 포맷
            Formatter-->>User: 즉시 출력
        end
    end
    Note over CLI,CSV: 검색 결과 목록을 만들지 않는다.<br/>파일 끝에서 루프 종료.
```

`search_transactions()`은 `--from`, `--to`, `--category`, `--type`, `--q`, `--tag`를 모두 만족하는 거래만 `yield`합니다. `list`도 저장소 읽기 자체는 스트리밍이지만, **출력 열 폭**을 맞추기 위해 `--limit` 이내의 거래만 목록에 잠시 보관합니다. 기본값 20이므로 이 버퍼는 최대 20건입니다.

```mermaid
sequenceDiagram
    actor CLI as _cmd_list()
    participant Repo as iter_transactions()
    participant CSV as transactions.csv
    participant Formatter as format_transactions()

    CLI->>Repo: 제너레이터 순회 시작
    loop 최대 --limit N건
        Repo->>CSV: 다음 행 읽기
        CSV-->>Repo: Transaction
        Repo-->>CLI: yield Transaction
        CLI->>CLI: 표시 버퍼에 1건 추가
    end
    CLI->>Formatter: 최대 N건의 열 폭 계산·포맷
    Formatter-->>CLI: 정렬된 줄 목록
    CLI-->>CLI: stdout 출력
```

### 스트리밍이 적용되지 않는 곳

| 기능 | 전체 데이터를 모으는 이유 |
| --- | --- |
| `add` / `import` | 기존 ID 중복 검사·새 ID 생성 후 정렬된 파일 전체 재작성 |
| `update` / `delete` | 대상 행을 변경/제거하고 나머지 행과 함께 새 파일로 재작성 |
| `summary` | 거래 행은 모으지 않지만 카테고리별 합계 `dict`는 유지 |
| `recur run --apply` | 해당 월의 중복 키와 생성할 거래 목록을 유지 |

파일 기반 구조에서 수정/삭제를 스트리밍 변환으로 구현할 수도 있지만, 현재 구현은 검증된 거래 전체를 메모리에 둔 다음 단순하게 정렬·원자 교체합니다. 데이터가 커지고 쓰기 빈도가 높아지면 SQLite 같은 DB 저장소가 더 적합합니다.

## 수정과 삭제: 읽기 → 변환 → 임시 파일 → 교체

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as update / delete
    participant Store as TransactionStore
    participant Atomic as _atomic_write()
    participant FS as 파일 시스템

    User->>CLI: update --id TX-000001<br/>또는 delete --id TX-000001
    CLI->>Store: iter_transactions()으로 대상 확인
    alt 대상 없음
        Store-->>CLI: None / False
        CLI-->>User: [오류] 없는 거래 ID + 힌트
    else 대상 존재
        alt update
            CLI->>User: 필드별 질문 (엔터=유지)
            User-->>CLI: 변경값
            CLI->>Store: update(id, 변경 필드)
        else delete
            CLI->>Store: delete(id)
        end
        Store->>Store: read_all() 후 변경/제거
        Store->>Store: (date, id) 내림차순 정렬
        Store->>Atomic: 새 전체 CSV 기록 요청
        Atomic->>FS: 같은 디렉터리에 임시 파일 생성
        Atomic->>FS: 기록 → flush → fsync
        Atomic->>FS: os.replace(임시 파일, 원본)
        Atomic-->>Store: 단일 파일 교체 완료
        Store-->>CLI: 수정된 거래 / 성공 여부
        CLI-->>User: [수정 완료] / [삭제 완료]
    end
```

`os.replace()` 이전에 실패하면 기존 `transactions.csv`는 그대로 남습니다. 단, 이 다이어그램은 **한 프로세스·한 파일** 기준입니다. 같은 파일을 여러 프로세스가 동시에 수정하는 문제는 해결하지 않습니다. 자세한 보장 범위는 [저장 안정성 문서](storage.md#쓰기-안정성과-한계)를 참고하세요.

## CSV 내보내기와 가져오기

### export: 읽기는 스트리밍, 출력 파일은 원자적 교체

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as _cmd_export()
    participant Service as export_transactions()
    participant Repo as TransactionStore
    participant Atomic as _atomic_write()
    participant Source as transactions.csv
    participant Output as report.csv

    User->>CLI: export --out report.csv --month 2024-01
    CLI->>Service: 필터와 출력 경로 전달
    Service->>Service: 필터 존재·내부 파일 덮어쓰기 검사
    Service->>Atomic: 교환용 CSV 쓰기 요청
    loop 원본 거래를 한 행씩 순회
        Atomic->>Repo: 다음 거래 행 요청
        Repo->>Source: 다음 CSV 행 읽기
        Source-->>Repo: Transaction
        Repo-->>Atomic: yield Transaction
        alt 월/기간 조건 일치
            Atomic->>Atomic: 교환 스키마 행 생성
        end
    end
    Atomic->>Output: 임시 report.csv 작성 → fsync → os.replace
    Service-->>CLI: 기록 건수
    CLI-->>User: [완료] report.csv (N records)
```

### import: 외부 행 검증 → 일괄 저장

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as _cmd_import()
    participant Service as import_transactions()
    participant ImportCSV as incoming.csv
    participant Category as CategoryStore
    participant Store as TransactionStore
    participant Atomic as _atomic_write()

    User->>CLI: import --from incoming.csv
    CLI->>Service: 파일 경로 전달
    Service->>ImportCSV: 헤더 검사 (UTF-8, 필수 컬럼)
    alt 헤더/CSV 문법 오류
        ImportCSV-->>CLI: StoreError; 거래 파일 변경 없음
    else 파일 정상
        Service->>Category: 등록 카테고리 목록 읽기
        loop 외부 CSV의 각 행
            Service->>Service: 날짜·type·금액·태그·카테고리 검증
            alt 유효한 행
                Service->>Service: 새 Transaction 및 새 ID 목록에 추가
            else 잘못된 행 / 미등록 카테고리 / 초과 컬럼
                Service->>Service: skipped += 1
            end
        end
        Service->>Store: insert_many(유효 거래 목록)
        Store->>Atomic: 전체 transactions.csv 재작성
        Atomic-->>Store: os.replace로 교체
        Store-->>CLI: imported / skipped 수
        CLI-->>User: [완료] imported=N, skipped=M
    end
```

행 단위 오류는 건너뛰지만, 헤더 오류나 깨진 CSV 인용 문법처럼 **파일 구조 자체가 유효하지 않은 경우에는 일괄 저장 전에 실패**합니다. 따라서 그 경우에는 일부 행만 가져와지는 상태가 생기지 않습니다. 교환 CSV의 정확한 규약은 [저장 파일 문서](storage.md#importexport-교환용-csv)를 참고하세요.

## 반복 거래와 백업

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as recur run
    participant Service as expand_recurrences()
    participant Rules as recurrences.csv
    participant Tx as transactions.csv
    participant Category as categories.csv
    participant Store as TransactionStore

    User->>CLI: recur run --month 2024-02 [--apply]
    CLI->>Service: 월과 apply 여부 전달
    Service->>Tx: 해당 월 거래를 읽어 중복 키 구성
    Service->>Category: 등록 카테고리 목록 읽기
    Service->>Rules: 반복 규칙을 순회
    loop 각 규칙
        alt 그 달에 존재하지 않는 일자
            Service->>Service: 일자없음 건수 증가
        else 미등록 카테고리
            Service->>Service: 미등록 건수 증가
        else 같은 날짜·type·category·amount 존재
            Service->>Service: 중복 건수 증가
        else 생성 가능
            Service->>Service: 생성 예정 목록 추가
        end
    end
    alt --apply 없음
        Service-->>CLI: 미리보기 결과 (파일 변경 없음)
    else --apply 있음
        Service->>Store: insert_many(생성 예정 거래)
        Store-->>CLI: 생성 건수
    end
    CLI-->>User: 예정/건너뜀/생성 결과
```

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant CLI as _cmd_backup()
    participant Backup as backup_files()
    participant Data as data/*.csv
    participant Temp as data/backups/.backup-*/
    participant Final as data/backups/backup-YYYYmmdd-HHMMSS/

    User->>CLI: backup
    CLI->>Backup: backup_files(data_dir)
    Backup->>Data: 존재하는 내부 CSV 4개 확인
    Backup->>Temp: 임시 백업 폴더 생성
    loop 각 내부 CSV
        Backup->>Data: copy2(source)
        Data-->>Temp: 파일 복사
    end
    Backup->>Final: os.replace(임시 폴더, 최종 폴더)
    Backup-->>CLI: 폴더 경로와 파일 수
    CLI-->>User: [백업 완료] ...
```

백업 폴더는 완성된 파일이 모두 복사된 뒤 공개됩니다. 다만 백업 도중 다른 프로세스가 원본 네 파일을 수정하면 하나의 일관된 시점 스냅샷은 보장하지 않습니다.
