#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    base = Path(__file__).resolve().parent
    manifest = json.loads((base / "DOCUMENTS_MANIFEST.json").read_text(encoding="utf-8"))
    coverage = json.loads((base / "SOURCE_COVERAGE.json").read_text(encoding="utf-8"))
    file_index = json.loads((base / "FILE_INDEX.json").read_text(encoding="utf-8"))

    errors: list[str] = []

    if manifest.get("counts", {}).get("missing") != 0:
        errors.append("manifest missing count is non-zero")
    if manifest.get("counts", {}).get("mismatch") != 0:
        errors.append("manifest mismatch count is non-zero")

    for row in coverage.get("rows", []):
        if not row.get("mirror_exists"):
            errors.append(f"mirror missing: {row.get('source_path')}")
        if not row.get("sha_match"):
            errors.append(f"sha mismatch: {row.get('source_path')}")

    indexed = {entry.get("path"): entry for entry in file_index.get("files", [])}
    for rel, entry in indexed.items():
        path = base / rel
        if not path.exists():
            errors.append(f"indexed file missing on disk: {rel}")
            continue
        actual_sha = sha256(path)
        if entry.get("sha256") != actual_sha:
            errors.append(f"index sha mismatch: {rel}")

    if "FILE_INDEX.json" in indexed:
        errors.append("FILE_INDEX.json must be excluded from FILE_INDEX hash scope")
    if "FILE_INDEX.json.sha256" in indexed:
        errors.append("FILE_INDEX.json.sha256 must be excluded from FILE_INDEX hash scope")

    if errors:
        print("documents tree verification: FAIL")
        for err in errors:
            print(f"- {err}")
        return 1

    print("documents tree verification: PASS")
    print(f"source files: {manifest.get('counts', {}).get('source_files')}")
    print(f"indexed files: {file_index.get('file_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
