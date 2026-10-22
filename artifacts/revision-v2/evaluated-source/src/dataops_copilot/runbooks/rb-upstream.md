# 상류 실패로 차단된 태스크 / upstream_failed

문서 ID: rb-upstream
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
upstream_failed, skipped, dependency, manifest, daily_orders

## 확인과 원인 구분
실제로 실패한 상류 태스크와 실행되지 못한 하류 태스크를 구분한다. manifest의 종속 모델은 잠재 영향이며 실제 실패 수와 다르다.

## 사람의 조치
최초 실패 원인을 확인해 해당 런북으로 대응한다. 하류를 무조건 재시도하거나 실패 모델 수를 부풀리지 않는다.

## 선행 조건
태스크 상태와 선택 invocation 의존관계가 필요하다.

## 검증
별도 후속 실행의 전체 태스크와 검사·집계를 확인한다.

## 적용 제외
upstream_failed만으로 스키마·NULL·연결 원인을 특정할 수 없다.
