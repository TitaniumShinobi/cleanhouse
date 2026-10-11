"""Root-only post-install configuration for the bundled macOS Wazuh agent.

This helper is intentionally narrow.  It accepts one mode-0600 JSON file,
imports the API-created client key, configures the single CleanHouse scope,
starts the agent, and never prints enrollment material.
"""

from __future__ import annotations

import base64
import grp
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


INSTALL_ROOT = Path("/Library/Ossec")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
AGENT_ID_RE = re.compile(r"^[0-9]{3,8}$")
IGNORED_SCOPE_NAMES = (
    ".git",
    ".venv",
    "venv",
    "cleanhouse_env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "runtime",
    "generated_evidence",
    "bundled",
)
NESTED_IGNORE_SREGEX = (
    "/(__pycache__|node_modules|cleanhouse_env|venv|runtime|generated_evidence|bundled)/"
    "|/\\.(git|venv|pytest_cache|mypy_cache|ruff_cache)/"
    "|\\.(pyc|pyo|swp|db-wal|db-shm|db-journal)$"
)
BARE_AMPERSAND_TOKEN = "__CLEANHOUSE_WAZUH_BARE_AMPERSAND__"


def _load_config(path: Path) -> dict[str, str]:
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise RuntimeError("Wazuh setup material must not be group/world accessible")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Wazuh setup material is invalid")
    result = {key: str(payload.get(key) or "").strip() for key in (
        "manager", "agent_name", "agent_id", "monitored_scope", "client_key"
    )}
    if not HOST_RE.fullmatch(result["manager"]):
        raise RuntimeError("Invalid manager hostname")
    if not AGENT_NAME_RE.fullmatch(result["agent_name"]):
        raise RuntimeError("Invalid Wazuh agent name")
    if not AGENT_ID_RE.fullmatch(result["agent_id"]):
        raise RuntimeError("Invalid Wazuh agent ID")
    scope = Path(result["monitored_scope"]).expanduser().resolve(strict=True)
    if not scope.is_dir():
        raise RuntimeError("CleanHouse monitored scope is not a directory")
    result["monitored_scope"] = str(scope)
    if not result["client_key"]:
        raise RuntimeError("Wazuh client key is missing")
    return result


def _client_key_line(encoded: str, *, agent_id: str, agent_name: str) -> bytes:
    try:
        decoded = base64.b64decode(encoded, validate=True).strip()
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Wazuh client key is not valid base64") from exc
    fields = decoded.decode("utf-8", errors="strict").split()
    if len(fields) < 4 or fields[0] != agent_id or fields[1] != agent_name:
        raise RuntimeError("Wazuh client key identity does not match enrollment")
    return decoded + b"\n"


def _ensure_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    node.text = value
    return node


def _parse_wazuh_configuration(source: str) -> ET.Element:
    if BARE_AMPERSAND_TOKEN in source:
        raise RuntimeError("Wazuh configuration contains the reserved ampersand token")
    protected = re.sub(
        r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)",
        BARE_AMPERSAND_TOKEN,
        source,
    )
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.fromstring(protected, parser=parser)


def _serialize_wazuh_configuration(root: ET.Element) -> str:
    serialized = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return serialized.replace(BARE_AMPERSAND_TOKEN, "&")


def _configure_xml(config: dict[str, str]) -> None:
    path = INSTALL_ROOT / "etc" / "ossec.conf"
    source = path.read_text(encoding="utf-8")
    # Wazuh's packaged macOS configuration contains shell commands with bare
    # `&&`.  Wazuh accepts that form, but strict XML parsers correctly reject
    # the unescaped ampersands.  Protect only bare ampersands while parsing,
    # then restore Wazuh's accepted dialect when serializing.
    root = _parse_wazuh_configuration(source)
    client = root.find("client")
    if client is None:
        client = ET.SubElement(root, "client")
    server = client.find("server")
    if server is None:
        server = ET.SubElement(client, "server")
    _ensure_text(server, "address", config["manager"])
    _ensure_text(server, "port", "1514")
    _ensure_text(server, "protocol", "tcp")

    syscheck = root.find("syscheck")
    if syscheck is None:
        syscheck = ET.SubElement(root, "syscheck")
    _ensure_text(syscheck, "disabled", "no")
    _ensure_text(syscheck, "frequency", "43200")
    _ensure_text(syscheck, "scan_on_start", "yes")
    scope = config["monitored_scope"]
    for existing in list(syscheck.findall("directories")):
        if (existing.text or "").strip() == scope:
            syscheck.remove(existing)
    directories = ET.SubElement(syscheck, "directories", {
        "realtime": "yes",
        "check_all": "yes",
        "report_changes": "no",
        "recursion_level": "64",
    })
    directories.text = scope
    existing_ignores = {(node.text or "").strip() for node in syscheck.findall("ignore")}
    for name in IGNORED_SCOPE_NAMES:
        ignored = str(Path(scope) / name)
        if ignored not in existing_ignores:
            node = ET.SubElement(syscheck, "ignore")
            node.text = ignored
            existing_ignores.add(ignored)
    regex_ignores = {
        (node.text or "").strip()
        for node in syscheck.findall("ignore")
        if node.get("type") == "sregex"
    }
    if NESTED_IGNORE_SREGEX not in regex_ignores:
        node = ET.SubElement(syscheck, "ignore", {"type": "sregex"})
        node.text = NESTED_IGNORE_SREGEX
    ET.indent(root, space="  ")
    temporary = path.with_suffix(".conf.cleanhouse-new")
    temporary.write_text(
        _serialize_wazuh_configuration(root) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o640)
    try:
        group_id = grp.getgrnam("wazuh").gr_gid
    except KeyError:
        group_id = -1
    os.chown(temporary, 0, group_id)
    os.replace(temporary, path)


def _install_client_key(config: dict[str, str]) -> None:
    target = INSTALL_ROOT / "etc" / "client.keys"
    temporary = target.with_suffix(".keys.cleanhouse-new")
    temporary.unlink(missing_ok=True)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    try:
        os.write(fd, _client_key_line(
            config["client_key"],
            agent_id=config["agent_id"],
            agent_name=config["agent_name"],
        ))
    finally:
        os.close(fd)
    # Root authorization helpers commonly inherit a restrictive 077 umask.
    # The agent daemon runs as the Wazuh service account, so the group-read
    # bit must be applied explicitly rather than relying on os.open's mode.
    os.chmod(temporary, 0o640)
    try:
        group_id = grp.getgrnam("wazuh").gr_gid
    except KeyError:
        group_id = -1
    os.chown(temporary, 0, group_id)
    os.replace(temporary, target)


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        raise RuntimeError("Wazuh agent configuration requires root")
    if len(argv) != 2:
        raise RuntimeError("Expected one setup-material path")
    config = _load_config(Path(argv[1]))
    _install_client_key(config)
    _configure_xml(config)
    control = INSTALL_ROOT / "bin" / "wazuh-control"
    failures: list[str] = []
    for action in ("restart", "start"):
        result = subprocess.run(
            [str(control), action],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode == 0:
            return 0
        output = " ".join((result.stdout + " " + result.stderr).split())
        failures.append(f"{action}: {output[-768:] or 'no control output'}")
        time.sleep(2)
    log_path = INSTALL_ROOT / "logs" / "ossec.log"
    try:
        log_tail = " ".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
    except OSError:
        log_tail = "unavailable"
    raise RuntimeError(
        "Wazuh agent did not start after configuration; "
        + "; ".join(failures)
        + f"; ossec.log: {log_tail[-1536:]}"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(str(exc)[:512], file=sys.stderr)
        raise SystemExit(1)
