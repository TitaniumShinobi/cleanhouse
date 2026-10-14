from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

from backend import wazuh_files


class _Response:
    def __init__(self, payload: bytes, *, content_length: str | None = None):
        self._payload = io.BytesIO(payload)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount: int = -1) -> bytes:
        return self._payload.read(amount)


class WazuhTransportBoundaryTests(unittest.TestCase):
    def tearDown(self):
        wazuh_files.stop_service(timeout=0.5)

    def test_external_http_and_embedded_credentials_are_rejected(self):
        headers = {"Authorization": "Bearer secret"}
        for url in (
            "http://wazuh.example/api/events",
            "https://user:password@wazuh.example/api/events",
            "https://wazuh.example/api/events#private-fragment",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
                wazuh_files._request_json(url, headers=headers)

    def test_loopback_http_is_an_explicit_development_exception(self):
        response = _Response(b'{"status":"ok"}')
        with patch.object(wazuh_files, "_open_response", return_value=response) as urlopen:
            result = wazuh_files._request_json("http://127.0.0.1:8000/status", headers={})

        self.assertEqual(result, {"status": "ok"})
        urlopen.assert_called_once()

    def test_response_body_is_bounded_even_without_content_length(self):
        response = _Response(b"{" + b"x" * 5000)
        with patch.dict(os.environ, {"CLEANHOUSE_WAZUH_MAX_RESPONSE_BYTES": "4096"}), patch.object(
            wazuh_files, "_open_response", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                wazuh_files._request_json("https://wazuh.example/status", headers={})

    def test_http_failure_does_not_echo_private_url_or_response_body(self):
        error = urllib.error.HTTPError(
            "https://private.internal/secret?token=forbidden",
            401,
            "body=credential-material",
            {},
            None,
        )
        with patch.object(wazuh_files, "_open_response", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                wazuh_files._request_json("https://wazuh.example/status", headers={})

        message = str(raised.exception)
        self.assertEqual(message, "Wazuh endpoint returned HTTP 401")
        self.assertNotIn("private.internal", message)
        self.assertNotIn("credential-material", message)

    def test_authenticated_destination_must_share_vvault_origin(self):
        with self.assertRaisesRegex(RuntimeError, "share the authenticated VVAULT origin"):
            wazuh_files._request_json(
                "https://attacker.example/events",
                headers={"Authorization": "Bearer secret"},
                credential_origin="https://vvault.example",
                transport=lambda _request: {},
            )

    def test_redirect_is_rejected_without_exposing_location(self):
        error = urllib.error.HTTPError(
            "https://vvault.example/events",
            302,
            "redirect",
            {"Location": "https://attacker.example/secret"},
            None,
        )
        with patch.object(wazuh_files, "_open_response", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "redirect was rejected") as raised:
                wazuh_files._request_json("https://vvault.example/events", headers={})
        self.assertNotIn("attacker.example", str(raised.exception))

    def test_service_does_not_start_without_authenticated_transport(self):
        config = {
            "events_url": "https://wazuh.example/events",
            "scope": "/scope",
        }
        with patch.object(wazuh_files, "_config", return_value=config), patch.object(
            wazuh_files, "_authorization_headers", return_value={}
        ), patch.object(
            wazuh_files, "status", return_value={
                "configured": False,
                "health": "unavailable",
                "operational": False,
            }
        ):
            result = wazuh_files.start_service()

        self.assertEqual(result["health"], "unavailable")
        self.assertIsNone(wazuh_files._THREAD)


class FilesWazuhServerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CLEANHOUSE_ENABLE_AUTH"] = "0"
        from backend import server

        cls.server = server

    def setUp(self):
        self.server._EVENTS_SERVICES_STARTED = False

    def test_optional_wazuh_failure_is_visible_without_blocking_runtime_warmup(self):
        completion = Mock()
        with patch.object(self.server, "_wait_for_listener_ready", return_value=True), patch.object(
            self.server.runtime_supervisor, "mark_backend_bootstrap_ready"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_started"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_complete", completion
        ), patch.object(
            self.server.cleanhouse_events, "init_db"
        ), patch.object(
            self.server.cleanhouse_events, "start_watcher", return_value={"status": "running"}
        ), patch.object(
            self.server.vvault_sync, "start_service", return_value={"status": "warming"}
        ), patch.object(
            self.server.wazuh_files, "start_service", side_effect=RuntimeError("private failure detail")
        ), patch.object(
            self.server, "start_network_history_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "start_network_collector_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "_start_runtime_heartbeat"
        ):
            self.server._start_events_services()

        result = completion.call_args.kwargs
        self.assertEqual(result["runtime_state"], "healthy")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["details"]["wazuh_files"]["status"], "degraded")
        self.assertEqual(result["details"]["wazuh_files"]["reason_code"], "wazuh_files_start_failed")
        self.assertEqual(result["details"]["wazuh_files"]["error"], "RuntimeError")
        self.assertNotIn("private failure detail", str(result))

    def test_files_preservation_worker_is_started_with_files_scope(self):
        completion = Mock()
        preservation_start = Mock(return_value={"status": "warming"})
        with patch.object(self.server, "_wait_for_listener_ready", return_value=True), patch.object(
            self.server.runtime_supervisor, "mark_backend_bootstrap_ready"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_started"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_complete", completion
        ), patch.object(
            self.server.cleanhouse_events, "init_db"
        ), patch.object(
            self.server.cleanhouse_events, "start_watcher", return_value={"status": "running"}
        ), patch.object(
            self.server.vvault_sync, "start_service", preservation_start
        ), patch.object(
            self.server.wazuh_files, "start_service", return_value={"health": "warming"}
        ), patch.object(
            self.server, "start_network_history_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "start_network_collector_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "_start_runtime_heartbeat"
        ):
            self.server._start_events_services()

        preservation_start.assert_called_once_with(surface="files")

    def test_wazuh_shutdown_failure_does_not_skip_other_services(self):
        calls: list[str] = []
        with patch.object(
            self.server.wazuh_files,
            "stop_service",
            side_effect=lambda **_kwargs: (calls.append("wazuh"), (_ for _ in ()).throw(RuntimeError()))[1],
        ), patch.object(
            self.server.vvault_sync, "stop_service", side_effect=lambda **_kwargs: calls.append("preservation")
        ), patch.object(
            self.server, "stop_network_collector_service", side_effect=lambda **_kwargs: calls.append("network")
        ), patch.object(
            self.server, "stop_network_history_service", side_effect=lambda: calls.append("history")
        ), patch.object(
            self.server.cleanhouse_events, "stop_events_services", side_effect=lambda: calls.append("events")
        ), patch.object(
            self.server.runtime_supervisor,
            "stop_backend_heartbeat",
            side_effect=lambda *_args: calls.append("heartbeat"),
        ):
            self.server._stop_events_services()

        self.assertEqual(calls, ["wazuh", "preservation", "network", "history", "events", "heartbeat"])

    def test_preservation_start_failure_is_visible_and_does_not_skip_wazuh(self):
        completion = Mock()
        wazuh_start = Mock(return_value={"health": "warming"})
        with patch.object(self.server, "_wait_for_listener_ready", return_value=True), patch.object(
            self.server.runtime_supervisor, "mark_backend_bootstrap_ready"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_started"
        ), patch.object(
            self.server.runtime_supervisor, "mark_backend_warmup_complete", completion
        ), patch.object(
            self.server.cleanhouse_events, "init_db"
        ), patch.object(
            self.server.cleanhouse_events, "start_watcher", return_value={"status": "running"}
        ), patch.object(
            self.server.vvault_sync, "start_service", side_effect=RuntimeError("private endpoint")
        ), patch.object(
            self.server.wazuh_files, "start_service", wazuh_start
        ), patch.object(
            self.server, "start_network_history_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "start_network_collector_service", return_value={"status": "running", "reason_code": ""}
        ), patch.object(
            self.server, "_start_runtime_heartbeat"
        ):
            self.server._start_events_services()

        result = completion.call_args.kwargs
        self.assertEqual(result["runtime_state"], "healthy")
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["details"]["files_preservation"]["reason_code"], "files_preservation_start_failed")
        self.assertNotIn("private endpoint", str(result))
        wazuh_start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
