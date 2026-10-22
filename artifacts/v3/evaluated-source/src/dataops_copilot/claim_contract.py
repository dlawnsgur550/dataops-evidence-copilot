"""Bounded claims: models select propositions; the application renders factual text."""
from typing import Literal
from pydantic import Field
from .models import Contract, Category


class ClaimProposal(Contract):
    category: Category
    evidence_ids: list[str] = Field(max_length=10)
    current_connection: Literal['unknown', 'connected', 'unavailable']
    artifact_coverage: Literal['unknown', 'complete', 'run_results_missing']
    config_error: Literal['unknown', 'wrong_port', 'wrong_host']
    business_equivalence: Literal['unknown', 'equivalent', 'different']
    propose_action: bool


class Finding(Contract):
    component: Literal['cause', 'observations', 'actions']
    rule_id: Literal['R00','R01','R02','R03','R04','R05','R06','R07','R08','R09','R10','R11','R12','R13','R14','R15','R16','R17']
    claim_id: Literal['category','evidence_ids','current_connection','artifact_coverage','config_error','business_equivalence','propose_action']


class ClaimReview(Contract):
    findings: list[Finding] = Field(max_length=8)
