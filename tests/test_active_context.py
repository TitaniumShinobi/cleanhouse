import json
import tempfile
import unittest
from pathlib import Path

from backend.active_context import (
    ActiveContextCollector,
    FrontmostApp,
    TRUTH_INFERRED,
    TRUTH_MISSING,
    TRUTH_OBSERVED,
)


class ActiveContextCollectorTests(unittest.TestCase):
    def test_clipboard_prompt_requires_follow_and_chatgpt_or_codex_frontmost(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = ActiveContextCollector(
                frontmost_reader=lambda: FrontmostApp(app_name="ChatGPT", window_title="CleanHouse prompt", status="observed"),
                clipboard_reader=lambda: "Implement the active context lane",
                codex_root=Path(tmpdir) / "codex",
                pickup_paths_reader=lambda: [],
            )
            disabled = collector.collect(follow_enabled=False)
            self.assertEqual(disabled["truth_classification"], TRUTH_MISSING)
            self.assertFalse(disabled["attachable"])

            observed = collector.collect(follow_enabled=True)
            self.assertEqual(observed["source_type"], "clipboard")
            self.assertEqual(observed["truth_classification"], TRUTH_OBSERVED)
            self.assertEqual(observed["tool_identity"], "chatgpt")
            self.assertTrue(observed["attachable"])
            self.assertIn("active_window_observed", observed["source_labels"])
            self.assertIn("clipboard_observed", observed["source_labels"])

            ignored = collector.collect(follow_enabled=True, ignored_keys=[observed["dedupe_key"]])
            self.assertEqual(ignored["truth_classification"], TRUTH_MISSING)

    def test_export_file_pickup_is_operator_observed_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "exports"
            export_dir.mkdir()
            export_file = export_dir / "pickup.json"
            export_file.write_text(
                json.dumps({
                    "text": "Use this exported prompt",
                    "context": "operator approved export",
                    "current_repo": "/tmp/cleanhouse",
                    "tool_identity": "chatgpt",
                    "source_ref": "local://cleanhouse/test/export",
                }),
                encoding="utf-8",
            )
            collector = ActiveContextCollector(
                frontmost_reader=lambda: FrontmostApp(app_name="TextEdit", window_title="pickup", status="observed"),
                clipboard_reader=lambda: "",
                codex_root=Path(tmpdir) / "codex",
                pickup_paths_reader=lambda: [export_dir],
            )

            context = collector.collect(follow_enabled=True)
            self.assertEqual(context["source_type"], "export_file")
            self.assertEqual(context["active_prompt"], "Use this exported prompt")
            self.assertEqual(context["current_repo"], "/tmp/cleanhouse")
            self.assertEqual(context["truth_classification"], TRUTH_OBSERVED)
            self.assertTrue(context["attachable"])

    def test_codex_session_index_and_rollout_metadata_are_parsed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_root = Path(tmpdir) / "codex"
            sessions_dir = codex_root / "sessions"
            sessions_dir.mkdir(parents=True)
            thread_id = "019e-active-context-thread"
            (codex_root / "session_index.jsonl").write_text(
                json.dumps({"id": thread_id, "thread_name": "CleanHouse active context", "updated_at": "2026-05-28T12:00:00Z"}) + "\n",
                encoding="utf-8",
            )
            (sessions_dir / f"{thread_id}.jsonl").write_text(
                "\n".join([
                    json.dumps({"type": "session_meta", "payload": {"id": thread_id, "cwd": "/Users/devonwoodson/Documents/GitHub/cleanhouse"}}),
                    json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "Implement active context"}]}}),
                    json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": "Reading the codebase"}]}}),
                ]),
                encoding="utf-8",
            )
            collector = ActiveContextCollector(
                frontmost_reader=lambda: FrontmostApp(app_name="Codex", window_title="CleanHouse", status="observed"),
                clipboard_reader=lambda: "",
                codex_root=codex_root,
                pickup_paths_reader=lambda: [],
            )

            context = collector.collect(follow_enabled=False)
            self.assertEqual(context["truth_classification"], TRUTH_MISSING)
            self.assertFalse(context["attachable"])

            observed = collector.collect(follow_enabled=True)
            self.assertEqual(observed["source_type"], "codex_artifact")
            self.assertEqual(observed["session_id"], thread_id)
            self.assertEqual(observed["current_repo"], "/Users/devonwoodson/Documents/GitHub/cleanhouse")
            self.assertEqual(observed["active_prompt"], "Implement active context")
            self.assertEqual(observed["last_agent_action"], "Reading the codebase")
            self.assertEqual(observed["truth_classification"], TRUTH_OBSERVED)

    def test_codex_session_index_without_rollout_is_truthfully_inferred(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_root = Path(tmpdir) / "codex"
            codex_root.mkdir()
            (codex_root / "session_index.jsonl").write_text(
                json.dumps({"id": "thread-without-rollout", "thread_name": "Indexed only"}) + "\n",
                encoding="utf-8",
            )
            collector = ActiveContextCollector(
                frontmost_reader=lambda: FrontmostApp(app_name="Codex", window_title="", status="observed"),
                clipboard_reader=lambda: "",
                codex_root=codex_root,
                pickup_paths_reader=lambda: [],
            )

            context = collector.collect(follow_enabled=False)
            self.assertEqual(context["truth_classification"], TRUTH_MISSING)

            inferred = collector.collect(follow_enabled=True)
            self.assertEqual(inferred["source_type"], "codex_artifact")
            self.assertEqual(inferred["truth_classification"], TRUTH_INFERRED)
            self.assertIn("codex_rollout_missing", inferred["source_labels"])


if __name__ == "__main__":
    unittest.main()
