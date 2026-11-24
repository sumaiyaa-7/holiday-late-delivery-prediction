"""One command: python run_all.py  (about a minute)."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
for step in ["generate_data", "validate_clean", "run_kpis", "promise_risk", "make_charts", "build_tracker"]:
    print(f"\n=== {step} ===")
    runpy.run_path(str(Path(__file__).parent / "src" / f"{step}.py"), run_name="__main__")
