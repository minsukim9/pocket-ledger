# Pocket Ledger

> CSV 파일에 거래를 안전하게 기록하는 Python 콘솔 용돈 기입장.

수입·지출을 입력하고 검색하거나 월별로 정리할 수 있습니다. 예산 경고, 카테고리 관리, CSV 가져오기/내보내기와 함께 **백업·매월 반복 거래**도 지원합니다. Python 표준 라이브러리만 사용하며, 저장한 내용은 프로그램을 종료해도 남습니다.

## 빠른 시작

**준비:** Python **3.10 이상**, 별도 패키지 설치 불필요. 터미널에서 이 저장소의 루트 디렉터리로 이동하세요.

```bash
python3 --version
python3 -m budget_app --help
python3 -m budget_app add
```

`add`를 실행하면 날짜 → 수입/지출 → 카테고리 → 금액 → 메모 → 태그를 순서대로 묻습니다. 처음에는 `food`, `transport`, `rent`, `salary` 카테고리가 자동으로 준비됩니다.

```text
날짜(YYYY-MM-DD): 2024-01-15
타입(income/expense): expense
카테고리: food
금액(양수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal
[저장 완료] id=TX-000001
```

저장된 내용을 확인하거나 요약할 때는 다음처럼 실행합니다.

```bash
python3 -m budget_app list --limit 5
python3 -m budget_app search --category food --tag meal
python3 -m budget_app summary --month 2024-01
```

기본 저장 폴더는 **명령을 실행한 위치의 `./data`**입니다. 기존 기록과 분리해서 써보고 싶다면 모든 명령에 `--data-dir`을 지정하세요.

```bash
python3 -m budget_app add --data-dir ./manual-test-data
python3 -m budget_app list --data-dir ./manual-test-data
```

> [!IMPORTANT]
> 동일한 데이터 폴더에 **여러 프로세스가 동시에 쓰는 방식은 지원하지 않습니다.** 파일 하나의 원자적 교체와 여러 파일을 묶는 트랜잭션은 다릅니다. 제한 사항과 백업 방법은 [저장 파일 문서](docs/storage.md#쓰기-안정성과-한계)를 확인하세요.

## 주요 기능

| 작업 | 명령 | 동작 |
| --- | --- | --- |
| 거래 추가·조회 | `add`, `list --limit N` | 대화형 입력, 최신순 목록 |
| 거래 검색 | `search --from … --to … --category … --type … --q … --tag …` | 여러 조건으로 검색 |
| 요약·예산 | `summary --month YYYY-MM`, `budget set/list` | 월별 합계·카테고리 지출 TOP N·예산 초과 경고 |
| 카테고리 | `category add/list/remove` | 사용 중인 카테고리는 삭제 방지 |
| 수정·삭제 | `update --id ID`, `delete --id ID` | 수정은 **대화형 고정**(엔터=유지) |
| CSV 교환 | `import --from FILE`, `export --out FILE --month YYYY-MM` | 외부 데이터 가져오기·조건별 내보내기 |
| 백업·반복 거래 | `backup`, `recur add/list/run/remove` | 타임스탬프 백업·월 반복 규칙 미리보기/생성 |

모든 명령과 하위 명령은 `--help`를 제공합니다. 상세 옵션과 실행 예시는 [명령어 가이드](docs/commands.md)에 정리했습니다.

## 문서 안내

| 문서 | 이런 내용을 찾을 때 |
| --- | --- |
| [명령어 사용법](docs/commands.md) | 각 명령의 입력 방식·옵션·출력·예외 처리 |
| [저장 파일과 CSV 계약](docs/storage.md) | `data/` 위치, 내부 4개 CSV 스키마, **import/export 스키마**, 백업·복구·안전성 |
| [설계와 코드 읽기](docs/architecture.md) | CLI/서비스/저장소/모델의 책임, 제너레이터·데코레이터·타입 힌트 |
| [개발·검증 가이드](docs/development.md) | 자동 테스트, 사용자 직접 테스트 시나리오, 문제 해결 |
| [CSV·JSONL·SQLite 비교](docs/format-choice.md) | 저장 형식 선택 이유와 DB로 이전할 때의 고려 사항 |

## 프로젝트 구조

```text
budget_app/          # 실행 패키지: CLI, 모델, 서비스, CSV 저장소, 포맷터
tests/               # unittest 기반 기본 기능·보너스 회귀 테스트
docs/                # 주제별 사용자/개발자 문서
README.md            # 빠른 시작 및 문서 목차
```

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

테스트는 임시 폴더를 사용하여 기본 `data/`에 저장한 거래를 변경하지 않습니다. 무엇을 검증하는지와 수동 테스트 순서는 [개발·검증 가이드](docs/development.md)를 참고하세요.
