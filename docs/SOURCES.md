# 구현 근거와 버전

확인일 2026-10-20. 실제 설치 버전은 `uv.lock`과 `artifacts/checkpoint4/app-versions.txt`로 고정한다. 공식 문서는 API 선택의 근거이며 동작 여부는 저장된 실행과 테스트로 구분한다.

| 대상 | 근거 |
| --- | --- |
| 실제 모델·구조화 출력 | [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) |
| 단가·낮은 우선순위 평가 | [Pricing](https://developers.openai.com/api/docs/pricing), [Flex processing](https://developers.openai.com/api/docs/guides/flex-processing) |
| 공개 임베딩 | [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small), [모델 논문](https://arxiv.org/abs/2402.05672) |
| 로컬 벡터 DB | [Qdrant Python client](https://python-client.qdrant.tech/quickstart) |
| 화면 상태·무료 다운로드 | [Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state), [download_button](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button) |
| 화면 자동 검사 | [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest) |
| 그래프와 MCP | [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [공식 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [FastMCP tools](https://gofastmcp.com/servers/tools) |

E5 모델 카드의 라이선스는 MIT다. 공식 ONNX qint8 가중치를 사용했고 revision·파일 SHA256·용량은 `deployment/embedding-model.json`에 있다. 가중치는 결과 ZIP에 넣지 않고 인증 없이 공개 파일을 다운로드하는 재현 스크립트를 제공한다. 원본 float 모델과의 성능 동등성을 별도로 평가하지 않았다.

런북 9개·합성 장애 기록 3개·평가 증거·정답은 이 작업에서 직접 작성했다. 실제 회사의 운영 문서·개인 주문 데이터는 사용하지 않았다. 공개 저장소나 외부 배포는 하지 않았으며 라이브러리 전체의 재배포 라이선스 검토를 완료했다고 주장하지 않는다. 과제 원본 PDF와 읽기 전용 원본 문서는 이 패키지에 추가 복제하지 않았다.
