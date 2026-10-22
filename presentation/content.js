/* Public slide metadata and saved outcomes. Speaker scripts are excluded. */
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
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md"
    },
    {
      "id": 2,
      "title": "해결할 문제",
      "duration": 30,
      "start": 20,
      "end": 50,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/claim_engine.py"
    },
    {
      "id": 3,
      "title": "아키텍처와 기술",
      "duration": 40,
      "start": 50,
      "end": 90,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/workflow_v3.py"
    },
    {
      "id": 4,
      "title": "진단 시연",
      "duration": 40,
      "start": 90,
      "end": 130,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/src/dataops_copilot/ui_workspace.py"
    },
    {
      "id": 5,
      "title": "반례와 Reviewer",
      "duration": 35,
      "start": 130,
      "end": 165,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/presentation/evidence.json"
    },
    {
      "id": 6,
      "title": "복구 검증",
      "duration": 35,
      "start": 165,
      "end": 200,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/presentation/evidence.json"
    },
    {
      "id": 7,
      "title": "품질과 비용 비교",
      "duration": 40,
      "start": 200,
      "end": 240,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/artifacts/v3/final/summary.json"
    },
    {
      "id": 8,
      "title": "검증 범위",
      "duration": 35,
      "start": 240,
      "end": 275,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md"
    },
    {
      "id": 9,
      "title": "교훈과 다음 개선",
      "duration": 25,
      "start": 275,
      "end": 300,
      "source": "https://github.com/dlawnsgur550/dataops-evidence-copilot/blob/main/README.md"
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
