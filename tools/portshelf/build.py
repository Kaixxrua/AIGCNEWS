#!/usr/bin/env python3
"""Test and cross-compile the standalone Windows directory into ZIP artifacts."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.out.expanduser().resolve()
    if output == root or root in output.parents:
        parser.error("Output must be outside the source directory.")
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["go", "test", "./..."], cwd=root, check=True)
    subprocess.run(["go", "vet", "./..."], cwd=root, check=True)
    sums = []
    for arch, label in (("amd64", "x64"), ("arm64", "arm64")):
        name = f"PortShelf-windows-{label}"
        with tempfile.TemporaryDirectory(prefix="portshelf-build-") as tmp:
            package = Path(tmp) / name
            package.mkdir()
            environment = dict(os.environ, GOOS="windows", GOARCH=arch, CGO_ENABLED="0")
            subprocess.run(
                ["go", "build", "-trimpath", "-buildvcs=false", "-ldflags=-s -w -H=windowsgui",
                 "-o", str(package / "PortShelf.exe"), "."],
                cwd=root, env=environment, check=True,
            )
            shutil.copy2(root / "README.md", package / "使用说明.md")
            shutil.copy2(root / "LICENSE", package / "LICENSE")
            shutil.copytree(root / "third_party", package / "third_party")
            source = package / "source"
            source.mkdir()
            for pattern in ("*.go", "go.mod", "go.sum", "*.json", "build.py", "README.md", "LICENSE"):
                for path in root.glob(pattern):
                    if path.is_file():
                        shutil.copy2(path, source / path.name)
            for directory in ("web", "third_party"):
                shutil.copytree(root / directory, source / directory)
            target = output / f"{name}.zip"
            pending = output / f".{name}.zip.tmp"
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(package.parent))
            pending.replace(target)
            exe_target = output / f"{name}.exe"
            shutil.copy2(package / "PortShelf.exe", exe_target)
            for artifact in (target, exe_target):
                sums.append(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}")
                print(f"Built {artifact} ({artifact.stat().st_size:,} bytes)")
    (output / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
