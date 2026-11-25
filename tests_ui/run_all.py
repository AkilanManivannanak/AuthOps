"""Run every recorded UI journey in order and print a summary."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOURNEYS = ["j_accounts.py", "j_patient.py", "j_clinic.py", "j_ops.py", "j_mobile.py", "j_standards.py"]
for j in JOURNEYS:
    subprocess.run([sys.executable, str(HERE / j)], cwd=HERE)
total = passed = 0
for f in sorted((HERE / "runs").glob("result_*.json")):
    r = json.loads(f.read_text())
    n, p = len(r["checks"]), sum(c["pass"] for c in r["checks"])
    total, passed = total + n, passed + p
    print(f"{r['journey']:28s} {p}/{n}  video: runs/{r['video']}")
print(f"\n{passed}/{total} checks passed")
sys.exit(0 if passed == total else 1)
