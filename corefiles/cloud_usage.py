"""
Read-only observation of cloud service usage indicators.

No credentials are read, decrypted, or harvested.
Only environment variable *names*, config file *existence*,
process *command lines*, and network *destinations* are inspected.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def _ps_aux() -> List[str]:
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.splitlines()
    except Exception:
        return []


def _lsof_i() -> List[str]:
    try:
        result = subprocess.run(
            ["lsof", "-i"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.splitlines()
    except Exception:
        return []


def _check_env_var_names(prefixes: tuple[str, ...]) -> List[str]:
    return sorted(k for k in os.environ if k.startswith(prefixes))


def _check_dir_exists(path: Path) -> bool:
    try:
        return path.is_dir()
    except Exception:
        return False


class CloudUsageObserver:
    """Read-only observer for cloud service usage indicators per provider.

    Each ``observe_*`` method returns a dict::

        {
            "status": "supported" | "unsupported",
            "provider": "<name>",
            "observed_indicators": [ ... ],
            "limitation": "Non-empty string describing v1 constraints",
        }

    ``observed_indicators`` is a list of dicts with keys
    ``type``, ``detail``, and ``evidence_level``.
    When ``status`` is ``"unsupported"`` the list is empty and
    ``limitation`` explains why.
    """

    def __init__(self) -> None:
        self._ps_lines: List[str] = []
        self._net_lines: List[str] = []

    def observe_all(self) -> Dict[str, List[Dict[str, Any]]]:
        self._ps_lines = _ps_aux()
        self._net_lines = _lsof_i()
        result = {
            "cloud_usage_adapters": [
                self.observe_aws(),
                self.observe_icloud(),
                self.observe_openai(),
                self.observe_tmobile(),
                self.observe_google_cloud(),
            ],
        }
        self._ps_lines = []
        self._net_lines = []
        return result

    # ── AWS ────────────────────────────────────────────────

    def observe_aws(self) -> Dict[str, Any]:
        indicators: List[Dict[str, Any]] = []
        provider = "aws"
        env_names = _check_env_var_names(("AWS_", "AMAZON_"))
        if env_names:
            indicators.append({
                "type": "environment",
                "detail": f"observed env vars: {', '.join(env_names)}",
                "evidence_level": "observed",
            })
        aws_config = Path.home() / ".aws"
        if _check_dir_exists(aws_config):
            indicators.append({
                "type": "config_directory",
                "detail": f"observed directory: {aws_config}",
                "evidence_level": "observed",
            })
        processes = self._ps_lines
        aws_cmds = [l for l in processes if "aws" in l.lower() or "boto3" in l.lower()]
        for cmd in aws_cmds[:5]:
            indicators.append({
                "type": "process",
                "detail": f"observed process: {cmd.strip()[:200]}",
                "evidence_level": "observed",
            })
        nets = self._net_lines
        aws_nets = [l for l in nets if "amazonaws" in l.lower()]
        for net in aws_nets[:5]:
            indicators.append({
                "type": "network",
                "detail": f"observed connection: {net.strip()[:200]}",
                "evidence_level": "observed",
            })
        status = "supported" if indicators else "unsupported"
        return {
            "status": status,
            "provider": provider,
            "observed_indicators": indicators,
            "limitation": "Credential values not inspected in v1." if status == "supported"
                          else "No AWS usage indicators observed. Credential values not inspected in v1.",
        }

    # ── iCloud ─────────────────────────────────────────────

    def observe_icloud(self) -> Dict[str, Any]:
        indicators: List[Dict[str, Any]] = []
        provider = "icloud"

        mobile_docs = Path.home() / "Library" / "Mobile Documents"
        if _check_dir_exists(mobile_docs):
            indicators.append({
                "type": "config_directory",
                "detail": f"observed directory: {mobile_docs}",
                "evidence_level": "observed",
            })
        processes = self._ps_lines
        icloud_procs = [l for l in processes if any(
            p in l.lower() for p in ("cloudd", "bird", "icloud")
        )]
        for cmd in icloud_procs[:5]:
            indicators.append({
                "type": "process",
                "detail": f"observed process: {cmd.strip()[:200]}",
                "evidence_level": "observed",
            })
        nets = self._net_lines
        icloud_nets = [l for l in nets if any(
            d in l.lower() for d in ("icloud.com", "icloud-content.com")
        )]
        for net in icloud_nets[:5]:
            indicators.append({
                "type": "network",
                "detail": f"observed connection: {net.strip()[:200]}",
                "evidence_level": "observed",
            })
        status = "supported" if indicators else "unsupported"
        return {
            "status": status,
            "provider": provider,
            "observed_indicators": indicators,
            "limitation": "iCloud token inspection not implemented in v1." if status == "supported"
                          else "No iCloud usage indicators observed. iCloud token inspection not implemented in v1.",
        }

    # ── OpenAI ─────────────────────────────────────────────

    def observe_openai(self) -> Dict[str, Any]:
        indicators: List[Dict[str, Any]] = []
        provider = "openai"

        env_names = _check_env_var_names(("OPENAI_",))
        if env_names:
            indicators.append({
                "type": "environment",
                "detail": f"observed env vars: {', '.join(env_names)}",
                "evidence_level": "observed",
            })
        processes = self._ps_lines
        oai_procs = [l for l in processes if "openai" in l.lower()]
        for cmd in oai_procs[:5]:
            indicators.append({
                "type": "process",
                "detail": f"observed process: {cmd.strip()[:200]}",
                "evidence_level": "observed",
            })
        nets = self._net_lines
        oai_nets = [l for l in nets if "api.openai.com" in l.lower()]
        for net in oai_nets[:5]:
            indicators.append({
                "type": "network",
                "detail": f"observed connection: {net.strip()[:200]}",
                "evidence_level": "observed",
            })
        status = "supported" if indicators else "unsupported"
        return {
            "status": status,
            "provider": provider,
            "observed_indicators": indicators,
            "limitation": "API key values not inspected in v1." if status == "supported"
                          else "No OpenAI usage indicators observed. API key values not inspected in v1.",
        }

    # ── T-Mobile ───────────────────────────────────────────

    def observe_tmobile(self) -> Dict[str, Any]:
        indicators: List[Dict[str, Any]] = []
        provider = "tmobile"

        env_names = _check_env_var_names(("TMOBILE_", "T-MOBILE_"))
        if env_names:
            indicators.append({
                "type": "environment",
                "detail": f"observed env vars: {', '.join(env_names)}",
                "evidence_level": "observed",
            })
        nets = self._net_lines
        tmo_nets = [l for l in nets if any(
            d in l.lower() for d in (".tmobile.com", ".t-mobile.com")
        )]
        for net in tmo_nets[:5]:
            indicators.append({
                "type": "network",
                "detail": f"observed connection: {net.strip()[:200]}",
                "evidence_level": "observed",
            })
        status = "supported" if indicators else "unsupported"
        return {
            "status": status,
            "provider": provider,
            "observed_indicators": indicators,
            "limitation": "T-Mobile account data not inspected in v1." if status == "supported"
                          else "No T-Mobile usage indicators observed. Account data not inspected in v1.",
        }

    # ── Google Cloud ───────────────────────────────────────

    def observe_google_cloud(self) -> Dict[str, Any]:
        indicators: List[Dict[str, Any]] = []
        provider = "google_cloud"

        env_names = _check_env_var_names(("GOOGLE_", "GCP_"))
        if env_names:
            indicators.append({
                "type": "environment",
                "detail": f"observed env vars: {', '.join(env_names)}",
                "evidence_level": "observed",
            })
        gcloud_config = Path.home() / ".config" / "gcloud"
        if _check_dir_exists(gcloud_config):
            indicators.append({
                "type": "config_directory",
                "detail": f"observed directory: {gcloud_config}",
                "evidence_level": "observed",
            })
        processes = self._ps_lines
        gcp_procs = [l for l in processes if any(
            p in l.lower() for p in ("gcloud", "gsutil", "bq ")
        )]
        for cmd in gcp_procs[:5]:
            indicators.append({
                "type": "process",
                "detail": f"observed process: {cmd.strip()[:200]}",
                "evidence_level": "observed",
            })
        nets = self._net_lines
        gcp_nets = [l for l in nets if any(
            d in l.lower() for d in (".googleapis.com", "cloud.google.com")
        )]
        for net in gcp_nets[:5]:
            indicators.append({
                "type": "network",
                "detail": f"observed connection: {net.strip()[:200]}",
                "evidence_level": "observed",
            })
        status = "supported" if indicators else "unsupported"
        return {
            "status": status,
            "provider": provider,
            "observed_indicators": indicators,
            "limitation": "GCP credential values not inspected in v1." if status == "supported"
                          else "No Google Cloud usage indicators observed. Credential values not inspected in v1.",
        }


def get_cloud_usage_observer() -> CloudUsageObserver:
    return CloudUsageObserver()
