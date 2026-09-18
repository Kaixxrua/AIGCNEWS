#!/usr/bin/env python3
"""Publish the active immutable frontend artifact through the private edge controller."""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy_production import (
    IMAGE_RE,
    SHA_RE,
    DeployError,
    deployment_lock,
    read_state,
    write_state,
)


def prepare_inventory(config: dict, artifact: Path) -> dict:
    inventory = json.loads(Path(config["inventory"]).read_text())
    selected = config["sites"]
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
        raise DeployError("edge sites must be a nonempty unique list")
    result = copy.deepcopy(inventory)
    result["sites"] = {}
    result["groups"] = {}
    for name in selected:
        if name not in inventory["sites"]:
            raise DeployError(f"unknown configured edge site: {name}")
        site = copy.deepcopy(inventory["sites"][name])
        site.update(project_root=str(artifact.parent), artifact_dir=artifact.name)
        result["sites"][name] = site
    return result


def active_image(state: dict, source_sha: str) -> str | None:
    if not SHA_RE.fullmatch(source_sha):
        raise DeployError("invalid source SHA")
    if state.get("in_progress"):
        raise DeployError("origin deployment is unfinished")
    if state.get("active_release") != source_sha:
        return None
    image = state.get("images", {}).get("frontend", "")
    if not IMAGE_RE.fullmatch(image):
        raise DeployError("active frontend image must be an immutable digest")
    return image


def command(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def publish(root: Path, source_sha: str, *, dry_run: bool = False) -> str:
    control = root / ".aigcnews-deploy"
    with deployment_lock(control / "deploy.lock", 600):
        image = active_image(read_state(control / "state.json"), source_sha)
        if image is None:
            return "superseded"
        config = json.loads((control / "edge-config.json").read_text())
        controller = Path(config["controller"])
        if not controller.is_absolute() or not controller.is_file():
            raise DeployError("edge controller must be an existing absolute file")
        # Validate all configuration before exporting or changing any edge.
        prepare_inventory(config, control / "artifact" / "dist")
        with tempfile.TemporaryDirectory(prefix="frontend-edge-", dir=control) as temporary:
            stage = Path(temporary)
            artifact = stage / "dist"
            artifact.mkdir()
            container = command(["docker", "create", image])
            if not re.fullmatch(r"[0-9a-f]{64}", container):
                raise DeployError("unexpected export container identity")
            try:
                subprocess.run(["docker", "cp", f"{container}:/usr/share/nginx/html/.", str(artifact)], check=True)
            finally:
                subprocess.run(["docker", "rm", container], check=True)
            if not (artifact / "index.html").is_file():
                raise DeployError("frontend artifact has no index.html")
            inventory_path = stage / "inventory.json"
            write_state(inventory_path, prepare_inventory(config, artifact))
            state_path = control / "edge-state.json"
            previous = json.loads(state_path.read_text()) if state_path.exists() else {}
            state = {"source_sha": source_sha, "frontend_image": image, "sites": {}}
            if previous.get("source_sha") == source_sha and previous.get("frontend_image") == image:
                state["sites"] = previous.get("sites", {})
            for site in config["sites"]:
                args = [sys.executable, str(controller), "--inventory", str(inventory_path),
                        "plan" if dry_run else "publish", site, "--skip-build"]
                if not dry_run:
                    state["sites"][site] = "publishing"
                    write_state(state_path, state)
                try:
                    subprocess.run(args, check=True)
                except subprocess.CalledProcessError:
                    if not dry_run:
                        state["sites"][site] = "failed"
                        write_state(state_path, state)
                    raise
                if not dry_run:
                    state["sites"][site] = "published"
                    write_state(state_path, state)
            return "validated" if dry_run else "published"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(publish(args.root.resolve(), args.source_sha, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
