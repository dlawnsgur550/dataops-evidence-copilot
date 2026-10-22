# C의 실제 STEP 1 환경과 재현

2026-10-20의 실제 실행 결과입니다. 정상과 장애 3종의 실행·조회·개발자 조치·새 실행 검증은 실제이고 LLM은 결정적 fake입니다. 원본 PDR의 실제 LLM 기본 진단까지 완료한 것은 아닙니다.

## 환경과 시작

| 구성 | 검증한 환경 |
| --- | --- |
| 앱/MCP | 호스트 Python 3.11.15, `uv.lock` |
| Airflow | `apache/airflow:2.10.4-python3.11`, Python 3.11.11, 개발용 SQLite·SequentialExecutor, webserver+scheduler |
| API | `http://127.0.0.1:18783/api/v1`, Basic 인증, 별도 Admin/Viewer |
| dbt | `/opt/dataops-dbt` 가상환경, Core 1.9.10·postgres 1.9.1 |
| 개발자 드라이버 | `/opt/dataops-driver` 별도 가상환경, Pydantic 2.14.1·psycopg 3.3.6 |
| 업무 DB | `postgres:17.10-alpine`, 호스트 `127.0.0.1:15439`, DB `dataops_c_cp2` |
| 소유 컨테이너 | `dataops-c-cp2-postgres`, `dataops-c-cp2-airflow` |
| 소유 볼륨 | `dataops_c_cp2_pg17`, 중지 후 보존 |

이미지 digest와 ID는 `artifacts/checkpoint2/services.json`, 전체 의존성은 `deployment/*-resolved.txt`에 있습니다. 포트는 loopback에만 공개합니다. DB 개발자·dbt 빌더·관측자 역할을 분리하고 MCP 설정에는 관측자와 Airflow Viewer 자격만 넣습니다.

README의 절대 작업 디렉터리에서 `uv run python scripts/setup_local.py`와 `uv run python scripts/dev_services.py start`를 실행합니다. setup은 metadata 초기화에 사용하는 호스트 Airflow CLI 환경과 호스트 dbt 환경도 분리해 준비합니다. 실제 태스크는 Linux의 분리된 dbt 환경을 사용합니다. 첫 실행에는 이미지 다운로드·빌드가 필요하고 재시작은 캐시를 사용합니다.

새 비밀번호는 이 세션이 생성하여 `work/runtime/`의 권한 600 파일에 저장합니다. 사용자 비밀 파일·홈 설정은 탐색하지 않으며 생성 자격을 결과물에 복사하지 않습니다. 동명 컨테이너·볼륨이 소유 라벨을 갖지 않으면 중단합니다. 기존 사용자 DB나 볼륨을 삭제하지 않습니다.

macOS Airflow의 Gunicorn 작업자 SIGSEGV 때문에 공식 Linux 컨테이너로 옮겼습니다. 설치 버전과 v1 API를 유지했고 실패 로그는 보존했습니다. 네이티브 런타임의 성공을 주장하지 않습니다.

## 실제 파이프라인과 복구

`load_demo_data → dbt_run → dbt_test → publish_summary`입니다. 초기화·주입은 개발자 DAG 태스크가, 진단은 조회 전용 MCP가 담당합니다. 기준 스키마는 최초 정상 DB에서 실제 수집하고 이후 덮어쓰지 않습니다.

- 정상: 고정 시드 주문 1,000건과 모델 2개를 생성합니다. order_id not_null·unique와 원본/staging/일별 집계가 일치해야 publish_summary가 성공합니다.
- 스키마: load가 amount 대신 paid_amount를 생성합니다. dbt_run의 컬럼 부재를 확인하고 개발자 repair가 컬럼 계약을 맞춘 뒤 새 실행으로 검사합니다.
- 품질: 최초 3개 order_id에 NULL을 주입합니다. dbt_run 성공 후 not_null 실패를 확인하고 개발자가 합성 데이터의 시간 기반 매핑으로 원래 키를 복구한 뒤 새 실행으로 검사합니다.
- 연결: dbt용 active endpoint 포트만 미사용 포트로 변경합니다. Airflow API와 별도 MCP 관측 연결은 계속 동작합니다. 정상 포트로 되돌린 뒤 새 실행으로 검사합니다.

후속 실행의 `mode=verify` 적재 단계는 데이터와 설정을 초기화하지 않습니다. 복구 성공이 단순 초기화로 바뀌지 않습니다. repair는 사용자가 승인한 개발자 스크립트가 수행했으며 에이전트의 도구 호출이나 사람이 직접 편집한 시연은 아닙니다.

## 증거 연결

dbt 명령마다 run/task/try 해시와 새 call ID 아래 독립 target/log 경로를 사용합니다. dbt_run·dbt_test는 서로 덮어쓰지 않습니다. invocation·내용 해시·명령 로그 해시·실행 식별자를 대조하고 receipt로 보존합니다. 같은 태스크 시도에 호출이 여러 개면 임의로 최신 자료를 고르지 않고 거부합니다.

연결 실패는 manifest 생성 후 run_results 생성 전에 종료될 수 있습니다. `artifact_status=partial`, `missing_artifacts=[run_results]`를 기록합니다. manifest와 실제 JSON 명령 로그의 invocation·해시가 맞는지 검사하고 선택한 Airflow 실행의 연결 거부 로그와 함께 연결 실패까지만 판단합니다. 스키마·품질·정상 판정에는 완전한 산출물을 요구합니다.

Airflow 2.10.4 JSON 로그가 청크 표현 문자열로 반환되는 문제를 실제 소스로 확인했습니다. 같은 v1 API의 `Accept: text/plain`으로 조회하고 dbt JSON 메시지를 정규화합니다. 최대 200줄·40,000바이트와 잘림 표시를 강제합니다.

`check_connection(dbt_orders)`는 개발자 설정의 현재 endpoint를 읽기 계정으로 검사합니다. 실제 dbt 비밀번호로 로그인하는 검사가 아니며 실패 프로세스 설정·과거 연결·복구를 보장하지 않습니다. 컨테이너의 `host.docker.internal`과 호스트의 `127.0.0.1`은 같은 전용 공개 포트를 이용합니다.

## 검증 자료와 한계

`live_e2e.py`는 하나의 MCP 세션에서 실제 정상 1회·실패 3회·후속 3회를 검사했습니다. 분모는 실제 복구 3건이며 최종 평가셋 12건이나 LLM 성능 평가가 아닙니다. 각 후속 실행은 1,000건·502,360.39, NULL/중복 0개를 확인했습니다.

`live_limits.py`는 실제 8개 NULL 중 5개 샘플 반환·truncated를 확인하고 키를 복원했습니다. 별도 성공 실행의 230개 긴 로그로 40,000바이트 반환을 확인했습니다. `live_post_recovery.py`는 현재 endpoint 성공 후에도 과거 실패를 유지하고, 복구 대상이 mcp_readonly로 바뀌면 거절하는지 검사했습니다.

DB의 read-only 트랜잭션 설정을 해제해도 INSERT·UPDATE·CREATE는 권한 SQLSTATE 42501로 거부됐고, Airflow Viewer의 실행 요청은 403이었습니다. 실제 LLM·원격 서비스·외부 배포는 연결하지 않았습니다.

마지막에 `dev_services.py stop`으로 전용 서비스를 중지합니다. 이후 다시 start할 수 있으며 볼륨·metadata·증거는 유지됩니다.
