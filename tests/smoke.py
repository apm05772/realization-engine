"""Run generic toy tests from the repository root using SageMath."""
from pathlib import Path
import runpy

root = Path(__file__).resolve().parents[1]
ns = runpy.run_path(str(root / "realization_engine_base.py"))
ns["rv_run_v3_tests"](level="full")
