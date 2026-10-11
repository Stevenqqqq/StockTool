"""Exercise the actual source entrypoint with conflicting installed packages."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("preload", ["none", "current", "old", "old_child", "old_path"])
def test_source_entrypoint_checks_actual_import_origin(tmp_path, preload):
    root = Path(__file__).resolve().parents[1]
    old = tmp_path / "old_site"
    package = old / "stock_tool"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "old-fixture"\n')
    env = dict(os.environ)
    env["STOCK_TOOL_USER_DATA_DIR"] = str(tmp_path / "runtime")
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    code = """
import json, runpy, sys, types
from pathlib import Path
root, old, preload = sys.argv[1:]
src = str(Path(root) / 'src')
sys.path[:] = [old, *[p for p in sys.path if p != src], src]
if preload == 'old':
    import stock_tool
elif preload != 'none':
    sys.path.insert(0, src)
    import stock_tool
    sys.path.remove(src)
    if preload == 'old_child':
        child = types.ModuleType('stock_tool.stale_child')
        child.__file__ = str(Path(old) / 'stock_tool/stale_child.py')
        sys.modules[child.__name__] = child
    if preload == 'old_path':
        stock_tool.__path__.append(str(Path(old) / 'stock_tool'))
try:
    runpy.run_path(str(Path(src) / 'stock_tool/dashboard/app.py'), run_name='source_probe')
except RuntimeError as exc:
    print(json.dumps({'error': str(exc), 'loaded_origin': sys.modules['stock_tool'].__file__}))
else:
    import stock_tool, stock_tool.dashboard.instrument_names as names
    print(json.dumps({'package': stock_tool.__file__, 'names': names.__file__}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(root), str(old), preload],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    if preload in {"old", "old_child", "old_path"}:
        assert "already loaded module" in evidence["error"]
        if preload == "old":
            assert Path(evidence["loaded_origin"]) == package / "__init__.py"
    else:
        assert Path(evidence["package"]) == root / "src/stock_tool/__init__.py"
        assert Path(evidence["names"]) == root / "src/stock_tool/dashboard/instrument_names.py"
