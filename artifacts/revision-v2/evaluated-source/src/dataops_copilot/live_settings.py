"""명시적으로 지정한 설정만 읽습니다. 사용자 홈/환경 비밀 파일을 탐색하지 않습니다."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator

from .models import Contract


class DBSettings(Contract):
    host: str = "127.0.0.1"
    port: int = Field(ge=1024, le=65535)
    dbname: str = "dataops_c_cp2"
    user: str
    password: SecretStr

    @field_validator("host")
    @classmethod
    def local_only(cls, value):
        if value != "127.0.0.1":
            raise ValueError("This development adapter is restricted to loopback")
        return value

    @field_validator("user", "dbname")
    @classmethod
    def isolated_reader(cls, value, info):
        expected = "dataops_observer" if info.field_name == "user" else "dataops_c_cp2"
        if value != expected:
            raise ValueError("Actual MCP settings must use the isolated demo read-only account/database")
        return value

    def connect_kwargs(self):
        return {**self.model_dump(exclude={"password"}), "password": self.password.get_secret_value(), "connect_timeout": 4}


class LiveSettings(Contract):
    airflow_url: str
    airflow_user: str
    airflow_password: SecretStr
    observer: DBSettings
    artifact_root: Path
    baseline_path: Path
    endpoint_path: Path

    @field_validator("airflow_url")
    @classmethod
    def local_api(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path != "/api/v1" or not parsed.port or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("Use explicit loopback Airflow 2.10.4 /api/v1 URL")
        return value

    @field_validator("airflow_user")
    @classmethod
    def viewer_only(cls, value):
        if value != "dataops_viewer":
            raise ValueError("MCP Airflow credentials must use the dedicated Viewer")
        return value

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(json.loads(path.read_text()))
