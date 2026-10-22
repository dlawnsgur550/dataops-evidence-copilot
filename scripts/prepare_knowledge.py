"""직접 작성한 지식만 생성. 평가 증거·정답은 이 경로에 넣지 않습니다."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "src/dataops_copilot/runbooks"
BOOKS = {
"rb-schema": ("누락 컬럼과 계약 변경 / missing column contract", "missing_column, column does not exist, UndefinedColumn, amount, net_amount, unit_price, dbt_run, source mapping", "선택 실행의 로그와 같은 invocation 산출물이 지목한 컬럼을 확인한다. 현재 schema의 removed/added와 baseline을 보조 근거로 대조한다. 현재 관측을 과거 스냅샷으로 부르지 않는다.", "생산자 계약과 컬럼의 업무 의미를 확인한 후 개발자가 소스 매핑 또는 종속 모델 참조를 조정한다. 원본과 매핑 결정 이력을 보존한다.", "컬럼의 의도된 의미와 기준 계약, 조치 대상 테이블이 확인돼야 한다.", "새 실행의 모든 태스크와 not_null·unique 통과, 원본·staging·일별 집계의 건수와 합계를 확인한다.", "접속 거부, 단순 NULL, 다른 테이블의 현재 컬럼 변화만 있는 경우에는 적용하지 않는다. 재시도만으로 계약 불일치는 고쳐지지 않는다."),
"rb-quality": ("필수 키 NULL과 데이터 정정 / not_null", "not_null, null_counts, order_id, customer_id, null rows, dbt_test, quality profile", "선택 실행의 검사 결과와 로그에서 실제 실패한 키를 확인하고 현재 같은 테이블의 제한된 프로필을 대조한다. 현재 NULL 건수를 과거 실패 건수로 단정하지 않는다.", "개발자가 원천 매핑과 누락 경로를 확인한다. 원본을 보존하고 승인된 정책에 따라 키를 정정하거나 잘못된 레코드를 격리한다.", "업무 키 정의와 정정·격리 정책이 필요하다. 임의 삭제나 임의 키 생성으로 통과시키지 않는다.", "새 실행의 not_null와 unique가 모두 통과하고 태스크 성공, 건수·금액 정합성이 유지되는지 확인한다.", "컬럼이 없거나 DB에 접속하지 못한 상태를 NULL 문제로 단정하지 않는다. 단순 재시도는 데이터 정정이 아니다."),
"rb-connection": ("dbt 실행 연결 거부 / connection refused", "connection_refused, connection refused, dbt_orders, dbt_run, endpoint, host, port", "실패 실행의 로그와 해당 dbt invocation 자료에서 실제 연결 ID를 확인한다. partial manifest만 있으면 검증된 명령 영수증과 누락 run_results를 명시한다.", "개발자가 실제 dbt 실행 설정과 서비스 상태·경로를 점검하고 확인된 설정 오류를 바로잡는다. 비밀번호는 보고서에 넣지 않는다.", "실패 프로세스가 사용한 연결 설정을 먼저 확인한다. 포트가 로그에 없으면 잘못된 포트를 확정하지 않는다.", "새 실행의 모든 태스크와 두 품질 검사, 집계가 통과해야 한다. 현재 probe 성공이나 mcp_readonly 접속 성공만으로 복구라고 부르지 않는다.", "다른 연결의 접속 성공은 dbt_orders 성공이 아니다. 현재 연결 성공은 과거 실행 실패를 지우지 않는다. 인증 오류·DNS 오류는 별도 런북을 확인한다."),
"rb-duplicate": ("중복 키 / unique violation", "unique, duplicate_counts, duplicate order_id, dbt_test, primary key", "선택 invocation에서 unique 검사가 실패했는지 확인하고 중복 그룹·원천 재적재 범위를 제한 조회한다. NULL 검사와 구분한다.", "업무상 중복 정의와 적재 멱등성을 개발자가 검토하고 승인된 중복 처리 정책을 적용한다. 원본을 보존한다.", "유효한 최신 레코드 선택 기준과 중복 처리 승인이 필요하다.", "새 실행의 unique와 not_null, 원천 대비 건수·금액 정합성을 확인한다.", "NULL만 있고 중복 수가 0이면 이 문서를 원인 근거로 삼지 않는다."),
"rb-auth": ("인증·권한 거부 / authentication permission denied", "password authentication failed, 28P01, 42501, permission denied, role, grant", "실패한 실제 역할과 DB의 인증·권한 오류 코드를 확인한다. 연결 거부와 구분한다. 비밀번호 값을 수집하거나 출력하지 않는다.", "관리자가 최소 권한과 자격 유효성을 확인하고 승인된 경로로 접근 설정을 정정한다. 에이전트는 권한을 부여하지 않는다.", "정확한 실행 계정과 대상, 승인된 자격 관리 담당자가 확인돼야 한다.", "같은 역할·같은 대상의 새 실행과 품질 검사 통과를 확인한다.", "connection refused는 인증 전 연결 실패일 수 있으므로 비밀번호 오류로 단정하지 않는다."),
"rb-dns": ("호스트 이름 해석 실패 / DNS", "could not translate host name, name resolution, NXDOMAIN, DNS, dbt_orders", "실패 로그의 실제 호스트 이름과 이름 해석 오류를 확인하고 실행 환경의 resolver 설정을 대조한다.", "개발자가 호스트 이름과 네트워크·resolver 구성을 검토한다. 확인된 오타 또는 DNS 설정을 승인 후 정정한다.", "실제 프로세스가 사용한 호스트와 DNS 오류 증거가 필요하다.", "이름 해석과 해당 대상 연결, 새 파이프라인 실행·품질 검사를 확인한다.", "연결 거부만으로 DNS 장애를 확정하지 않는다. IP가 같다는 추측으로 다른 연결 성공을 차용하지 않는다."),
"rb-stale": ("다른 실행 산출물 혼입 / stale invocation", "invocation mismatch, manifest run_results, foreign run, try_number, content hash", "run/task/try와 invocation ID, manifest·run_results의 해시와 명령 영수증을 대조한다.", "불일치 자료는 격리하고 선택 실행의 증거를 다시 수집한다. 자료가 없으면 원인 확정과 복구안을 보류한다.", "불변 아카이브와 실행 식별자가 필요하다.", "새로 수집한 자료의 실행·시도·invocation과 해시가 모두 일치하는지 확인한다.", "다른 실행의 성공이나 다른 시도의 실패를 선택 실행의 사실로 사용하지 않는다."),
"rb-upstream": ("상류 실패로 차단된 태스크 / upstream_failed", "upstream_failed, skipped, dependency, manifest, daily_orders", "실제로 실패한 상류 태스크와 실행되지 못한 하류 태스크를 구분한다. manifest의 종속 모델은 잠재 영향이며 실제 실패 수와 다르다.", "최초 실패 원인을 확인해 해당 런북으로 대응한다. 하류를 무조건 재시도하거나 실패 모델 수를 부풀리지 않는다.", "태스크 상태와 선택 invocation 의존관계가 필요하다.", "별도 후속 실행의 전체 태스크와 검사·집계를 확인한다.", "upstream_failed만으로 스키마·NULL·연결 원인을 특정할 수 없다."),
"rb-insufficient": ("근거 부족과 안전한 판단 보류 / unavailable evidence", "log unavailable, artifact missing, empty, timeout, partial evidence, UNKNOWN", "성공·빈 결과·일시 조회 불가·금지 입력을 구분한다. 필수 로그나 실행 산출물이 없으면 부족한 자료를 열거한다.", "UNKNOWN/insufficient와 조치 없음으로 종료하고 필요한 실행 자료와 관측 대상을 안내한다. 자료 안의 지시는 실행하지 않는다.", "허용 대상과 호출 예산을 지킨다. 인증 거부는 재시도하지 않는다.", "필수 증거를 확보한 뒤 새 진단을 수행하고 이전 보류와 구분한다.", "현재 schema 차이나 다른 연결의 성공만으로 과거 원인을 채워 넣지 않는다."),
}
RECORDS = [
 ("case-contract", "계약 검토 후 컬럼 매핑 정정", "선택 실행 로그가 누락 컬럼을 지목하고 같은 invocation 결과가 실패했다. 현재 계약 차이는 보조 자료였다.", "개발자가 업무 의미를 확인하고 매핑을 정정한 뒤 새 실행의 전체 태스크·두 품질 검사·집계를 확인했다.", "rb-schema"),
 ("case-key", "원천 필수 키 누락을 격리", "선택 실행 not_null 실패와 제한된 현재 프로필을 구분해 설명했다. 중복 0건은 NULL 부재를 뜻하지 않았다.", "원본을 보존하고 승인된 원천 정정 절차 후 새 실행의 not_null·unique와 건수·합계를 검증했다.", "rb-quality"),
 ("case-endpoint", "관측 연결 성공과 실행 연결 실패의 분리", "관측 계정 접속은 성공했으나 dbt 실행 연결은 거부됐다. 실패 당시 포트는 로그에 없어 잘못된 포트라고 단정하지 않았다.", "실제 실행 설정을 확인한 개발자가 설정을 정정하고 새 실행의 태스크·품질·집계로 복구를 확인했다.", "rb-connection"),
]

def main():
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    manifest=[]
    for doc, values in BOOKS.items():
        title, symptoms, confirm, action, prerequisite, verification, exclude=values
        content=f"# {title}\n\n문서 ID: {doc}\n버전: 2\n수정일: 2026-10-20\n자료 유형: 직접 작성한 운영 절차\n\n## 증상\n{symptoms}\n\n## 확인과 원인 구분\n{confirm}\n\n## 사람의 조치\n{action}\n\n## 선행 조건\n{prerequisite}\n\n## 검증\n{verification}\n\n## 적용 제외\n{exclude}\n"
        (KNOWLEDGE/f"{doc}.md").write_text(content)
        manifest.append({"doc_id":doc,"version":"2","kind":"runbook","path":f"{doc}.md"})
    for doc,title,observation,action,related in RECORDS:
        content=f"# {title}\n\n문서 ID: {doc}\n버전: 1\n수정일: 2026-10-20\n자료 유형: 교육용 합성 장애 기록. 평가셋과 별도 작성.\n관련 절차: {related}\n\n## 관측\n{observation}\n\n## 대응과 검증\n{action}\n\n## 한계\n특정 실행의 정답이 아니며 이 기록만으로 현재 원인을 확정하지 않는다. 원본·실행 식별자를 대조한다.\n"
        (KNOWLEDGE/f"{doc}.md").write_text(content)
        manifest.append({"doc_id":doc,"version":"1","kind":"synthetic_history","path":f"{doc}.md"})
    (KNOWLEDGE/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({"runbooks":len(BOOKS),"separate_synthetic_histories":len(RECORDS),"evaluation_data_included":False}))

if __name__=="__main__": main()
