"""Scan tracked public files without printing any credential value. No network calls."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(rb'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,})\b')
KEY = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
TEST_FILES = {'tests/test_openai_safety.py', 'tests/test_revision_v2.py',
    'artifacts/revision-v2/evaluated-source/tests/test_openai_safety.py',
    'artifacts/revision-v2/evaluated-source/tests/test_revision_v2.py'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secret-env', type=Path, help='Optional explicit local env, used only for exact byte comparison')
    parser.add_argument('--credentials-json', type=Path, help='Optional explicit local credentials JSON; no values are printed')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    secrets = []
    if args.secret_env:
        for line in args.secret_env.read_text().splitlines():
            if line.startswith('OPENAI_API_KEY='):
                value = line.split('=', 1)[1].strip().strip('\"\'')
                if value:
                    secrets.append(value.encode())
    if args.credentials_json:
        secrets += [v.encode() for v in json.loads(args.credentials_json.read_text()).values() if isinstance(v, str) and len(v) > 12]
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    findings, dummy_count, checked = [], 0, 0
    for name in filter(None, names):
        path = ROOT / name
        if path.is_symlink():
            findings.append({'path': name, 'rule': 'symlink'}); continue
        if not path.is_file():
            continue
        checked += 1
        raw = path.read_bytes()
        if any(secret in raw for secret in secrets):
            findings.append({'path': name, 'rule': 'exact_local_secret'})
        if path.name in ('.env', 'openai.env', 'generated-credentials.json', 'secrets.toml') or '.sqlite' in name or path.suffix in ('.db', '.pem', '.key'):
            findings.append({'path': name, 'rule': 'credential_or_database_file'})
        if KEY.search(raw):
            findings.append({'path': name, 'rule': 'private_key'})
        for match in TOKEN.finditer(raw):
            if name in TEST_FILES and b'test' in match.group().lower():
                dummy_count += 1
            else:
                findings.append({'path': name, 'rule': 'credential_pattern', 'line': raw.count(b'\n', 0, match.start()) + 1})
    result = {'passed': not findings, 'tracked_files_checked': checked,
        'known_secret_values_checked': len(secrets), 'test_dummy_tokens_allowlisted': dummy_count,
        'findings': findings, 'provider_calls': 0}
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(bool(findings))


if __name__ == '__main__':
    main()
