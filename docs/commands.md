# 명령어 사용법

[← 프로젝트 소개](../README.md) · [저장 형식](storage.md) · [직접 테스트](development.md)

모든 예시는 **프로젝트 루트**에서 실행합니다. `python` 명령이 Python 3.10+을 가리키지 않는 환경에서는 `python3`로 바꾸세요.

```text
python -m budget_app <command> [options]
```

- `--help`: 최상위 또는 각 명령/하위 명령의 사용법 확인. 예: `python -m budget_app recur run --help`.
- `--data-dir DIR`: 저장 폴더 변경(기본값: **현재 작업 디렉터리**의 `./data`). 하위 명령에서는 마지막에 쓰는 방식이 가장 명확합니다: `budget set --month 2024-01 --amount 50000 --data-dir ./my-data`.
- 옵션은 모두 `--`를 사용합니다. 날짜는 `YYYY-MM-DD`, 월은 `YYYY-MM`, 금액은 **1 이상의 정수**입니다.
- 입력을 받는 명령은 **add, category add/remove, update, recur add**입니다. 그 외 명령은 인자로 실행합니다.

## 거래: add / list / search

### 거래 추가 — `add`

```console
$ python -m budget_app add
날짜(YYYY-MM-DD): 2024-01-15
타입(income/expense): expense
카테고리: food
금액(양수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal,weekday
[저장 완료] id=TX-000001
```

날짜·타입·카테고리·금액이 잘못되면 해당 질문에서 이유를 보여주고 재입력받습니다. 카테고리는 등록된 이름이어야 합니다(처음 실행하면 `food`, `transport`, `rent`, `salary`가 준비됩니다). 메모와 태그는 엔터로 비울 수 있습니다. 태그는 쉼표로 분리하며 앞뒤 공백과 중복 태그는 정리합니다.

### 최신순 목록 — `list`

```bash
python -m budget_app list                 # 기본 20건
python -m budget_app list --limit 3       # 최대 3건; N >= 1
```

날짜 내림차순, 같은 날짜면 거래 ID 내림차순입니다. 보이는 **최대 N건만** 메모리에 모아 열 폭을 맞춥니다. 금액은 오른쪽 정렬이고, 표시 대상 전체에 태그가 없으면 태그 열은 생략됩니다. 거래가 없으면 `저장된 거래가 없습니다`를 출력합니다.

### 조건 검색 — `search`

```bash
python -m budget_app search --from 2024-01-01 --to 2024-01-31 --category food
python -m budget_app search --type expense --q 점심 --tag meal
```

| 옵션 | 의미 |
| --- | --- |
| `--from YYYY-MM-DD` / `--to YYYY-MM-DD` | 양 끝 날짜 포함; 시작일이 종료일보다 늦으면 오류 |
| `--category NAME` | 카테고리 이름 정확히 일치(대소문자 무시) |
| `--type income\|expense` | 거래 유형 |
| `--q TEXT` | 메모 부분 검색(대소문자 무시) |
| `--tag TAG` | 태그 1개와 정확히 일치 |

조건을 여러 개 주면 **모두** 만족하는 거래만 최신순으로 출력합니다. 결과는 모으지 않고 한 건씩 출력하므로 목록과 달리 열 폭은 고정입니다. 매칭 건이 없으면 `조건에 맞는 거래가 없습니다`를 출력합니다.

## 요약과 예산: summary / budget

```bash
python -m budget_app budget set --month 2024-01 --amount 30000
python -m budget_app budget list
python -m budget_app summary --month 2024-01 --top 3
```

`budget set`은 해당 월의 예산을 새로 지정하거나 덮어씁니다. `summary`는 총수입, 총지출, 잔액(수입−지출)과 **지출 카테고리별 합계 TOP N**을 보여줍니다(`--top` 기본 5, 1 이상). 지출이 예산보다 *클 때만* 초과 경고를 표시합니다(같으면 경고 없음).

```text
총 수입: 3000000원
총 지출: 35000원
잔액: 2965000원
예산: 30000원 (사용률 116.7%) [경고] 예산 초과 — 5000원
지출 TOP 2
1) transport 20000원
2) food 15000원
```

