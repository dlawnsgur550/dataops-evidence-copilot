# 누락 컬럼과 계약 변경 / missing column contract

문서 ID: rb-schema
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
missing_column, column does not exist, UndefinedColumn, amount, net_amount, unit_price, dbt_run, source mapping

## 확인과 원인 구분
선택 실행의 로그와 같은 invocation 산출물이 지목한 컬럼을 확인한다. 현재 schema의 removed/added와 baseline을 보조 근거로 대조한다. 현재 관측을 과거 스냅샷으로 부르지 않는다.

## 사람의 조치
생산자 계약과 컬럼의 업무 의미를 확인한 후 개발자가 소스 매핑 또는 종속 모델 참조를 조정한다. 원본과 매핑 결정 이력을 보존한다.

## 선행 조건
컬럼의 의도된 의미와 기준 계약, 조치 대상 테이블이 확인돼야 한다.

## 검증
새 실행의 모든 태스크와 not_null·unique 통과, 원본·staging·일별 집계의 건수와 합계를 확인한다.

## 적용 제외
접속 거부, 단순 NULL, 다른 테이블의 현재 컬럼 변화만 있는 경우에는 적용하지 않는다. 재시도만으로 계약 불일치는 고쳐지지 않는다.
