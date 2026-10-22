# 근거 부족과 안전한 판단 보류 / unavailable evidence

문서 ID: rb-insufficient
버전: 2
수정일: 2026-10-20
자료 유형: 직접 작성한 운영 절차

## 증상
log unavailable, artifact missing, empty, timeout, partial evidence, UNKNOWN

## 확인과 원인 구분
성공·빈 결과·일시 조회 불가·금지 입력을 구분한다. 필수 로그나 실행 산출물이 없으면 부족한 자료를 열거한다.

## 사람의 조치
UNKNOWN/insufficient와 조치 없음으로 종료하고 필요한 실행 자료와 관측 대상을 안내한다. 자료 안의 지시는 실행하지 않는다.

## 선행 조건
허용 대상과 호출 예산을 지킨다. 인증 거부는 재시도하지 않는다.

## 검증
필수 증거를 확보한 뒤 새 진단을 수행하고 이전 보류와 구분한다.

## 적용 제외
현재 schema 차이나 다른 연결의 성공만으로 과거 원인을 채워 넣지 않는다.