거래가 없는 월에도 수입·지출·잔액 `0원`, 설정된 예산의 `0.0%`, `YYYY-MM 데이터 없음`을 출력합니다. 거래는 있지만 지출이 없으면 `지출 없음`입니다.

## 카테고리: category add / list / remove

```bash
python -m budget_app category list
python -m budget_app category add        # 카테고리명 프롬프트: coffee
python -m budget_app category remove     # 삭제할 카테고리명 프롬프트: coffee
```

이미 있는 이름을 추가하면 재입력받습니다. **거래 또는 반복 규칙**이 사용 중인 카테고리는 삭제할 수 없습니다. 해당 거래는 `update`로 이동하고 반복 규칙은 `recur remove`로 제거한 뒤 다시 시도하세요.

## 거래 수정·삭제: update / delete

`update`는 **대화형 방식으로 고정**했습니다. `--id`로 대상을 정한 뒤 날짜 → 타입 → 카테고리 → 금액 → 메모 → 태그 순서로 질문합니다.

```bash
python -m budget_app update --id TX-000001
python -m budget_app delete --id TX-000001
```

| 수정 질문에 입력 | 동작 |
| --- | --- |
| 엔터 | 현재 값 유지 |
| 새 값 | 해당 필드만 변경(잘못된 값이면 해당 필드 재질문) |
| `-` | **메모 또는 태그에 한해** 내용 지우기 |

예를 들어 금액만 바꾸려면 첫 세 질문(날짜/타입/카테고리)에 엔터를 누르고, 새 금액을 입력한 다음 나머지 두 질문에 엔터를 누릅니다. 변경할 값이 없으면 `변경된 항목이 없습니다`가 표시됩니다. 존재하지 않는 거래 ID로 수정/삭제하면 오류 메시지와 함께 종료 코드가 0이 아닙니다.

## CSV 교환: export / import

```bash
python -m budget_app export --out ./report.csv --month 2024-01
python -m budget_app export --out ./report.csv --from 2024-01-01 --to 2024-01-31
python -m budget_app import --from ./incoming.csv
```

`export`는 `--out` 외에 **`--month`, `--from`, `--to` 가운데 하나 이상** 지정해야 합니다. 여러 조건을 주면 모두 적용합니다. 건수를 출력하며 내부 저장 파일(`transactions.csv` 등) 덮어쓰기는 막습니다. `import`는 `imported=N, skipped=M`을 출력하고, 행별 형식 오류 또는 미등록 카테고리를 건너뜁니다. 잘못된 헤더/CSV 문법은 파일 단위 오류입니다. **가져올 때마다 새 ID를 발급하며 중복 거래 여부는 검사하지 않습니다.** 같은 파일을 두 번 가져오면 두 번 추가됩니다.

CSV 컬럼·인코딩·건너뜀 정책과 파일 예시는 [저장 형식 문서](storage.md#importexport-교환용-csv)를 참고하세요.

## 백업과 반복 거래: backup / recur

```bash
python -m budget_app backup
python -m budget_app recur add                # 유형/카테고리/금액/일자(1~31)/메모 입력
python -m budget_app recur list
python -m budget_app recur run --month 2024-02          # 미리보기; 저장하지 않음
python -m budget_app recur run --month 2024-02 --apply  # 실제 거래 생성
python -m budget_app recur remove --id R-000001
```

`backup`은 `data/backups/backup-YYYYmmdd-HHMMSS/`에 내부 CSV 4개를 복사합니다(`--data-dir` 변경 시 해당 폴더 내부). 해당 월에 없는 일자(2월 31일), 미등록 카테고리, 같은 날짜·유형·카테고리·금액 거래는 `recur run`에서 건너뛰고 사유별 건수를 표시합니다. 반복 규칙을 제거해도 **이미 생성된 거래는 남습니다**. 더 자세한 동작과 백업 한계는 [저장 형식 문서](storage.md#백업과-복구)를 확인하세요.
