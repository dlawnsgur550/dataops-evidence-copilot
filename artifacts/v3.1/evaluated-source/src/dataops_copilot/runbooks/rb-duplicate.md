# 중복 키 / unique violation

문서 ID: rb-duplicate
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
unique, duplicate_counts, duplicate order_id, dbt_test, primary key

## 확인과 원인 구분
선택 invocation에서 unique 검사가 실패했는지 확인하고 중복 그룹·원천 재적재 범위를 제한 조회한다. NULL 검사와 구분한다.

## 사람의 조치
업무상 중복 정의와 적재 멱등성을 개발자가 검토하고 승인된 중복 처리 정책을 적용한다. 원본을 보존한다.

## 선행 조건
유효한 최신 레코드 선택 기준과 중복 처리 승인이 필요하다.

## 검증
새 실행의 unique와 not_null, 원천 대비 건수·금액 정합성을 확인한다.

## 적용 제외
NULL만 있고 중복 수가 0이면 이 문서를 원인 근거로 삼지 않는다.
