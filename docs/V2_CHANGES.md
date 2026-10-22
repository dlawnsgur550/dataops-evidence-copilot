# v2 변경과 v2.1 보완 범위

v1은 `../dataops-copilot`에 보존했다. 이 디렉터리는 독립 수정본이며, 복사된 checkpoint 1~4 자료는 v1의 과거 증거다. 현재 수정·검증 결과는 `artifacts/revision-v2`와 이 문서, `V2_RESULTS.md`를 기준으로 읽는다. 발표자료는 만들지 않는다.

## 실제 변경

- Inspector를 이미 수집한 get_task_context를 제외한 네 도구와 최대 네 개의 서로 다른 선택으로 정리했다. 요청은 기존 strict JSON Schema를 계속 사용한다.
- 빈 응답·잘린 응답·거절·모호한 여러 출력·잘못된 JSON·금지 도구·중복 선택을 거절한다. 자동 수리·재시도는 없다. 메타데이터에는 역할·오류 코드·바이트 수·JSON 위치 또는 허용된 필드 위치·오류 유형만 남긴다. 잘못된 모델 응답 원문·서버 오류 본문은 보존하지 않는다. 임의 추가 필드 이름도 그대로 오류에 출력하지 않는다.
- RCA의 무조건적인 run_results 누락 명시 지시를 삭제했다. 누락 단정에는 검증된 partial receipt와 missing_artifacts의 명시적 run_results가 필요하다. 필드 부재·태스크 범위·dbt 명령별 검사 범위를 파일 누락과 구분한다.
- 코드 검토에도 관측된 한국어·영어 run_results 누락 단정 차단을 추가했다. 불확실성 표현은 단정과 구분한다. 제한된 문구 검출이며 가능한 모든 표현을 증명하는 의미 검증기가 아니다.
- 정상인 전체 실행 증거를 UNKNOWN으로 판정하면 코드 검토가 거절한다. 미래에 수행할 검증 제안을 이미 수행된 사실로 간주하지 않도록 Reviewer 지시를 보완했다.
- 검토에서 거절된 유효한 후보·위반·피드백은 비밀값을 제거해 Report.rejected_candidates에 따로 남긴다. 최종 diagnosis는 계속 UNKNOWN으로 보류한다. 진단·검토 결과와 출력 오류 메타데이터를 혼동하지 않는다.
- baseline은 다른 방식의 수집 성공 여부와 독립적으로 전체 고정 증거를 받도록 바꿨다. 비교용 Inspector는 평가 정책상 네 도구 전체를 선택하고, RCA 앞에서 다섯 관측이 있는지 검사한다. 제품의 선택적 수집 정책과 구분한다. 각 방식의 실제 근거 해시를 대조한다.

## 검증 구분

v2의 `artifacts/revision-v2/tests.xml`은 기존 86개와 새 21개, 합계 107개 테스트다. v2.1은 두 검사를 더해 `artifacts/revision-v2.1/tests.xml`의 109개가 통과했다. 새 검사는 잘못된 JSON·빈 출력·거절·출력 잘림·중복 도구와 금지 도구·근거 없는 누락 단정·정상/보류 구분·검토 거절 후보 보존·수집 실패에 독립적인 baseline 입력을 포함한다. HTTP 테스트는 MockTransport이며 실제 API 성능 평가가 아니다.

기존 dev 6건·이미 분석한 final 12건·새 사례 2건은 FakeLLM으로 무료 재생한다. 20건 통과는 계약과 제어 흐름 검증이며 모델 정확도 20/20이라는 뜻이 아니다. 저장된 실제 증거 기반 NEG 여섯 종류도 재검사한다.

유료 확인은 별도 사전 규칙 `evaluation/V2_PROTOCOL.md`에 따라 새로 직접 작성한 합성 사례 두 건만 사용한다. 코드·테스트·규칙·증거·정답을 호출 전에 고정하고 첫 결과를 보존한다. 모델은 gpt-6-luna, Flex, reasoning none을 유지한다. 정확도 개선·독립 사람 검토·원래 8/9 목표 달성을 이 작은 확인으로 주장하지 않는다.

v1의 실제 Airflow/Postgres/dbt 복구 3/3과 UI 증거를 보존했다. 이번에는 서비스를 기동하거나 실제 장애를 다시 주입하지 않았다. 이번 변경은 응답·진단 검토·평가 경로이며 새 실서비스 복구 결과는 없다.

## 재현

v2 폴더에서 `uv sync` 후 아래 명령을 실행한다. 무료 명령은 키가 필요 없다.

```sh
uv run pytest -q
uv run python scripts/run_v2_check.py --offline
uv run python scripts/verify_negatives.py
```

이미 저장된 유료 결과는 JSON으로 열람한다. 보존된 v2 유료 실행기는 별도 --api-settings를 요구하며 기존 `work/runtime/openai.env`와 같은 장부만 사용했다. v2.1 확인 실행기는 무료 전용이다. 최대 10회의 새 요청 창을 재개 시에도 보존하며, 기존 금액 상한을 높이거나 장부를 초기화하지 않는다. 현재 일반 유료 경로는 기존 요청 수 제한 때문에 차단된 상태다. 공용 키의 다른 사용자 지출은 이 로컬 장부가 통제하지 않는다.

## 공식 문서

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses): 엄격한 스키마와 거절·불완전 응답을 별도로 처리한다. 스키마가 사실의 정확성까지 보증하지는 않는다.
- [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing): 2026-10-20 재확인. 기존 Luna Standard/Flex 단가와 로컬 예산을 유지했다.

## v2.1의 추가 변경

v2 최초 결과를 확인한 뒤 별도 버전으로 분리했다. 연결 설정 오류가 확인된 경우에만 수정하고, 아니라면 변경하지 않는 조건을 명시했다. Reviewer에는 조건부 계획과 현재 설정 오류의 확정을 구분하도록 지시했다. 이후 유료 재호출은 없어서 실제 모델 효과는 미검증이다. 향후 baseline의 증거 배열 순서를 수집 순서와 맞추되 이미 저장한 v2 결과는 고치지 않았다. v2의 고정 소스는 evaluated-source에 보존했다.
