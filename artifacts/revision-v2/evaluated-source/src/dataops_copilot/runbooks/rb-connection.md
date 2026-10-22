# dbt 실행 연결 거부 / connection refused

문서 ID: rb-connection
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
connection_refused, connection refused, dbt_orders, dbt_run, endpoint, host, port

## 확인과 원인 구분
실패 실행의 로그와 해당 dbt invocation 자료에서 실제 연결 ID를 확인한다. partial manifest만 있으면 검증된 명령 영수증과 누락 run_results를 명시한다.

## 사람의 조치
개발자가 실제 dbt 실행 설정과 서비스 상태·경로를 점검하고 확인된 설정 오류를 바로잡는다. 비밀번호는 보고서에 넣지 않는다.

## 선행 조건
실패 프로세스가 사용한 연결 설정을 먼저 확인한다. 포트가 로그에 없으면 잘못된 포트를 확정하지 않는다.

## 검증
새 실행의 모든 태스크와 두 품질 검사, 집계가 통과해야 한다. 현재 probe 성공이나 mcp_readonly 접속 성공만으로 복구라고 부르지 않는다.

## 적용 제외
다른 연결의 접속 성공은 dbt_orders 성공이 아니다. 현재 연결 성공은 과거 실행 실패를 지우지 않는다. 인증 오류·DNS 오류는 별도 런북을 확인한다.
