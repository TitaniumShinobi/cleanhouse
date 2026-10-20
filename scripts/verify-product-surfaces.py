#!/usr/bin/env python3
"""Fail closed when an established CleanHouse product surface disappears."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / ".cleanhouse" / "product-surface-baseline.json"
SERVER_PATH = ROOT / "backend" / "server.py"


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    server = SERVER_PATH.read_text(encoding="utf-8")
    failures: list[str] = []

    for surface in baseline["surfaces"]:
        name = surface["name"]
        route = surface["route"]
        relative_file = surface["file"]
        marker = surface["marker"]
        path = ROOT / relative_file

        if not path.is_file():
            failures.append(f"{name}: missing file {relative_file}")
            continue

        source = path.read_text(encoding="utf-8")
        if marker not in source:
            failures.append(f"{name}: missing marker {marker!r} in {relative_file}")
        if f"@app.route('{route}')" not in server and f'@app.route("{route}")' not in server:
            failures.append(f"{name}: missing server route {route}")

    if failures:
        print("CLEANHOUSE PRODUCT SURFACE BASELINE: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"CLEANHOUSE PRODUCT SURFACE BASELINE: PASS ({len(baseline['surfaces'])} protected surfaces)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
