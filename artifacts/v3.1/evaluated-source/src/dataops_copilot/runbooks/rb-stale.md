# 다른 실행 산출물 혼입 / stale invocation

문서 ID: rb-stale
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
invocation mismatch, manifest run_results, foreign run, try_number, content hash

## 확인과 원인 구분
run/task/try와 invocation ID, manifest·run_results의 해시와 명령 영수증을 대조한다.

## 사람의 조치
불일치 자료는 격리하고 선택 실행의 증거를 다시 수집한다. 자료가 없으면 원인 확정과 복구안을 보류한다.

## 선행 조건
불변 아카이브와 실행 식별자가 필요하다.

## 검증
새로 수집한 자료의 실행·시도·invocation과 해시가 모두 일치하는지 확인한다.

## 적용 제외
다른 실행의 성공이나 다른 시도의 실패를 선택 실행의 사실로 사용하지 않는다.
