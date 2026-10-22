"""Launch or reuse the single local workspace; never read provider credentials."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def healthy(url):
    try:
        with urllib.request.urlopen(url + '/_stcore/health', timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18784)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('invalid local port')
    url = f'http://127.0.0.1:{args.port}'
    if healthy(url):
        print('이미 실행 중인 기본 웹: ' + url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    child = subprocess.Popen([sys.executable, '-m', 'dataops_copilot.web_server',
        '--port', str(args.port)], cwd=ROOT,
        env={**os.environ, 'PYTHONPATH': str(ROOT/'src')})
    try:
        for _ in range(60):
            if child.poll() is not None:
                return child.returncode
            if healthy(url):
                print('기본 웹: ' + url, flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                break
            time.sleep(.2)
        else:
            raise RuntimeError('WORKSPACE_START_TIMEOUT')
        return child.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)


if __name__ == '__main__':
    raise SystemExit(main())
