from dataops_copilot.openai_llm import response_schema


def test_claim_ids_only_successful_evidence():
    s=response_schema('claims',{'evidence':[{'evidence_id':'good','status':'success'},{'evidence_id':'unavailable','status':'unavailable'},{'evidence_id':'empty','status':'empty'},{'evidence_id':'invalid','status':'invalid_input'}]})
    assert s['properties']['evidence_ids']['items']['enum']==['good']


def test_no_successful_evidence_forces_empty_citations():
    s=response_schema('claims',{'evidence':[{'evidence_id':'bad','status':'unavailable'}]})
    assert s['properties']['evidence_ids']['maxItems']==0
