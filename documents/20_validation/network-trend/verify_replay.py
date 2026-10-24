#!/usr/bin/env python3
"""Verify the bounded Network Trend receipt without touching the worktree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def listed(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        right = line.split(" b/", 1)[1]
        prefix = "after/"
        if not right.startswith(prefix):
            raise AssertionError(f"unexpected patch destination: {right}")
        paths.append(right[len(prefix):])
    return paths


def verify() -> dict[str, object]:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    included = listed(ROOT / "included-paths.txt")
    excluded = listed(ROOT / "excluded-paths.txt")
    assert included == manifest["included_paths"], "included path list differs from manifest"
    assert excluded == manifest["excluded_paths"], "excluded path list differs from manifest"
    assert len(included) == 11 and len(set(included)) == 11, "included path set must contain exactly eleven unique paths"
    assert len(excluded) == 3 and len(set(excluded)) == 3, "excluded path set must contain exactly three unique paths"

    patch_file = ROOT / manifest["patch"]["path"]
    patch_text = patch_file.read_text(encoding="utf-8")
    assert sha256(patch_file) == manifest["patch"]["sha256"], "patch hash mismatch"
    actual_patch_paths = patch_paths(patch_text)
    assert actual_patch_paths == manifest["delta_paths"], "patch path order/set differs from manifest"
    for path in excluded:
        assert path not in patch_text, f"excluded path leaked into patch: {path}"
        assert not (ROOT / "baseline" / path).exists(), f"excluded path leaked into baseline: {path}"
        assert not (ROOT / "after" / path).exists(), f"excluded path leaked into after image: {path}"

    for path in included:
        record = manifest["files"][path]
        before = ROOT / "baseline" / path
        after = ROOT / "after" / path
        if record["before"]["state"] == "absent":
            assert not before.exists(), f"absent baseline unexpectedly exists: {path}"
        else:
            assert before.is_file(), f"baseline missing: {path}"
            assert sha256(before) == record["before"]["sha256"], f"baseline hash mismatch: {path}"
        assert after.is_file(), f"after image missing: {path}"
        assert sha256(after) == record["after"]["sha256"], f"after hash mismatch: {path}"
        if record["role"] == "proof_only":
            assert record["before"]["sha256"] == record["after"]["sha256"], f"proof-only input changed: {path}"

    replay_root = Path(tempfile.mkdtemp(prefix="cleanhouse-trend-replay-"))
    try:
        shutil.copytree(ROOT / "baseline", replay_root, dirs_exist_ok=True)
        process = subprocess.run(
            ["git", "apply", "-p2", str(patch_file)],
            cwd=replay_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert process.returncode == 0, f"patch replay failed: {process.stderr.strip()}"
        replay_hashes = {}
        for path in included:
            replayed = replay_root / path
            assert replayed.is_file(), f"replay did not create: {path}"
            replay_hashes[path] = sha256(replayed)
            assert replay_hashes[path] == manifest["files"][path]["after"]["sha256"], f"replay hash mismatch: {path}"
    finally:
        shutil.rmtree(replay_root, ignore_errors=True)

    return {
        "schema": "cleanhouse.network.trend.replay-result.v1",
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "pass",
        "manifest_schema": manifest["schema"],
        "repository_head": manifest["repository"]["head"],
        "included_count": len(included),
        "excluded_count": len(excluded),
        "delta_count": len(actual_patch_paths),
        "patch_sha256": manifest["patch"]["sha256"],
        "replayed_sha256": replay_hashes,
        "excluded_paths_absent": True,
        "temporary_tree_removed": not replay_root.exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify()
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
