# 개발·검증 가이드

[← 프로젝트 소개](../README.md) · [명령어](commands.md) · [아키텍처](architecture.md)

## 환경과 자동 테스트

- Python **3.10 이상**, 외부 패키지 설치 불필요(표준 라이브러리만 사용).
- 프로젝트 루트에서 실행해야 `budget_app` 패키지를 찾을 수 있습니다.

```bash
python3 --version
python3 -m unittest discover -s tests -v
python3 -m budget_app --help
```

`tests/test_core.py`는 CLI 입력 재시도, 월별 요약·빈 달의 예산, 수정/삭제의 없는 ID, import/export 스키마 및 손상 CSV 보호, 전체 하위 명령 `--help` 등을 검사합니다. `tests/test_bonus.py`는 백업, 반복 규칙, 목록 정렬, CSV 내보내기 등을 검사합니다. `tests/test_decorators.py`는 데코레이터(로깅·시간 측정·오류 계약)를 검사합니다 — 표준 `logging`(`assertLogs`)과 주입한 clock으로 검증하며, 기본 무출력이라 기존 콘솔 계약을 바꾸지 않습니다. 테스트는 임시 폴더를 사용하므로 기본 `data/` 파일을 지우거나 덮어쓰지 않습니다.

### 데코레이터 출력 보기(선택)

로깅·시간 측정은 기본 무출력이라 일반 실행 출력은 그대로입니다. 환경변수 `BUDGET_APP_LOG`로 켭니다(레벨 이름 또는 `1`/`true`/`yes`/`on`).

```bash
BUDGET_APP_LOG=DEBUG python3 -m budget_app list --data-dir "$DATA"
```

stderr 예(순서·수치는 실행마다 다름):

```text
DEBUG budget_app: main 호출
DEBUG budget_app: main 반환
DEBUG budget_app: main: 0.003초
```

`@timed`가 걸린 내보내기/가져오기에서는 `export_transactions: 0.002초` 같은 줄이 함께 찍힙니다. 테스트는 임시 폴더를 쓰므로 기본 `data/`는 그대로입니다.

## 수동 확인: 데이터 분리해서 시작하기

기존 `data/`를 건드리지 않으려면 **새 빈 폴더 이름**을 지정하세요. 이미 존재하는 폴더를 사용하면 거래 ID와 예상 합계가 달라질 수 있습니다. 아래 명령은 macOS/Linux의 셸 예시입니다.

```bash
DATA=./manual-test-data
python3 -m budget_app category list --data-dir "$DATA"
```

카테고리 네 개가 출력되고, 해당 폴더에 CSV 네 파일이 생겨야 합니다. `add`를 두 번 실행하고 질문에 다음 값을 입력합니다.

| 거래 | 날짜 | 타입 | 카테고리 | 금액 | 메모 | 태그 |
| --- | --- | --- | --- | ---: | --- | --- |
| 1 | `2024-01-15` | `expense` | `food` | `15000` | `점심` | `meal` |
| 2 | `2024-01-14` | `income` | `salary` | `3000000` | `월급` | 빈 값(엔터) |

```bash
python3 -m budget_app add --data-dir "$DATA"    # 위 표의 1번 입력
python3 -m budget_app add --data-dir "$DATA"    # 위 표의 2번 입력
python3 -m budget_app list --limit 2 --data-dir "$DATA"
python3 -m budget_app search --tag meal --data-dir "$DATA"
python3 -m budget_app budget set --month 2024-01 --amount 10000 --data-dir "$DATA"
python3 -m budget_app summary --month 2024-01 --data-dir "$DATA"
```

**기대:** ID `TX-000001`, `TX-000002`; 목록은 날짜 최신순(1번이 먼저); `search`는 1건; 요약은 수입 3,000,000원/지출 15,000원/잔액 2,985,000원/예산 사용률 150.0% 및 초과 경고입니다.

```bash
python3 -m budget_app update --id TX-000001 --data-dir "$DATA"
```

금액만 바꾸려면 **날짜·타입·카테고리에는 엔터**, 금액에는 `20000`, 메모·태그에는 엔터를 입력합니다. `list`에 20,000원이 보이면 성공입니다.

```bash
python3 -m budget_app export --out "$DATA/export.csv" --month 2024-01 --data-dir "$DATA"
python3 -m budget_app backup --data-dir "$DATA"
python3 -m budget_app recur add --data-dir "$DATA"
```

`export`는 2건; 백업은 4개 내부 파일 복사(교환용 `export.csv`는 제외). 반복 규칙에는 `expense`, `rent`, `500000`, `15`, `월세`를 입력합니다.

```bash
python3 -m budget_app recur run --month 2024-02 --data-dir "$DATA"          # 미리보기
python3 -m budget_app recur run --month 2024-02 --apply --data-dir "$DATA"  # 거래 1건 추가
python3 -m budget_app recur run --month 2024-02 --apply --data-dir "$DATA"  # 중복으로 0건
python3 -m budget_app summary --month 2024-02 --data-dir "$DATA"
```

더 많은 시나리오(카테고리 삭제, import, 기간 검색)는 [명령어 가이드](commands.md)에 있습니다.

### 실패 경로도 확인하기

```bash
python3 -m budget_app delete --id TX-999999 --data-dir "$DATA"
echo $?  # 직전 명령: 1(오류); 정상 명령은 0
python3 -m budget_app export --out "$DATA/transactions.csv" --month 2024-01 --data-dir "$DATA"
echo $?  # 내부 저장 파일 보호로 오류
python3 -m budget_app search --from 2024-02-01 --to 2024-01-01 --data-dir "$DATA"
```

잘못된 명령/옵션은 종료 코드 `2`, Ctrl+C는 `130`입니다. 오류에는 `[오류]`와 `[힌트]`가 표시되고 스택트레이스는 출력되지 않아야 합니다. 오류는 stderr, 정상 결과는 stdout으로 나옵니다(대화형 재입력 안내는 화면에서 바로 보입니다).

## 흔한 문제

| 증상 | 확인할 것 |
| --- | --- |
| `No module named budget_app` | 프로젝트 루트에서 실행했는지, `python3 --version`이 3.10 이상인지 |
| 저장한 내역이 안 보임 | 실행한 **현재 디렉터리**와 `--data-dir`이 앞선 명령과 같은지 |
| 카테고리가 없다고 나옴 | `category list`로 등록 이름 확인 후 `category add`로 등록 |
| CSV import에서 `skipped` 증가 | 컬럼 수/날짜/양수 정수/카테고리 등록 여부 확인. 개별 행 이유를 별도로 파일에 기록하지는 않음 |
| CSV 읽기 오류 | 헤더·쉼표·따옴표·UTF-8 확인, 손상 전 백업에서 복구 |
| 반복 규칙 적용 시 0건 | 기본 `run`은 미리보기인지, `--apply`를 사용했는지, 이미 동일한 거래가 있는지 확인 |

프로그램의 쓰기/동시 실행 제한과 백업 복구 방법은 [저장 파일 문서](storage.md)를 참고하세요.
