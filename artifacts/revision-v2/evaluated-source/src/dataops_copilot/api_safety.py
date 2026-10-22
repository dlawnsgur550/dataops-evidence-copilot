"""공유 키를 위한 로컬 비용 장부·비밀값 비노출 설정. 계정 전역 설정은 변경하지 않습니다."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr

MODEL = "gpt-6-luna"
PRICE_DATE = "2026-10-20"
# USD 1 = 1e9 나노달러. 입력은 cache-write 단가까지 보수적으로 예약합니다.
INPUT_NANO = 100
CACHED_NANO = 10
CACHE_WRITE_NANO = 125
OUTPUT_NANO = 500
DAY_CAP = 20_000_000
TOTAL_CAP = 50_000_000
DIAGNOSIS_CAP = 10_000_000
REQUEST_CAP = 5_000_000
MAX_DAY_CALLS, MAX_TOTAL_CALLS = 20, 50


class SafeAPIError(RuntimeError):
    """메시지에 서버 본문·키·헤더·프롬프트를 포함하지 않는 종료 사유."""


def read_api_settings(path: Path) -> tuple[SecretStr, str]:
    if path.is_symlink() or not path.is_file():
        raise SafeAPIError("API_SETTINGS_MUST_BE_EXPLICIT_REGULAR_FILE")
    path.chmod(0o600)
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            if "=" not in line:
                raise SafeAPIError("INVALID_API_SETTINGS")
            key, value = line.split("=", 1)
            if key.strip() not in ("OPENAI_API_KEY", "OPENAI_MODEL"):
                raise SafeAPIError("UNSUPPORTED_API_SETTING")
            values[key.strip()] = value.strip().strip("\"'")
    key = values.get("OPENAI_API_KEY", "")
    if not key or any(c.isspace() for c in key):
        raise SafeAPIError("OPENAI_API_KEY_NOT_CONFIGURED")
    model = values.get("OPENAI_MODEL") or MODEL
    if model != MODEL:
        raise SafeAPIError("MODEL_NOT_IN_LOW_COST_ALLOWLIST")
    return SecretStr(key), model


class CostLedger:
    """SQLite BEGIN IMMEDIATE로 프로세스 간 예산 선예약. 불명확한 청구는 예약액 유지."""

    def __init__(self, path: Path, *, purpose="standard"):
        if purpose not in ("standard", "evaluation"):
            raise SafeAPIError("UNKNOWN_BUDGET_PROFILE")
        self.max_day_calls, self.max_total_calls = (96, 128) if purpose == "evaluation" else (MAX_DAY_CALLS, MAX_TOTAL_CALLS)
        self.purpose = purpose
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise SafeAPIError("UNSAFE_LEDGER_PATH")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, day TEXT NOT NULL, diagnosis TEXT NOT NULL, role TEXT NOT NULL, reserved INTEGER NOT NULL, charge INTEGER NOT NULL, status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER)")
            if "tier" not in {row[1] for row in conn.execute("PRAGMA table_info(requests)")}:
                conn.execute("ALTER TABLE requests ADD COLUMN tier TEXT NOT NULL DEFAULT 'default'")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def reserve(self, diagnosis: str, role: str, nano: int) -> str:
        if not 0 < nano <= REQUEST_CAP:
            raise SafeAPIError("API_REQUEST_COST_CAP")
        day = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            total, total_calls = conn.execute("SELECT coalesce(sum(charge),0), count(*) FROM requests").fetchone()
            if conn.execute("SELECT count(*) FROM requests WHERE status='reservation_exceeded'").fetchone()[0]:
                raise SafeAPIError("API_BILLING_CIRCUIT_BREAKER")
            daily, daily_calls = conn.execute("SELECT coalesce(sum(charge),0), count(*) FROM requests WHERE day=?", (day,)).fetchone()
            diag, diag_calls = conn.execute("SELECT coalesce(sum(charge),0),count(*) FROM requests WHERE diagnosis=?", (diagnosis,)).fetchone()
            if diag_calls >= 4:
                raise SafeAPIError("API_DIAGNOSIS_FOUR_CALL_CAP")
            if total + nano > TOTAL_CAP or total_calls >= self.max_total_calls:
                raise SafeAPIError("API_PROJECT_LIFETIME_CAP")
            if daily + nano > DAY_CAP or daily_calls >= self.max_day_calls:
                raise SafeAPIError("API_PROJECT_DAILY_CAP")
            if diag + nano > DIAGNOSIS_CAP:
                raise SafeAPIError("API_DIAGNOSIS_COST_CAP")
            rid = uuid.uuid4().hex
            conn.execute("INSERT INTO requests (id,day,diagnosis,role,reserved,charge,status,input_tokens,output_tokens) VALUES (?,?,?,?,?,?,?,NULL,NULL)", (rid, day, diagnosis, role, nano, nano, "reserved"))
            return rid

    def settle(self, rid: str, usage: dict, *, service_tier="default") -> tuple[int, int, int]:
        if service_tier not in ("default","flex"):
            raise SafeAPIError("OPENAI_SERVICE_TIER_UNVERIFIED_RESERVATION_RETAINED")
        try:
            input_tokens, output_tokens = usage["input_tokens"], usage["output_tokens"]
            cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
            written = (usage.get("input_tokens_details") or {}).get("cache_write_tokens", 0)
            if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (input_tokens, output_tokens, cached, written)) or cached + written > input_tokens:
                raise ValueError()
            nano = (input_tokens - cached - written) * INPUT_NANO + cached * CACHED_NANO + written * CACHE_WRITE_NANO + output_tokens * OUTPUT_NANO
            if service_tier == "flex":
                nano = (nano + 1) // 2  # official Flex/Batch price; round up at most 0.5 nano-USD
        except (ValueError, TypeError, KeyError):
            raise SafeAPIError("OPENAI_USAGE_MISSING_RESERVATION_RETAINED") from None
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            reserved = conn.execute("SELECT reserved FROM requests WHERE id=?", (rid,)).fetchone()[0]
            conn.execute("UPDATE requests SET charge=?,status=?,input_tokens=?,output_tokens=?,tier=? WHERE id=?", (nano, "billed" if nano <= reserved else "reservation_exceeded", input_tokens, output_tokens, service_tier, rid))
        if nano > reserved:
            raise SafeAPIError("OPENAI_USAGE_EXCEEDED_CONSERVATIVE_RESERVATION")
        return input_tokens, output_tokens, nano

    def summary(self):
        with self.connect() as conn:
            count, charge = conn.execute("SELECT count(*),coalesce(sum(charge),0) FROM requests").fetchone()
            uncertain = conn.execute("SELECT count(*) FROM requests WHERE status='reserved'").fetchone()[0]
        return {"requests": count, "spent_or_reserved_usd": charge / 1e9, "uncertain_requests": uncertain,
                "lifetime_cap_usd": TOTAL_CAP / 1e9, "daily_cap_usd": DAY_CAP / 1e9, "diagnosis_cap_usd": DIAGNOSIS_CAP / 1e9, "day_timezone": "Asia/Seoul", "profile": self.purpose, "daily_call_cap": self.max_day_calls, "total_call_cap": self.max_total_calls}

    def uncertain_usd(self, diagnosis):
        with self.connect() as conn:
            return conn.execute("SELECT coalesce(sum(charge),0) FROM requests WHERE diagnosis=? AND status='reserved'", (diagnosis,)).fetchone()[0] / 1e9
