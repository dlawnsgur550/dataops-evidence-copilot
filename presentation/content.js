/* Authoring source for slide timing, speaker notes and saved outcomes. No API calls. */
window.DECK = {
  "title": "DataOps Evidence Copilot",
  "author": "임준혁",
  "total": 300,
  "slides": [
    {
      "id": 1,
      "title": "프로젝트 소개",
      "duration": 20,
      "start": 0,
      "end": 20,
      "cue": "표지를 보며 소개. 제품 화면은 실제 구현한 웹 캡처입니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md",
      "notes": "안녕하세요. SKALA 임준혁입니다. 제가 만든 DataOps Evidence Copilot은 데이터 파이프라인 장애를 진단하는 읽기 전용 도구입니다. 핵심은 모델이 그럴듯하게 설명하는 데서 끝내지 않고, 어느 실행의 어떤 근거로 판단했는지 코드로 검증하는 것입니다. 지금부터 문제, 동작 방식, 검증 결과와 한계를 설명드리겠습니다."
    },
    {
      "id": 2,
      "title": "해결할 문제",
      "duration": 30,
      "start": 20,
      "end": 50,
      "cue": "왼쪽 실패 로그와 오른쪽 이후 관측을 차례로 가리킵니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/claim_engine.py",
      "notes": "먼저 연결 실패를 예로 보겠습니다. 실행 당시 로그에는 연결 거부가 남아 있지만, 나중에 확인한 연결 상태는 성공일 수 있습니다. 이때 현재 연결이 된다는 이유로 과거 장애가 없었다고 하거나, 전체 복구가 끝났다고 판단하면 안 됩니다. 또 연결 거부만으로 포트가 틀렸다고 단정할 수도 없습니다. 그래서 실행 ID, 대상, 관측 시점을 묶어 검사하고, 확인되지 않은 원인과 설정 변경은 보류하도록 개선했습니다."
    },
    {
      "id": 3,
      "title": "아키텍처와 기술",
      "duration": 40,
      "start": 50,
      "end": 90,
      "cue": "근거 수집 → 주장 → 규칙 → 결과 순서로 짚습니다. 확장 기능은 아래 행에서 설명합니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/workflow_v3.py",
      "notes": "현재 기본 경로는 네 단계입니다. 먼저 읽기 전용 도구 다섯 종류로 근거를 모으거나 저장 근거를 재생합니다. Proposer는 원인, 근거 ID, 조치를 정해진 구조로 제안합니다. 이후 R00부터 R17까지 코드 규칙이 실행과 대상의 일치, 관측 범위, 조치 조건을 검사하고, 통과한 주장만 문장으로 만듭니다. 확장 구성에는 로컬 E5와 Qdrant, BM25와 RRF 검색, 반례를 만드는 Reviewer를 추가했습니다. LangGraph는 초기 경로에 구현했고, 현재 기본 웹은 비용과 판정 통제를 위해 순차 실행합니다. 오늘 무료 시연의 실제 API 호출은 없습니다."
    },
    {
      "id": 4,
      "title": "진단 시연",
      "duration": 40,
      "start": 90,
      "end": 130,
      "cue": "4장의 '기본 웹 열기' 선택 → 연결 실패 → 저장 근거로 재진단 → 진단 실행 → 실행 로그 근거 ID. 20초 안에 복귀합니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/ui_workspace.py",
      "notes": "이제 연결 실패 사례입니다. 적재는 성공했지만 모델 변환이 실패해 뒤의 품질 검사와 발행이 차단됐습니다. 기본 웹에서 저장 근거로 재진단하고 근거 ID를 누르면, 해당 실행의 원본 로그와 관측 범위를 확인할 수 있습니다. 실행 당시 자료와 이후에 수집한 관측은 구분해서 표시합니다. 담당자 절차도 설정 오류가 확인되면 그 오류만 수정하고, 확인되지 않으면 설정을 유지하며 추가 근거를 모으도록 제시합니다. 다른 실행의 자료가 들어오면 판단을 보류합니다."
    },
    {
      "id": 5,
      "title": "반례와 Reviewer",
      "duration": 35,
      "start": 130,
      "end": 165,
      "cue": "'포트 오류 단정' → '과잉 거절'을 차례로 누릅니다. 저장된 실제 코드 검사 결과입니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/presentation/evidence.json",
      "notes": "안전성은 반례로 보여드리겠습니다. 없는 근거 ID를 인용하면 R02가 차단합니다. 포트 오류를 근거 없이 단정하면 R05가 해당 주장을 거절합니다. 반대로 Reviewer가 올바른 조건부 조치까지 거절한다면, 그 반례가 실제 코드 위반인지 다시 대조합니다. 위반 근거가 없는 거절은 기록하고 검증된 진단을 유지합니다. 지금 보시는 것은 의도적으로 만든 반례를 실제 코드로 검사한 저장 결과이며, 모델이 새로 답변한 결과는 아닙니다."
    },
    {
      "id": 6,
      "title": "복구 검증",
      "duration": 35,
      "start": 165,
      "end": 200,
      "cue": "'새 실행 기록' 통과 확인 → '같은 실행 반례' 선택. 원본 근거 행 수와 합계를 가리킵니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/presentation/evidence.json",
      "notes": "복구 판정은 더 엄격하게 분리했습니다. 담당자가 수정한 뒤 별도의 새 실행이 있어야 하고, 전체 태스크와 필수 품질 검사, 원본부터 최종 집계까지 일치해야 합니다. 여기서는 각 단계가 십만 행이며 합계도 같습니다. 하지만 같은 실패 실행을 후속 실행으로 제출하면, 성공 태스크 값이 있어도 복구로 인정하지 않습니다. 이 화면 역시 실제 로컬 서비스에서 수집한 합성 데이터의 저장 기록을 다시 확인하는 것이며, 발표 중 설정을 바꾸거나 서비스를 재실행하지 않습니다."
    },
    {
      "id": 7,
      "title": "품질과 비용 비교",
      "duration": 40,
      "start": 200,
      "end": 240,
      "cue": "8/10 두 값을 짚고, 비용 막대와 평균 시간을 설명합니다. 수치를 모두 읽기보다 차이를 말합니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/artifacts/v3/final/summary.json",
      "notes": "추가 모델 단계가 비용만큼 도움이 되는지도 비교했습니다. 같은 Luna 모델과 직접 만든 합성 사례 열 건에서 기본 구성과 검색·Reviewer 추가 구성 모두 진단과 조치 기준 여덟 건을 통과했습니다. 추정 API 비용은 열 건 기준 약 영점영영일이 달러와 영점영영삼이 달러였고, 평균 시간은 약 사 초와 십일 초였습니다. 이 작은 실험에서는 품질 이득이 없어 기본 구성을 선택했습니다. 다만 같은 열 건을 선택과 평가에 함께 사용했기 때문에, 운영 정확도나 RAG만의 효과를 입증한 결과로 해석하지 않았습니다."
    },
    {
      "id": 8,
      "title": "검증 범위",
      "duration": 35,
      "start": 240,
      "end": 275,
      "cue": "각 행의 데이터·모델 범위를 함께 짚습니다. 212개와 10건을 하나의 정확도로 합치지 않습니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md",
      "notes": "테스트 규모도 구분해서 보겠습니다. 코드와 통합 검사는 이백십이 개를 통과했고, 규칙 반례는 열 가지 의미 유형을 변형한 만 개를 검사했습니다. 실제 로컬 Airflow, PostgreSQL, dbt에서는 합성 데이터 십만 행으로 일곱 번 실행했고, 별도 새 실행 복구 세 건을 확인했습니다. 이 서비스 실험의 모델은 FakeLLM입니다. 실제 모델 평가는 앞의 고정 합성 열 건으로 작은 표본이고, 수정 후 추가 두 건도 기준별 결과를 분리했습니다. 따라서 테스트 수가 많다는 이유로 현업 정확도가 검증됐다고 주장하지 않습니다."
    },
    {
      "id": 9,
      "title": "교훈과 다음 개선",
      "duration": 25,
      "start": 275,
      "end": 300,
      "cue": "마지막 장표에서 멈춥니다. 공개 README 링크를 안내하고 마무리합니다.",
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md",
      "notes": "이번 구현에서 얻은 교훈은 설명을 늘리는 것보다 검증 가능한 주장과 근거 연결이 중요하다는 점입니다. 다음에는 새로운 독립 평가 자료와 실제 담당자의 검토, 승인된 업무 계약을 확보하겠습니다. LangSmith 외부 추적과 독립 LLM Judge도 아직 적용하지 않은 개선 과제로 남겼습니다. 최종 보고서와 실행 코드, 원본 검증 기록은 공개 GitHub에 정리했습니다. 감사합니다."
    }
  ],
  "guards": {
    "fake_evidence": {
      "input": "존재하지 않는 근거를 인용",
      "code": "evidence_ids += ev-workspace-nonexistent",
      "verdict": "R02 · 근거 인용 거절",
      "detail": "성공하고 실행·대상이 일치하는 근거만 인용합니다.",
      "tone": "fail"
    },
    "wrong_port": {
      "input": "연결 거부를 포트 오류로 단정",
      "code": "config_error = wrong_port",
      "verdict": "R05 · 포트 오류 주장 거절",
      "detail": "연결 거부만으로 설정 오류를 확정하지 않습니다.",
      "tone": "fail"
    },
    "reviewer_rejection": {
      "input": "검증된 조건부 조치까지 거절",
      "code": "Reviewer: R06 / propose_action",
      "verdict": "거절 근거 불충분",
      "detail": "실제 코드 위반 없음 · 검증된 원인과 조건부 조치를 유지합니다.",
      "tone": "pass"
    }
  },
  "recovery": {
    "new_run": {
      "verdict": "새 실행 · 복구 확인",
      "detail": "R10 통과 · 전체 태스크·검사·집계 일치",
      "tone": "pass"
    },
    "same_run": {
      "verdict": "같은 실행 · 복구 거절",
      "detail": "R10 거절 · 새 실행·근거·집계의 실행 연결 불일치",
      "tone": "fail"
    }
  }
};
