"""Build the approved v1.4.3 delivery in a new directory; never install or promote."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stock_tool import __version__  # noqa: E402
from stock_tool.installer_build import build_unsigned_internal_test_installer  # noqa: E402
from stock_tool.release_assets import package_release_assets  # noqa: E402

ACCEPTED = "40DF0F731202C7A16192DE8E2AE88844A400F958E25F914EE6A3731025414216"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--accepted-payload", type=Path, required=True)
    parser.add_argument("--rollback-installer", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert __version__ == "1.4.3"
    assert sha(args.accepted_payload) == ACCEPTED, "Accepted payload identity mismatch"
    baseline = json.loads(
        (ROOT / "docs/product/research-workflow-evidence/20260921-candidate-source.json").read_text(
            encoding="utf-8"
        )
    )
    for name, expected in baseline.items():
        data = (ROOT / name).read_bytes()
        if name == "src/stock_tool/__init__.py":
            data = data.replace(b'"1.4.3"', b'"1.4.2"')
        assert hashlib.sha256(data).hexdigest() == expected, f"Product source drift: {name}"
    assert set(baseline) == {p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")}
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

    def run(command: list[str], label: str) -> None:
        with (output / f"{label}.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=log, check=True)

    stage = output / "StockTool"
    for spec, dist, work in (
        ("StockTool.spec", output / "payload-build", output / "build-payload"),
        ("StableLauncher.spec", stage, output / "build-stable"),
    ):
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(dist),
                "--workpath",
                str(work),
                spec,
            ],
            spec.replace(".spec", ""),
        )
    shutil.move(str(output / "payload-build/StockToolPayload"), stage / "Payload")
    package_release_assets(stage / "Payload", payload=True)
    shutil.copytree(stage / "Payload", stage / "versions/1.4.3")
    run([str(stage / "StockTool.exe"), "--activate-version", "1.4.3"], "activation")
    result = build_unsigned_internal_test_installer(
        project_root=ROOT,
        staging_directory=stage,
        output_directory=output / "installer",
        rollback_artifact_path=args.rollback_installer.resolve(),
        rollback_version="1.4.2",
        disable_shell_integration=False,
    )
    binding = {
        "version": __version__,
        "status": "NOT_INSTALLED_PENDING_ISOLATED_LIFECYCLE",
        "accepted_research_payload_sha256": ACCEPTED,
        "stable_exe_sha256": sha(stage / "StockTool.exe"),
        "payload_exe_sha256": sha(stage / "Payload/StockToolPayload.exe"),
        "installer_sha256": sha(result.installer_path),
        "rollback_installer_sha256": sha(args.rollback_installer),
        "files": {
            p.relative_to(stage).as_posix(): sha(p) for p in sorted(stage.rglob("*")) if p.is_file()
        },
    }
    (output / "candidate-binding.json").write_text(
        json.dumps(binding, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in binding.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
