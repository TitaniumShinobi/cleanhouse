"""Wazuh agent packaging, lifecycle, and administrator-authorized setup."""

from __future__ import annotations

import ctypes
import hashlib
import http.server
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


VERSION = "4.14.7"
PACKAGE_NAME = f"wazuh-agent-{VERSION}-1.arm64.pkg"
SOURCE_ARCHIVE_NAME = f"wazuh-{VERSION}-source.tar.gz"
OFFICIAL_PACKAGE_SHA512 = "9d1dbf1a0e440d8a1f6f75d44a30a395442926b01208ee8b88821e6d21a6b1ea5b885fd0c389df999a089bebda741e1af76cf9f773d552612430664da9428b11"
OFFICIAL_SOURCE_SHA512 = "d6182330f74ff249bfd8ff2f6a6f7934b6c5df9c53a8e5955cd42c0aa36fb25cabaef2dce2dd6241f6eb979b85fc6f87067e9f5c19069eea940aa6f127e61c09"
OFFICIAL_SIGNER = "Wazuh Inc (KLZK8P68R5)"
OFFICIAL_SIGNER_FINGERPRINT = "A88FB540D91F9A4CAFDC573FE77D633038A1787D1C05548027EAD4B9C6477E1E"
REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = REPO_ROOT / "bundled" / "wazuh" / "darwin-arm64"
MANIFEST_PATH = BUNDLE_DIR / "manifest.json"
PACKAGE_PATH = BUNDLE_DIR / PACKAGE_NAME
SOURCE_ARCHIVE_PATH = BUNDLE_DIR / SOURCE_ARCHIVE_NAME
INSTALL_ROOT = Path("/Library/Ossec")
CONFIGURE_HELPER = REPO_ROOT / "backend" / "wazuh_agent_configure.py"
KEYCHAIN_SERVICE = "org.cleanhouse.wazuh.enrollment"
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_VERIFY_CACHE: tuple[tuple[int, int, int, int, str], dict[str, Any]] | None = None


