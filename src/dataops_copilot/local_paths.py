"""Portable public-release paths; never discover credentials above the checkout."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get('DATAOPS_WORK_DIR', str(ROOT / 'work'))).expanduser().resolve()
RUNTIME = WORK / 'runtime'
