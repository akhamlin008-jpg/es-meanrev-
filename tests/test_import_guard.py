"""Runtime purity guard. gs-quant, scipy and statsmodels are DEV/CI oracles
only; quantlab and the live scripts must run on requirements.txt alone.
Each module is imported in a fresh subprocess and the loaded module set is
checked -- a transitive import through any helper is caught too."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BANNED = ("gs_quant", "scipy", "statsmodels", "sklearn")

RUNTIME_MODULES = [
    "quantlab.account", "quantlab.cache", "quantlab.contracts",
    "quantlab.costs", "quantlab.data", "quantlab.engine",
    "quantlab.evalsim", "quantlab.indicators", "quantlab.live_strategy",
    "quantlab.report", "quantlab.sizing", "quantlab.strategies",
]

CHECK = (
    "import importlib, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "bad = sorted(b for b in {banned} if b in sys.modules)\n"
    "assert not bad, f'{{sys.argv[1]}} transitively imports {{bad}}'\n"
).format(banned=BANNED)


@pytest.mark.parametrize("module", RUNTIME_MODULES)
def test_runtime_module_stays_free_of_dev_deps(module):
    r = subprocess.run([sys.executable, "-c", CHECK, module],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

def test_requirements_txt_stays_lean():
    text = (ROOT / "requirements.txt").read_text().lower()
    for dep in ("gs-quant", "gs_quant", "scipy", "statsmodels", "scikit-learn"):
        assert dep not in text, f"{dep} must stay in requirements-dev.txt only"
