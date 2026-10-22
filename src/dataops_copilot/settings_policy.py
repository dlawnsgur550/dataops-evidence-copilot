"""Explicit allowlists. Identifiers are validated before composing read-only SQL."""
import json
import re
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from .models import Contract

ROOT = Path(__file__).resolve().parents[2]


class TargetPolicy(Contract):
    id: str
    dag_id: str
    table_id: str
    baseline_id: str
    quality_column: str
    schema_columns: list[str] = Field(min_length=1)
    connection_id: str
    tasks: list[str] = Field(min_length=1, max_length=100)
    required_tests: list[str] = Field(min_length=1)
    business_equivalence: str = 'unknown'
    business_contract_id: str | None = None
    max_profile_samples: int = Field(default=5, ge=0, le=5)

    @field_validator('table_id')
    @classmethod
    def table(cls, value):
        if not re.fullmatch(r'[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*',value):
            raise ValueError('INVALID_ALLOWLIST_TABLE')
        return value

    @field_validator('quality_column','dag_id','connection_id')
    @classmethod
    def identifier(cls,value):
        if not re.fullmatch(r'[a-z_][a-z0-9_]*',value):raise ValueError('INVALID_ALLOWLIST_IDENTIFIER')
        return value

    @field_validator('schema_columns','tasks','required_tests')
    @classmethod
    def identifiers(cls,values):
        if len(set(values))!=len(values) or any(not re.fullmatch(r'[a-z_][a-z0-9_]*',v) for v in values):
            raise ValueError('INVALID_ALLOWLIST_IDENTIFIERS')
        return values

    @model_validator(mode='after')
    def contract(self):
        if self.business_equivalence not in ('unknown','equivalent','different'):
            raise ValueError('INVALID_BUSINESS_EQUIVALENCE')
        if self.business_equivalence!='unknown' and not self.business_contract_id:
            raise ValueError('BUSINESS_CONTRACT_ID_REQUIRED')
        return self


class ProjectPolicy(Contract):
    version: str
    targets: list[TargetPolicy] = Field(min_length=1)

    @model_validator(mode='after')
    def distinct(self):
        if len({t.id for t in self.targets})!=len(self.targets) or len({(t.dag_id,t.table_id) for t in self.targets})!=len(self.targets):
            raise ValueError('DUPLICATE_ALLOWLIST_TARGET')
        return self

    def select(self,dag_id,table_id):
        matches=[t for t in self.targets if t.dag_id==dag_id and t.table_id==table_id]
        if len(matches)!=1:raise ValueError('TARGET_NOT_IN_PROJECT_ALLOWLIST')
        return matches[0]

    @classmethod
    def load(cls,path=None):
        return cls.model_validate(json.loads(Path(path or ROOT/'config/project.json').read_text()))
