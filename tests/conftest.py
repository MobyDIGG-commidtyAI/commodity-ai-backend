import os
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))
# Test-only export: a copy of the real price series (fair-value model tests) and a tiny synthetic assessment
# snapshot. The service itself ships no data; it reads the bucket export at DATA_DIR.
os.environ.setdefault("DATA_DIR", str(TESTS / "fixtures" / "export"))