def _read_manifest() -> dict[str, Any]:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_signature(path: Path) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"status": "unsupported", "verified": False, "reason": "macos_required"}
    result = subprocess.run(
        ["/usr/sbin/pkgutil", "--check-signature", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    compact_output = re.sub(r"\s+", "", output).upper()
    trusted = (
        result.returncode == 0
        and f"Developer ID Installer: {OFFICIAL_SIGNER}" in output
        and OFFICIAL_SIGNER_FINGERPRINT in compact_output
        and "notarization: trusted by the apple notary service" in output.lower()
    )
    return {
        "status": "verified" if trusted else "failed",
        "verified": trusted,
        "signer": OFFICIAL_SIGNER if trusted else "",
        "sha256_fingerprint": OFFICIAL_SIGNER_FINGERPRINT if trusted else "",
        "summary": output[:2048],
    }


def _vendoring_signature_receipt(manifest: dict[str, Any]) -> dict[str, Any]:
    receipt = manifest.get("signature")
    if not isinstance(receipt, dict):
        return {"status": "missing", "verified": False, "reason": "signature_receipt_missing"}
    verified = (
        manifest.get("vendored") is True
        and receipt.get("developer_id_installer") == OFFICIAL_SIGNER
        and receipt.get("sha256_fingerprint") == OFFICIAL_SIGNER_FINGERPRINT
        and receipt.get("notarization") == "trusted"
        and bool(receipt.get("verified_at_vendoring"))
    )
    return {
        "status": "verified_at_vendoring" if verified else "failed",
        "verified": verified,
        "signer": str(receipt.get("developer_id_installer") or ""),
        "sha256_fingerprint": str(receipt.get("sha256_fingerprint") or ""),
        "notarization": str(receipt.get("notarization") or ""),
        "verified_at_vendoring": str(receipt.get("verified_at_vendoring") or ""),
    }


def verify_bundle() -> dict[str, Any]:
    global _VERIFY_CACHE
    manifest = _read_manifest()
    expected = str(manifest.get("sha512") or "").lower()
    expected_source = str(manifest.get("source_sha512") or "").lower()
    package_present = PACKAGE_PATH.is_file()
    stat = PACKAGE_PATH.stat() if package_present else None
    source_present = SOURCE_ARCHIVE_PATH.is_file()
    source_stat = SOURCE_ARCHIVE_PATH.stat() if source_present else None
    cache_key = (
        int(stat.st_mtime_ns) if stat else 0,
        int(stat.st_size) if stat else 0,
        int(source_stat.st_mtime_ns) if source_stat else 0,
        int(source_stat.st_size) if source_stat else 0,
        hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
    )
    if _VERIFY_CACHE is not None and _VERIFY_CACHE[0] == cache_key:
        return dict(_VERIFY_CACHE[1])
    actual = _sha512(PACKAGE_PATH) if package_present else ""
    checksum_verified = bool(
        package_present
        and expected == OFFICIAL_PACKAGE_SHA512
        and actual == OFFICIAL_PACKAGE_SHA512
    )
    actual_source = _sha512(SOURCE_ARCHIVE_PATH) if source_present else ""
    source_verified = bool(
        source_present
        and expected_source == OFFICIAL_SOURCE_SHA512
        and actual_source == OFFICIAL_SOURCE_SHA512
    )
    if not package_present:
        signature = {
            "status": "unavailable",
            "verified": False,
            "reason": "package_missing",
        }
    elif not checksum_verified:
        # Never ask macOS to evaluate, copy, or otherwise process package bytes
        # until both the manifest and the checked-in payload match the pin.
        signature = {
            "status": "blocked",
            "verified": False,
            "reason": "pinned_checksum_required",
        }
    else:
        live_signature = _package_signature(PACKAGE_PATH)
        signature = live_signature if live_signature.get("verified") else (
            _signature_with_provenance_recovery(live_signature)
        )
    receipt = _vendoring_signature_receipt(manifest)
    # A historical manifest receipt is useful audit metadata, but it can never
    # override the live Apple package-signature gate. Installation is exposed
    # only when the exact bytes being installed pass pkgutil now.
    verified = checksum_verified and source_verified and bool(signature.get("verified"))
    result = {
        "status": "verified" if verified else ("unavailable" if not package_present else "degraded"),
        "packaged": verified,
        "package_present": package_present,
        "package_path": str(PACKAGE_PATH),
        "version": VERSION,
        "architecture": "darwin-arm64",
        "sha512": actual,
        "expected_sha512": expected,
        "checksum_verified": checksum_verified,
        "source_archive_path": str(SOURCE_ARCHIVE_PATH),
        "source_archive_present": source_present,
        "source_sha512": actual_source,
        "expected_source_sha512": expected_source,
        "source_verified": source_verified,
        "signature": signature,
        "vendoring_signature_receipt": receipt,
        "manifest": manifest,
    }
    _VERIFY_CACHE = (cache_key, result)
    return dict(result)


def _copy_package_over_loopback(destination: Path) -> None:
    token = secrets.token_urlsafe(32)
    expected_path = f"/{token}/{PACKAGE_NAME}"

    class PackageHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path != expected_path:
                self.send_error(404)
                return
            size = PACKAGE_PATH.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with PACKAGE_PATH.open("rb") as source:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)

        def log_message(self, _format, *_args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PackageHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="wazuh-package-loopback", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}{expected_path}"
    try:
        result = subprocess.run(
            [
                "/usr/bin/curl",
                "--fail",
                "--silent",
                "--show-error",
                "--proto",
                "=http",
                "--noproxy",
                "*",
                "--max-time",
                "30",
                "--output",
                str(destination),
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=40,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "loopback package copy failed")[:1024])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _materialize_pinned_package() -> Path:
    """Create a de-provenanced byte-identical copy without touching the bundle."""
    fd, raw_path = tempfile.mkstemp(prefix="cleanhouse-wazuh-agent-", suffix=".pkg", dir="/private/tmp")
    os.close(fd)
    path = Path(raw_path)
    try:
        _copy_package_over_loopback(path)
        subprocess.run(
            ["/usr/bin/xattr", "-d", "com.apple.provenance", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        os.chmod(path, 0o600)
        if _sha512(path) != OFFICIAL_PACKAGE_SHA512:
            raise RuntimeError("materialized Wazuh package checksum verification failed")
        return path
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _signature_with_provenance_recovery(direct_signature: dict[str, Any]) -> dict[str, Any]:
    """Recheck pinned bytes on a temporary copy when provenance blocks pkgutil."""
    path: Path | None = None
    try:
        path = _materialize_pinned_package()
        signature = _package_signature(path)
        return {
            **signature,
            "verification_path": "temporary_byte_identical_copy",
            "provenance_recovery": {
                "attempted": True,
                "verified": bool(signature.get("verified")),
                "direct_status": str(direct_signature.get("status") or "failed"),
            },
        }
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            **direct_signature,
            "provenance_recovery": {
                "attempted": True,
                "verified": False,
                "direct_status": str(direct_signature.get("status") or "failed"),
                "error": str(exc)[:1024],
            },
        }
    finally:
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass


def _materialize_verified_package() -> Path:
    path = _materialize_pinned_package()
    try:
        signature = _package_signature(path)
        if not signature.get("verified"):
            raise RuntimeError("materialized Wazuh package signature verification failed")
        return path
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _materialize_configure_helper() -> Path:
    """Copy the root helper outside privacy-protected source directories."""
    fd, raw_path = tempfile.mkstemp(
        prefix="cleanhouse-wazuh-configure-", suffix=".py", dir="/private/tmp"
    )
    os.close(fd)
    path = Path(raw_path)
    try:
        shutil.copyfile(CONFIGURE_HELPER, path)
        os.chmod(path, 0o600)
        source_digest = hashlib.sha256(CONFIGURE_HELPER.read_bytes()).digest()
        if hashlib.sha256(path.read_bytes()).digest() != source_digest:
            raise RuntimeError("materialized Wazuh configuration helper verification failed")
        return path
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _installed_version() -> str:
    version_file = INSTALL_ROOT / "etc" / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _agent_status() -> dict[str, Any]:
    control = INSTALL_ROOT / "bin" / "wazuh-control"
    if not _safe_is_file(control):
        return {"running": False, "summary": ""}
    try:
        result = subprocess.run(
            [str(control), "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"running": False, "summary": type(exc).__name__, "returncode": None}
    summary = (result.stdout + "\n" + result.stderr).strip()
    normalized = summary.lower()
    running = bool(
        result.returncode == 0
        and "not running" not in normalized
        and re.search(
            r"\bwazuh-(?:agentd|modulesd|logcollector|syscheckd)\s+is\s+running\b",
            normalized,
        )
    )
    return {"running": running, "summary": summary[:2048], "returncode": result.returncode}


def lifecycle_status(*, ingestion: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = verify_bundle()
    installed = INSTALL_ROOT.is_dir()
    enrolled = _safe_is_file(INSTALL_ROOT / "etc" / "client.keys")
    agent = _agent_status() if installed else {"running": False, "summary": ""}
    ingestion = ingestion if isinstance(ingestion, dict) else {}
    transport_authenticated = bool(ingestion.get("authenticated"))
    connected = bool(installed and enrolled and agent.get("running") and transport_authenticated)
    scanning = connected and int(ingestion.get("authenticated_event_count") or 0) > 0
    if scanning:
        lifecycle = "scanning"
    elif connected:
        lifecycle = "connected"
    elif installed and enrolled:
        lifecycle = "enrolled" if agent.get("running") else "degraded"
    elif installed:
        lifecycle = "installed"
    elif bundle["packaged"]:
        lifecycle = "packaged"
    elif bundle["package_present"]:
        lifecycle = "degraded"
    else:
        lifecycle = "unavailable"
    return {
        "provider": "wazuh",
        "lifecycle": lifecycle,
        "bundle": bundle,
        "installed": installed,
        "installed_version": _installed_version(),
        "enrolled": enrolled,
        "transport_authenticated": transport_authenticated,
        "connected": connected,
        "scanning": scanning,
        "agent": agent,
    }


def store_enrollment_key(secret: str, *, account: str = "default") -> dict[str, Any]:
    if not secret:
        raise ValueError("enrollment client key is required")
    if platform.system() != "Darwin":
        return {"status": "error", "stored": False, "message": "macOS Keychain is required"}
    security, core_foundation = _keychain_libraries()
    service_bytes = KEYCHAIN_SERVICE.encode("utf-8")
    account_bytes = account.encode("utf-8")
    secret_bytes = secret.encode("utf-8")
    item = ctypes.c_void_p()
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    found = security.SecKeychainFindGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        ctypes.byref(password_length),
        ctypes.byref(password_data),
        ctypes.byref(item),
    )
    if found == 0:
        security.SecKeychainItemFreeContent(None, password_data)
        status = security.SecKeychainItemModifyAttributesAndData(item, None, len(secret_bytes), secret_bytes)
    else:
        status = security.SecKeychainAddGenericPassword(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            len(secret_bytes),
            secret_bytes,
            ctypes.byref(item),
        )
    if item:
        core_foundation.CFRelease(item)
    return {
        "status": "ok" if status == 0 else "error",
        "stored": status == 0,
        "message": "" if status == 0 else f"macOS Keychain returned OSStatus {status}",
    }


def store_enrollment_secret(secret: str, *, account: str = "default") -> dict[str, Any]:
    """Compatibility alias; new callers store an API-created client key."""
    return store_enrollment_key(secret, account=account)


def delete_enrollment_key(*, account: str = "default") -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"status": "error", "deleted": False, "message": "macOS Keychain is required"}
    result = subprocess.run(
        ["/usr/bin/security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    # SecItemNotFound is also the desired terminal state for idempotent retry.
    deleted = result.returncode == 0 or "could not be found" in (result.stderr or "").lower()
    return {
        "status": "ok" if deleted else "error",
        "deleted": deleted,
        "message": "" if deleted else (result.stderr or result.stdout).strip()[:512],
    }


def _keychain_libraries():
    security = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
    core_foundation = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
    ]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    return security, core_foundation


def _load_enrollment_key(account: str = "default") -> str:
    if platform.system() != "Darwin":
        return ""
    security, core_foundation = _keychain_libraries()
    service_bytes = KEYCHAIN_SERVICE.encode("utf-8")
    account_bytes = account.encode("utf-8")
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        ctypes.byref(password_length),
        ctypes.byref(password_data),
        ctypes.byref(item),
    )
    if status != 0:
        return ""
    try:
        return ctypes.string_at(password_data, password_length.value).decode("utf-8")
    finally:
        security.SecKeychainItemFreeContent(None, password_data)
        if item:
            core_foundation.CFRelease(item)


def _load_enrollment_secret(account: str = "default") -> str:
    """Compatibility alias for pre-client-key tests and callers."""
    return _load_enrollment_key(account)


def install_with_authorization(
    *,
    manager: str,
    agent_name: str = "CleanHouse",
    agent_id: str = "",
    monitored_scope: str = "",
    keychain_account: str = "default",
) -> dict[str, Any]:
    """Invoke only the verified bundled package through macOS authorization."""
    if platform.system() != "Darwin":
        return {"status": "error", "message": "Wazuh agent installation requires macOS"}
    if not HOST_RE.fullmatch(manager):
        return {"status": "error", "message": "manager must be a hostname or IP literal without a scheme"}
    if not AGENT_NAME_RE.fullmatch(agent_name):
        return {"status": "error", "message": "agent_name is invalid"}
    if not re.fullmatch(r"[0-9]{3,8}", agent_id):
        return {"status": "error", "message": "agent_id is invalid"}
    try:
        resolved_scope = Path(monitored_scope).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {"status": "error", "message": "monitored_scope must be an existing directory"}
    if not resolved_scope.is_dir():
        return {"status": "error", "message": "monitored_scope must be an existing directory"}
    bundle = verify_bundle()
    if not bundle.get("packaged"):
        return {"status": "error", "message": "bundled Wazuh package is not verified", "bundle": bundle}
    secret = _load_enrollment_key(keychain_account)
    if not secret:
        return {"status": "error", "message": "Wazuh enrollment client key is not stored in Keychain"}
    materialized_package: Path | None = None
    materialized_helper: Path | None = None
    try:
        materialized_package = _materialize_verified_package()
        materialized_helper = _materialize_configure_helper()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if materialized_package is not None:
            try:
                materialized_package.unlink()
            except OSError:
                pass
        return {"status": "error", "message": str(exc)[:1024], "bundle": bundle}

    temp_path: Path | None = None
    try:
        payload = json.dumps({
            "manager": manager,
            "agent_name": agent_name,
            "agent_id": agent_id,
            "monitored_scope": str(resolved_scope),
            "client_key": secret,
        }, separators=(",", ":"))
        fd, raw_temp_path = tempfile.mkstemp(
            prefix="cleanhouse-wazuh-env-", dir="/private/tmp", text=True
        )
        temp_path = Path(raw_temp_path)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(temp_path, 0o600)
        expected_sha512 = shlex.quote(OFFICIAL_PACKAGE_SHA512)
        package_path = shlex.quote(str(materialized_package))
        helper_path = shlex.quote(str(materialized_helper))
        interpreter = shlex.quote(sys.executable)
        setup_path = shlex.quote(str(temp_path))
        command = (
            "umask 077; "
            f"test \"$(/usr/bin/shasum -a 512 {package_path} | /usr/bin/awk '{{print $1}}')\" = {expected_sha512} && "
            f"/usr/sbin/pkgutil --check-signature {package_path} >/dev/null && "
            f"/usr/sbin/installer -pkg {package_path} -target / && "
            f"{interpreter} {helper_path} {setup_path}; "
            f"result=$?; /bin/rm -f {setup_path}; exit $result"
        )
        apple_script_command = command.replace("\\", "\\\\").replace('"', '\\"')
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", f'do shell script "{apple_script_command}" with administrator privileges'],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        for materialized_path in (materialized_helper, materialized_package):
            if materialized_path is not None:
                try:
                    materialized_path.unlink()
                except OSError:
                    pass
    installed = result.returncode == 0
    keychain_cleanup = delete_enrollment_key(account=keychain_account) if installed else {
        "status": "retained",
        "deleted": False,
        "message": "Retained for idempotent installation retry",
    }
    return {
        "status": "ok" if installed else "error",
        "installed": installed,
        "message": "" if installed else (result.stderr or result.stdout).strip()[:1024],
        "enrollment_key_cleanup": keychain_cleanup,
        "lifecycle": lifecycle_status(),
    }
