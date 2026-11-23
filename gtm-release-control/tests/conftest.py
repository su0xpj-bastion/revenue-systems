import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "classifier", "gate", "evidence", "metrics", "ci"):
    sys.path.insert(0, str(ROOT / sub))
