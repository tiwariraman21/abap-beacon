"""Build a release: version bump check, tests, zip of the project (without .venv / caches), wheel, SHA256SUMS.

    python release.py 0.15.1
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", "abap_atlas.egg-info", "dist", "build", "workspaces"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else None
    current = (ROOT / "atlas" / "__init__.py").read_text(encoding="utf-8").split('"')[1]
    if version and version != current:
        print(f"atlas/__init__.py says {current}, you asked for {version} - bump the version first")
        return 1
    version = current
    print(f"Running tests for {version} ...")
    if subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT).returncode != 0:
        print("Tests failed - no release.")
        return 1
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zpath = dist / f"abap_beacon_v{version.replace('.', '_')}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if any(part in EXCLUDE_DIRS for part in rel.parts) or p.suffix in EXCLUDE_SUFFIX or p.is_dir():
                continue
            if rel.parts[0] == "data" and (rel.name.endswith((".db-wal", ".db-shm")) or rel.parts[1:2] == ("output",)):
                continue
            z.write(p, Path("abap_atlas") / rel)
    try:
        subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist), "-q"], cwd=ROOT, check=True)
    except Exception as error:  # noqa: BLE001
        print(f"(wheel skipped: {error})")
    sums = []
    for f in sorted(dist.iterdir()):
        if f.suffix in (".zip", ".whl"):
            sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
    (dist / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("\n".join(sums))
    print(f"\nRelease files in {dist}. Tag it:  git tag -a v{version} -m 'Release {version}' && git push origin v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
