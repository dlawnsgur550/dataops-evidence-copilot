# 로컬 시연과 재현 절차

슬라이드·발표 대본은 만들지 않았다. 아래는 실행 환경, 조작 순서, 확인할 근거를 담은 운영 절차다. 합성 데이터만 사용하고 전용 데모 DB 밖을 변경하지 않는다.

## 저장 자료 확인 — API 비용 없음

프로젝트 루트에서 실행한다.

```bash
uv sync --locked --python 3.11
uv run python scripts/run_ui.py
```

브라우저 주소는 `http://127.0.0.1:18784`다. 모델 파일·DB·Airflow 없이도 저장 결과를 볼 수 있다. 화면 기본값은 ‘저장된 결과 보기’, API 사용 해제다. 실행 결과와 다운로드에는 비밀값이 없다.

| 순서 | 동작 | 확인할 것 |
| --- | --- | --- |
| 1 | 스키마 변경 선택 | 실행 로그의 amount 부재, 현재 관측과 과거 시점의 구분, 사람의 계약·매핑 검토 |
| 2 | 수집 근거 펼치기 | run/task/try, dbt invocation, 실제 수집 표시, 관측 시각·시간 범위 |
| 3 | 런북과 검토 탭 | 문서·청크 ID와 버전, 검토 통과가 복구와 별개임 |
| 4 | 복구 확인 탭 | 별도 후속 run의 성공, 두 품질 검사, 1,000건·502,360.39 정합성 |
| 5 | 필수 키 누락·실행 연결 실패 선택 | 원인별 다른 조치, 현재 probe만으로 과거 복구를 확정하지 않음 |
| 6 | JSON 내려받기·새로고침 | 결과를 보존하며 API를 자동 재호출하지 않음 |

실제 화면은 `artifacts/checkpoint4/screens/01-schema-diagnosis.png`부터 `05-connection.png`까지 있다. `browser-verification.json`에 실제 브라우저 조작과 과금 없는 동작 확인을 기록했다. 별도 최종 평가의 합성 실패 사례는 화면의 실제 DB 장애 시연과 구분한다.

## 무료 새 진단·검색 검사

공개 모델은 최초 한 번 다운로드한다. 모델 다운로드와 로컬 임베딩은 OpenAI API 비용이 없다. 모델 용량·revision·파일 해시는 `deployment/embedding-model.json`에 있다.

```bash
uv run python scripts/setup_rag_model.py
uv run dataops-copilot --fixture schema --transport stdio --retrieval hybrid --output artifacts/my-free-report.json
uv run pytest -q -W error::RuntimeWarning
```

fixture 보고서는 합성 조회·fake LLM의 검사이며 실제 모델 성능이나 실제 DB 통합으로 세지 않는다. 동결된 문서·평가셋을 다시 생성하는 스크립트는 기존 평가 재현 중 실행하지 않는다.

## 실제 파이프라인 시연

Docker Desktop과 이미 준비한 Airflow·dbt 개발 이미지가 필요하다. 설치 절차는 기존 `STEP1_LIVE.md`에 있다. 전용 DB와 소유 라벨을 검증하며 원본 파일·다른 후보·기존 사용자 DB는 초기화하지 않는다.

```bash
uv run python scripts/dev_services.py start
uv run python scripts/verify_container_boundary.py
uv run python scripts/dev_services.py stop
```

경계 검사는 유료 모델을 호출하지 않는다. 실제 새 정상 DAG의 전체 태스크와 품질 검사를 확인하고, API 키 파일이 Airflow 컨테이너에 없음을 검사한다. Airflow 소스는 읽기 전용, 필요한 산출물과 metadata만 쓰기 마운트다.

세 장애를 새로 주입하고 실제 모델까지 실행하려면 다음처럼 **명시적인 유료 실험**을 실행한다. 기존 완료 자료는 덮어쓰지 않고 새 시각의 결과 폴더를 만든다. 표준 프로필의 요청 한도는 이번 평가 후 소진됐으며 evaluation 프로필도 같은 금액·장부와 남은 호출 한도를 적용한다. 한도에 걸리면 중단하고 상한을 자동으로 올리거나 장부를 삭제하지 않는다.

```bash
uv run python scripts/dev_services.py start
uv run python scripts/live_e2e_openai.py --fresh
uv run python scripts/dev_services.py stop
```

`--fresh` 없이 실행하면 보존된 완료 기록을 확인하고 새 API 요청 없이 종료한다. 이 절차는 개발자 스크립트가 주입·조치하므로 사람이 직접 편집한 기록이 아니다.

사람이 개별 조치를 직접 확인하려면 먼저 실패 실행의 보고서와 아래 의미를 검토한다. 개발자 전용 `pipeline/driver.py --step repair --mode ... --config ...`는 격리된 데모 DB에서만 동작한다. 실제 업무 데이터에 이 합성 키 복원 방식을 적용하면 안 된다.

| 장애 | 이 합성 데모의 조치 | 새 실행의 완료 조건 |
| --- | --- | --- |
| 스키마 | 업무 의미를 확인하고 paid_amount를 원래 amount 계약에 맞춤 | 전체 태스크·두 검사·집계 일치 |
| NULL | 원본 생성 규칙이 확정된 합성 행의 키를 복원 | NULL·중복 0, 건수·합계 보존 |
| 연결 | 실제 실행 endpoint를 확인해 원래 데모 포트로 정정 | probe만으로 끝내지 않고 전체 새 실행 확인 |

## 고정 평가 재현

현재 결과 열람·CSV 집계·감사는 API를 호출하지 않는다. 독립된 사람 확인은 공란 양식을 사용한다. 모델을 다시 부르는 재평가는 별도 유료 행위이며 최초 결과와 분리해야 한다.

```bash
uv run python scripts/build_materials.py
uv run python scripts/audit_checkpoint4.py
```

동결 소스 묶음에는 평가 코드·모델 설정·증거·분리된 정답과 스크립트가 있다. 새 폴더를 같은 workspace의 outputs 아래에 풀고 의존성·공개 모델을 준비한 뒤 `run_evaluation.py --split final --paid --baseline --service-tier flex --api-settings <명시적 로컬 경로>`로 유료 재현할 수 있다. 같은 입력·코드여도 모델 응답은 달라질 수 있다. 이미 본 최종셋을 새 프롬프트 조정에 쓰면 독립 평가라고 부르지 않는다.

서비스 종료 후 볼륨·Airflow metadata·증거는 보존한다. Docker Desktop 자체는 다른 작업을 위해 종료하지 않는다.
