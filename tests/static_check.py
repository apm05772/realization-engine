"""Public distribution integrity/syntax checks; no SageMath required."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
code = root / "realization_engine_base.py"
satellites = sorted((root / "satellites").glob("rv_satellite_*.py"))
assert len(satellites) == 7, "Unexpected satellite module inventory"
for path in [code, *satellites, root / "tests" / "smoke.py"]:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
for path in root.rglob("*"):
    assert not path.is_symlink(), path
    assert not path.is_file() or path.stat().st_size < 1_000_000, path
print("Static syntax and package checks passed; Sage runtime not checked.")
