#!/usr/bin/env python3
"""Generate a deterministic notification truth inventory for CleanHouse."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MONITORING_PATH = REPO / "backend" / "api" / "cleanhouse_monitoring.py"
OUTPUT_PATH = REPO / "docs" / "evidence" / "CLEANHOUSE_NOTIFICATION_TRUTH_INVENTORY.md"

PRODUCTION_TYPES = {
    "session_started",
    "session_ended",
    "scope_drift_detected",
}

VALIDATION_SOURCES = {"probe", "notification_probe"}


@dataclass(frozen=True)
class EmitterRow:
    file: str
    function: str
    line: int
    notification_type: str
    trigger: str
    runtime_backing_event: str
    deep_link_target: str
    current_behavior: str
    classification: str


@dataclass(frozen=True)
class ClickFlowRow:
    emitter: str
    click_url_builder: str
    ui_handler: str
    ack_path: str
    current_behavior: str


def _literal(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        out: dict[str, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = _literal(key_node)
            if isinstance(key, str):
                out[key] = _literal(value_node)
        return out
    if isinstance(node, ast.List):
        return [_literal(v) for v in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_literal(v) for v in node.elts)
    return None


def _runtime_backing_event(metadata: dict[str, Any], notification_type: str) -> str:
    if "domain_event_id" in metadata:
        return "domain_event_id"
    if "prompt_id" in metadata:
        return "prompt_id"
    if "alert_id" in metadata:
        return "alert_id"
    if "receipt_id" in metadata:
        return "receipt_id"
    if "rollback_id" in metadata:
        return "rollback_id"
    if "approval_id" in metadata:
        return "approval_id"
    if notification_type in {"session_started", "session_ended"}:
        return "session_id"
    return "missing"


def _deep_link_target(metadata: dict[str, Any], notification_type: str) -> str:
    if notification_type == "incident_action_required" or "incident_id" in metadata:
        return "/incident-receipt"
    return "/dashboard"


def _classification(notification_type: str, source: str, backing: str) -> tuple[str, str]:
    if source in VALIDATION_SOURCES:
        return "REMOVE", "validation_only (persisted, dispatch suppressed by default)"
    if notification_type not in PRODUCTION_TYPES:
        return "REMOVE", "persist_only (non-target type)"
    if backing == "missing":
        return "BROKEN", "production target missing runtime backing id"
    return "VALID", "production_operator (runtime-backed)"


def collect_emitters() -> list[EmitterRow]:
    tree = ast.parse(MONITORING_PATH.read_text(encoding="utf-8"))
    rows: list[EmitterRow] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            target = None
            if isinstance(node.func, ast.Attribute):
                target = node.func.attr
            if target == "_ensure_operator_notification":
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                notification_type = _literal(kwargs.get("notification_type"))
                source = _literal(kwargs.get("source")) or "workstation"
                summary = _literal(kwargs.get("summary"))
                metadata = _literal(kwargs.get("metadata"))
                metadata = metadata if isinstance(metadata, dict) else {}
                if not isinstance(notification_type, str):
                    notification_type = "<dynamic>"
                trigger = summary if isinstance(summary, str) and summary else "runtime callsite"
                backing = _runtime_backing_event(metadata, notification_type)
                deep_link = _deep_link_target(metadata, notification_type)
                classification, behavior = _classification(notification_type, str(source), backing)
                rows.append(
                    EmitterRow(
                        file="backend/api/cleanhouse_monitoring.py",
                        function=".".join(self.stack) or "<module>",
                        line=getattr(node, "lineno", 0),
                        notification_type=notification_type,
                        trigger=trigger,
                        runtime_backing_event=backing,
                        deep_link_target=deep_link,
                        current_behavior=behavior,
                        classification=classification,
                    )
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    rows.sort(key=lambda row: (row.file, row.function, row.line, row.notification_type))
    return rows


def build_click_inventory() -> list[ClickFlowRow]:
    return [
        ClickFlowRow(
            emitter="_ensure_operator_notification -> _operator_notification_click_url",
            click_url_builder="backend/api/cleanhouse_monitoring.py::_operator_notification_click_url",
            ui_handler="frontend/js/dashboard.js::applyPendingDashboardFocus",
            ack_path="frontend/js/dashboard.js::ackNotification -> POST /cleanhouse/notifications/<id>/ack",
            current_behavior="open + auto-ack on deep-link resolution",
        ),
        ClickFlowRow(
            emitter="_ensure_operator_notification -> _runtime_notification_click_url",
            click_url_builder="backend/api/cleanhouse_monitoring.py::_runtime_notification_click_url",
            ui_handler="frontend/js/dashboard.js::applyPendingDashboardFocus",
            ack_path="frontend/js/dashboard.js::ackNotification -> POST /cleanhouse/notifications/<id>/ack",
            current_behavior="open + auto-ack on deep-link resolution",
        ),
        ClickFlowRow(
            emitter="incident_action_required deep-link",
            click_url_builder="backend/api/cleanhouse_monitoring.py::_operator_notification_click_url (/incident-receipt)",
            ui_handler="frontend/js/incident-receipt.js::loadIncidentCard",
            ack_path="frontend/js/incident-receipt.js::ackDeepLinkNotificationIfNeeded -> POST /cleanhouse/notifications/<id>/ack",
            current_behavior="open incident receipt + auto-ack",
        ),
    ]


def render(rows: list[EmitterRow], click_rows: list[ClickFlowRow]) -> str:
    valid = [row for row in rows if row.classification == "VALID"]
    broken = [row for row in rows if row.classification == "BROKEN"]
    remove = [row for row in rows if row.classification == "REMOVE"]

    out: list[str] = []
    out.append("# CLEANHOUSE Notification Truth Inventory")
    out.append("")
    out.append("## NOTIFICATION INVENTORY")
    out.append("")
    out.append("| file | function | notification_type | trigger | runtime backing event | deep-link target | current behavior | classification |")
    out.append("|---|---|---|---|---|---|---|---|")
    for row in rows:
        out.append(
            f"| `{row.file}:{row.line}` | `{row.function}` | `{row.notification_type}` | {row.trigger[:110]} | `{row.runtime_backing_event}` | `{row.deep_link_target}` | {row.current_behavior} | **{row.classification}** |"
        )

    out.append("")
    out.append("## CLICK FLOW INVENTORY")
    out.append("")
    out.append("| emitter | click URL builder | UI handler | ack path | current behavior |")
    out.append("|---|---|---|---|---|")
    for row in click_rows:
        out.append(
            f"| {row.emitter} | `{row.click_url_builder}` | `{row.ui_handler}` | `{row.ack_path}` | {row.current_behavior} |"
        )

    out.append("")
    out.append("## VALID")
    out.append("")
    for row in valid:
        out.append(f"- `{row.notification_type}` via `{row.function}` ({row.file}:{row.line})")

    out.append("")
    out.append("## BROKEN")
    out.append("")
    if broken:
        for row in broken:
            out.append(
                f"- `{row.notification_type}` via `{row.function}` ({row.file}:{row.line}) missing `{row.runtime_backing_event}` backing"
            )
    else:
        out.append("- none")

    out.append("")
    out.append("## REMOVE")
    out.append("")
    for row in remove:
        out.append(f"- `{row.notification_type}` via `{row.function}` ({row.file}:{row.line}) -> {row.current_behavior}")

    out.append("")
    out.append("## ROOT CAUSE")
    out.append("")
    out.append("- Pre-existing notification lane mixed production and validation sources in the same dispatch surface.")
    out.append("- Non-target notification types were emitted as operator notifications instead of persist-only evidence records.")
    out.append("- Click completion lacked guaranteed open-time acknowledgement for deep-link entry points.")

    out.append("")
    out.append("## TOP 3 PATCHES")
    out.append("")
    out.append("1. Eliminate passive active-context auto-attach for GET polling (`attach` explicit only).")
    out.append("2. Enforce production dispatch gate + runtime-backing requirements (`event_id`, `incident_id` for incident action, `click_url`).")
    out.append("3. Route incident-backed notifications to `/incident-receipt` and auto-acknowledge on deep-link open.")

    out.append("")
    return "\n".join(out)


def main() -> int:
    rows = collect_emitters()
    click_rows = build_click_inventory()
    payload = render(rows, click_rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
