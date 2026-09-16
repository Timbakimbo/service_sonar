import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.pipeline_status import (
    EVALUATION, REDDIT, SOURCES, configure_windows_safe_output, evaluator_action_status,
    evaluator_gate, run, validate_artifact,
)


def write_json(root: Path, relative_path: str, value) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def evaluation(actions, review_count=0):
    return {
        "schema_version": "1.0-de", "evaluator_run_id": "ER_current",
        "topic_evaluations": [{"topic_id": "1"}], "gap_evaluations": [],
        "innovation_evaluations": [], "aggregierte_aktionen": {},
        "review_count": review_count, "review_reasons": [], "aktionen": actions,
    }


def action(action_id, autonomy, action_type="keyword_add", stable_target="keyword:kita"):
    return {
        "evaluator_run_id": "ER_current", "action_id": action_id,
        "action_type": action_type, "stable_target": stable_target,
        "target": stable_target, "autonomy": autonomy,
    }


class ArtifactValidationTests(unittest.TestCase):
    def test_missing_invalid_empty_and_non_empty_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(validate_artifact(root, SOURCES), (False, "fehlt"))
            path = root / SOURCES.path; path.parent.mkdir(parents=True); path.write_text("{", encoding="utf-8")
            self.assertFalse(validate_artifact(root, SOURCES)[0])
            write_json(root, SOURCES.path, [])
            self.assertEqual(validate_artifact(root, SOURCES), (False, "Liste ist leer"))
            write_json(root, SOURCES.path, [{"url": "https://example.test"}])
            self.assertEqual(validate_artifact(root, SOURCES), (True, "valide"))


class PipelineStatusTests(unittest.TestCase):
    def test_windows_safe_output_configures_replacement_errors(self):
        class Stream:
            def __init__(self): self.errors = None
            def reconfigure(self, **kwargs): self.errors = kwargs.get("errors")
        stream = Stream()
        with patch("scripts.pipeline_status.sys.stdout", stream):
            configure_windows_safe_output()
        self.assertEqual(stream.errors, "replace")

    def test_only_unresolved_human_required_activates_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, EVALUATION.path, evaluation([
                action("H1", "human_required", "real_gap_review", "gap:g1:topic:1"),
                action("A1", "auto_apply", "topic_remove", "topic:2"),
                action("S1", "suggestion_only", "source_quality_warning", "source:reddit"),
            ], review_count=7))
            active, reasons = evaluator_gate(root)
            status = evaluator_action_status(root)
        self.assertTrue(active)
        self.assertEqual(reasons, ["human_required_actions: 1"])
        self.assertEqual(status["auto_actions_available"], 1)
        self.assertEqual(status["suggestions_available"], 1)

    def test_accepted_and_rejected_current_actions_close_gate(self):
        for state in ("accepted", "rejected"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); current = action("H1", "human_required")
                write_json(root, EVALUATION.path, evaluation([current]))
                write_json(root, "data/evaluation/human_decisions.json", {
                    "evaluator_run_id": "ER_current", "decisions": [{**current, "decision": state}]
                })
                self.assertEqual(evaluator_gate(root), (False, []))

    def test_deferred_current_action_remains_open_and_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); current = action("H1", "human_required")
            write_json(root, EVALUATION.path, evaluation([current]))
            write_json(root, "data/evaluation/human_decisions.json", {
                "evaluator_run_id": "ER_current", "decisions": [{**current, "decision": "deferred"}]
            })
            self.assertEqual(evaluator_gate(root), (True, ["human_required_actions: 1"]))

    def test_stale_decision_does_not_close_current_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); current = action("H1", "human_required")
            write_json(root, EVALUATION.path, evaluation([current]))
            write_json(root, "data/evaluation/human_decisions.json", {
                "evaluator_run_id": "ER_old", "decisions": [
                    {**current, "evaluator_run_id": "ER_old", "decision": "accepted"}
                ]
            })
            self.assertTrue(evaluator_gate(root)[0])
            self.assertEqual(evaluator_action_status(root)["stale_decisions_ignored"], 1)

    def test_text_and_json_output_separate_action_information(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, EVALUATION.path, evaluation([action("A1", "auto_apply")], review_count=5))
            with redirect_stdout(StringIO()) as text_output:
                run(root, "evaluator", as_json=False)
            with redirect_stdout(StringIO()) as json_output:
                run(root, "evaluator", as_json=True)
            payload = json.loads(json_output.getvalue())
        self.assertIn("auto_verfuegbar=1", text_output.getvalue())
        self.assertFalse(payload["human_gate"])
        self.assertEqual(payload["action_status"]["auto_actions_available"], 1)

    def test_legacy_evaluator_is_fresh_run_required_not_normal_human_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = evaluation([action("OLD", "human_required")])
            legacy.pop("evaluator_run_id")
            for item in legacy["aktionen"]:
                item.pop("evaluator_run_id")
                item.pop("stable_target")
            write_json(root, EVALUATION.path, legacy)
            with redirect_stdout(StringIO()) as text_output:
                run(root, "evaluator", as_json=False)
            with redirect_stdout(StringIO()) as json_output:
                run(root, "evaluator", as_json=True)
            payload = json.loads(json_output.getvalue())
        self.assertFalse(payload["human_gate"])
        self.assertTrue(payload["legacy_evaluator_output"])
        self.assertTrue(payload["fresh_evaluator_run_required"])
        self.assertEqual(payload["action_status"]["legacy_human_action_count"], 1)
        self.assertIn("LEGACY EVALUATOR OUTPUT", text_output.getvalue())

    def test_legacy_evaluator_without_actions_has_no_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); payload = evaluation([]); payload.pop("evaluator_run_id")
            write_json(root, EVALUATION.path, payload)
            self.assertEqual(evaluator_gate(root), (False, []))
            self.assertTrue(evaluator_action_status(root)["fresh_evaluator_run_required"])

    def test_source_discovery_ready_status_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            exit_code = run(Path(directory), "source-discovery")
        self.assertEqual(exit_code, 1)
        self.assertIn("READY", output.getvalue())
        self.assertIn("python -m agents.source_discovery_agent", output.getvalue())

    def test_reddit_blocked_metrics_are_visible_in_status(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            root = Path(directory)
            write_json(root, REDDIT.path, [{"url": "https://reddit.test", "text": "old corpus"}])
            write_json(root, "data/metrics.json", [{
                "source": "reddit", "attempted_requests": 10, "successful_requests": 0,
                "blocked_403_count": 10, "existing_data_preserved": True, "blocked_run": True,
            }])
            exit_code = run(root, "reddit-scraper")
        self.assertEqual(exit_code, 0)
        self.assertIn("OUTPUT VALID / BLOCKED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
